"""fleet-svc 資料存取(asyncpg)。SQL 集中此處;純函式部分(PATCH builder、row 映射)可單測。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from fleet_svc.models import (
    Device,
    DeviceCreate,
    DeviceFirmware,
    DeviceStatusView,
    DeviceUpdate,
    Firmware,
    FirmwareCreate,
    Fleet,
    FleetCreate,
)

# 在線判定門檻(秒):遙測 1 Hz,last_seen 超過此值視為離線
ONLINE_THRESHOLD_S = 10

_DEVICE_COLS = (
    "id, serial, name, fleet_id, model, status, cert_fingerprint, cert_not_after, created_at"
)
_FLEET_COLS = "id, name, org_id, created_at"
_FIRMWARE_COLS = "id, component, version, released_at, sbom_ref, created_at"

# PATCH 可更新的欄位白名單(防注入:欄位名不來自使用者輸入)
_DEVICE_PATCH_FIELDS = ("name", "fleet_id", "model", "status")


def build_device_patch(update: DeviceUpdate, start_index: int = 1) -> tuple[str, list[Any]]:
    """把 DeviceUpdate 的非 None 欄位組成 `col = $n` 片段與值清單(純函式,可單測)。

    回傳 ("name = $1, status = $2", [值...]);無任何欄位時回傳 ("", [])。
    """
    sets: list[str] = []
    values: list[Any] = []
    data = update.model_dump(exclude_unset=True)
    idx = start_index
    for field in _DEVICE_PATCH_FIELDS:
        if field in data:
            value = data[field]
            # enum → 其值;UUID 保留(asyncpg 接受)
            if hasattr(value, "value"):
                value = value.value
            sets.append(f"{field} = ${idx}")
            values.append(value)
            idx += 1
    return ", ".join(sets), values


def _device(r: asyncpg.Record) -> Device:
    return Device.model_validate(dict(r))


def _fleet(r: asyncpg.Record) -> Fleet:
    return Fleet.model_validate(dict(r))


def _firmware(r: asyncpg.Record) -> Firmware:
    return Firmware.model_validate(dict(r))


# ---- fleet ----
async def create_fleet(conn: asyncpg.Connection, body: FleetCreate) -> Fleet:
    r = await conn.fetchrow(
        f"INSERT INTO fleet.fleet (name, org_id) VALUES ($1, $2) RETURNING {_FLEET_COLS}",
        body.name,
        body.org_id,
    )
    return _fleet(r)


async def list_fleets(
    conn: asyncpg.Connection, limit: int = 100, offset: int = 0
) -> list[Fleet]:
    rows = await conn.fetch(
        f"SELECT {_FLEET_COLS} FROM fleet.fleet ORDER BY created_at DESC LIMIT $1 OFFSET $2",
        limit,
        offset,
    )
    return [_fleet(r) for r in rows]


async def count_fleets(conn: asyncpg.Connection) -> int:
    return await conn.fetchval("SELECT count(*) FROM fleet.fleet")


async def get_fleet(conn: asyncpg.Connection, fleet_id: UUID) -> Fleet | None:
    r = await conn.fetchrow(f"SELECT {_FLEET_COLS} FROM fleet.fleet WHERE id = $1", fleet_id)
    return _fleet(r) if r else None


# ---- device ----
async def create_device(conn: asyncpg.Connection, body: DeviceCreate) -> Device:
    r = await conn.fetchrow(
        "INSERT INTO fleet.device (serial, name, fleet_id, model) "
        f"VALUES ($1, $2, $3, $4) RETURNING {_DEVICE_COLS}",
        body.serial,
        body.name,
        body.fleet_id,
        body.model,
    )
    return _device(r)


async def list_devices(
    conn: asyncpg.Connection, fleet_id: UUID | None = None, limit: int = 100, offset: int = 0
) -> list[Device]:
    if fleet_id is not None:
        rows = await conn.fetch(
            f"SELECT {_DEVICE_COLS} FROM fleet.device WHERE fleet_id = $1 "
            "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            fleet_id,
            limit,
            offset,
        )
    else:
        rows = await conn.fetch(
            f"SELECT {_DEVICE_COLS} FROM fleet.device ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
    return [_device(r) for r in rows]


async def count_devices(conn: asyncpg.Connection, fleet_id: UUID | None = None) -> int:
    if fleet_id is not None:
        return await conn.fetchval(
            "SELECT count(*) FROM fleet.device WHERE fleet_id = $1", fleet_id
        )
    return await conn.fetchval("SELECT count(*) FROM fleet.device")


async def get_device(conn: asyncpg.Connection, device_id: UUID) -> Device | None:
    r = await conn.fetchrow(f"SELECT {_DEVICE_COLS} FROM fleet.device WHERE id = $1", device_id)
    return _device(r) if r else None


async def update_device(
    conn: asyncpg.Connection, device_id: UUID, update: DeviceUpdate
) -> Device | None:
    set_clause, values = build_device_patch(update, start_index=1)
    if not set_clause:
        return await get_device(conn, device_id)
    id_index = len(values) + 1
    r = await conn.fetchrow(
        f"UPDATE fleet.device SET {set_clause} WHERE id = ${id_index} RETURNING {_DEVICE_COLS}",
        *values,
        device_id,
    )
    return _device(r) if r else None


async def delete_device(conn: asyncpg.Connection, device_id: UUID) -> bool:
    result = await conn.execute("DELETE FROM fleet.device WHERE id = $1", device_id)
    return result.endswith("1")


# ---- firmware ----
async def create_firmware(conn: asyncpg.Connection, body: FirmwareCreate) -> Firmware:
    r = await conn.fetchrow(
        "INSERT INTO fleet.firmware_version (component, version, released_at, sbom_ref) "
        f"VALUES ($1, $2, $3, $4) RETURNING {_FIRMWARE_COLS}",
        body.component.value,
        body.version,
        body.released_at,
        body.sbom_ref,
    )
    return _firmware(r)


async def list_firmware(conn: asyncpg.Connection) -> list[Firmware]:
    rows = await conn.fetch(
        f"SELECT {_FIRMWARE_COLS} FROM fleet.firmware_version ORDER BY created_at DESC"
    )
    return [_firmware(r) for r in rows]


async def set_device_firmware(
    conn: asyncpg.Connection, device_id: UUID, component: str, version: str
) -> DeviceFirmware:
    r = await conn.fetchrow(
        "INSERT INTO fleet.device_firmware (device_id, component, version) "
        "VALUES ($1, $2, $3) "
        "ON CONFLICT (device_id, component) DO UPDATE SET version = EXCLUDED.version, "
        "installed_at = now() "
        "RETURNING device_id, component, version, installed_at",
        device_id,
        component,
        version,
    )
    return DeviceFirmware.model_validate(dict(r))


async def list_device_firmware(
    conn: asyncpg.Connection, device_id: UUID
) -> list[DeviceFirmware]:
    rows = await conn.fetch(
        "SELECT device_id, component, version, installed_at FROM fleet.device_firmware "
        "WHERE device_id = $1 ORDER BY component",
        device_id,
    )
    return [DeviceFirmware.model_validate(dict(r)) for r in rows]


# ---- status(device ⨝ device_state) ----
_STATUS_SELECT = """
SELECT d.id AS device_id, d.serial, d.name, d.fleet_id, d.status,
       (s.last_seen IS NOT NULL AND s.last_seen > now() - make_interval(secs => $1)) AS online,
       s.last_seen, s.lat_deg, s.lon_deg, s.rel_alt_m, s.battery_pct, s.flight_mode, s.armed
FROM fleet.device d
LEFT JOIN fleet.device_state s ON s.drone_id = d.serial
"""


def _status(r: asyncpg.Record) -> DeviceStatusView:
    return DeviceStatusView.model_validate(dict(r))


async def get_device_status(
    conn: asyncpg.Connection, device_id: UUID, threshold_s: int = ONLINE_THRESHOLD_S
) -> DeviceStatusView | None:
    r = await conn.fetchrow(_STATUS_SELECT + " WHERE d.id = $2", threshold_s, device_id)
    return _status(r) if r else None


async def list_fleet_status(
    conn: asyncpg.Connection, fleet_id: UUID, threshold_s: int = ONLINE_THRESHOLD_S
) -> list[DeviceStatusView]:
    rows = await conn.fetch(
        _STATUS_SELECT + " WHERE d.fleet_id = $2 ORDER BY d.serial", threshold_s, fleet_id
    )
    return [_status(r) for r in rows]


async def list_all_status(
    conn: asyncpg.Connection, threshold_s: int = ONLINE_THRESHOLD_S
) -> list[DeviceStatusView]:
    rows = await conn.fetch(_STATUS_SELECT + " ORDER BY d.serial", threshold_s)
    return [_status(r) for r in rows]

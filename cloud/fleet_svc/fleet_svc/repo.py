"""fleet-svc 資料存取(asyncpg)。SQL 集中此處;純函式部分(PATCH builder、row 映射)可單測。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg

from fleet_svc.models import (
    AuditEntry,
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
    "id, serial, name, fleet_id, org_id, model, status, "
    "cert_fingerprint, cert_not_after, created_at"
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


# ---- 租戶(G11)過濾小工具 ----
# org 語義:None = 不加 org 過濾(admin 跨 org / 內部呼叫);字串 = WHERE org_id = 該值。
def _where(conds: list[str]) -> str:
    return (" WHERE " + " AND ".join(conds)) if conds else ""


# ---- fleet ----
async def create_fleet(conn: asyncpg.Connection, body: FleetCreate, org: str) -> Fleet:
    """建立機隊。org 一律取自呼叫者 claim(不採信 client),寫入為租戶邊界。"""
    r = await conn.fetchrow(
        f"INSERT INTO fleet.fleet (name, org_id) VALUES ($1, $2) RETURNING {_FLEET_COLS}",
        body.name,
        org,
    )
    return _fleet(r)


async def list_fleets(
    conn: asyncpg.Connection, org: str | None = None, limit: int = 100, offset: int = 0
) -> list[Fleet]:
    conds: list[str] = []
    params: list[Any] = []
    if org is not None:
        params.append(org)
        conds.append(f"org_id = ${len(params)}")
    params.append(limit)
    lim = len(params)
    params.append(offset)
    off = len(params)
    rows = await conn.fetch(
        f"SELECT {_FLEET_COLS} FROM fleet.fleet{_where(conds)} "
        f"ORDER BY created_at DESC LIMIT ${lim} OFFSET ${off}",
        *params,
    )
    return [_fleet(r) for r in rows]


async def count_fleets(conn: asyncpg.Connection, org: str | None = None) -> int:
    if org is not None:
        return await conn.fetchval("SELECT count(*) FROM fleet.fleet WHERE org_id = $1", org)
    return await conn.fetchval("SELECT count(*) FROM fleet.fleet")


async def get_fleet(
    conn: asyncpg.Connection, fleet_id: UUID, org: str | None = None
) -> Fleet | None:
    """依 id 取機隊;org 指定時加租戶過濾(跨 org 回 None → 端點轉 404,不洩存在性)。"""
    if org is not None:
        r = await conn.fetchrow(
            f"SELECT {_FLEET_COLS} FROM fleet.fleet WHERE id = $1 AND org_id = $2",
            fleet_id,
            org,
        )
    else:
        r = await conn.fetchrow(f"SELECT {_FLEET_COLS} FROM fleet.fleet WHERE id = $1", fleet_id)
    return _fleet(r) if r else None


# ---- device ----
async def create_device(conn: asyncpg.Connection, body: DeviceCreate, org: str) -> Device:
    """建立裝置。org 取自呼叫者 claim(不採信 client),與 fleet 綁定無關(裝置可無 fleet)。"""
    r = await conn.fetchrow(
        "INSERT INTO fleet.device (serial, name, fleet_id, org_id, model) "
        f"VALUES ($1, $2, $3, $4, $5) RETURNING {_DEVICE_COLS}",
        body.serial,
        body.name,
        body.fleet_id,
        org,
        body.model,
    )
    return _device(r)


async def list_devices(
    conn: asyncpg.Connection,
    fleet_id: UUID | None = None,
    org: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Device]:
    conds: list[str] = []
    params: list[Any] = []
    if fleet_id is not None:
        params.append(fleet_id)
        conds.append(f"fleet_id = ${len(params)}")
    if org is not None:
        params.append(org)
        conds.append(f"org_id = ${len(params)}")
    params.append(limit)
    lim = len(params)
    params.append(offset)
    off = len(params)
    rows = await conn.fetch(
        f"SELECT {_DEVICE_COLS} FROM fleet.device{_where(conds)} "
        f"ORDER BY created_at DESC LIMIT ${lim} OFFSET ${off}",
        *params,
    )
    return [_device(r) for r in rows]


async def count_devices(
    conn: asyncpg.Connection, fleet_id: UUID | None = None, org: str | None = None
) -> int:
    conds: list[str] = []
    params: list[Any] = []
    if fleet_id is not None:
        params.append(fleet_id)
        conds.append(f"fleet_id = ${len(params)}")
    if org is not None:
        params.append(org)
        conds.append(f"org_id = ${len(params)}")
    return await conn.fetchval(f"SELECT count(*) FROM fleet.device{_where(conds)}", *params)


async def get_device(
    conn: asyncpg.Connection, device_id: UUID, org: str | None = None
) -> Device | None:
    """依 id 取裝置;org 指定時加租戶過濾(跨 org 回 None → 端點轉 404,不洩存在性)。"""
    if org is not None:
        r = await conn.fetchrow(
            f"SELECT {_DEVICE_COLS} FROM fleet.device WHERE id = $1 AND org_id = $2",
            device_id,
            org,
        )
    else:
        r = await conn.fetchrow(
            f"SELECT {_DEVICE_COLS} FROM fleet.device WHERE id = $1", device_id
        )
    return _device(r) if r else None


async def update_device(
    conn: asyncpg.Connection, device_id: UUID, update: DeviceUpdate, org: str | None = None
) -> Device | None:
    set_clause, values = build_device_patch(update, start_index=1)
    if not set_clause:
        return await get_device(conn, device_id, org)
    id_index = len(values) + 1
    where = f"id = ${id_index}"
    args: list[Any] = [*values, device_id]
    if org is not None:
        args.append(org)
        where += f" AND org_id = ${id_index + 1}"
    r = await conn.fetchrow(
        f"UPDATE fleet.device SET {set_clause} WHERE {where} RETURNING {_DEVICE_COLS}",
        *args,
    )
    return _device(r) if r else None


async def delete_device(
    conn: asyncpg.Connection, device_id: UUID, org: str | None = None
) -> bool:
    if org is not None:
        result = await conn.execute(
            "DELETE FROM fleet.device WHERE id = $1 AND org_id = $2", device_id, org
        )
    else:
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
    conn: asyncpg.Connection,
    device_id: UUID,
    org: str | None = None,
    threshold_s: int = ONLINE_THRESHOLD_S,
) -> DeviceStatusView | None:
    if org is not None:
        r = await conn.fetchrow(
            _STATUS_SELECT + " WHERE d.id = $2 AND d.org_id = $3", threshold_s, device_id, org
        )
    else:
        r = await conn.fetchrow(_STATUS_SELECT + " WHERE d.id = $2", threshold_s, device_id)
    return _status(r) if r else None


async def list_fleet_status(
    conn: asyncpg.Connection,
    fleet_id: UUID,
    org: str | None = None,
    threshold_s: int = ONLINE_THRESHOLD_S,
) -> list[DeviceStatusView]:
    if org is not None:
        rows = await conn.fetch(
            _STATUS_SELECT + " WHERE d.fleet_id = $2 AND d.org_id = $3 ORDER BY d.serial",
            threshold_s,
            fleet_id,
            org,
        )
    else:
        rows = await conn.fetch(
            _STATUS_SELECT + " WHERE d.fleet_id = $2 ORDER BY d.serial", threshold_s, fleet_id
        )
    return [_status(r) for r in rows]


async def list_all_status(
    conn: asyncpg.Connection, org: str | None = None, threshold_s: int = ONLINE_THRESHOLD_S
) -> list[DeviceStatusView]:
    if org is not None:
        rows = await conn.fetch(
            _STATUS_SELECT + " WHERE d.org_id = $2 ORDER BY d.serial", threshold_s, org
        )
    else:
        rows = await conn.fetch(_STATUS_SELECT + " ORDER BY d.serial", threshold_s)
    return [_status(r) for r in rows]


async def list_org_serials(conn: asyncpg.Connection, org: str) -> set[str]:
    """回傳某租戶的所有裝置 serial(=遙測 drone_id)。供 SSE 串流依 org 過濾(G11b):
    遙測 hub 以 drone_id 為鍵,非 admin 訂閱者只放行本 org 裝置的即時遙測。"""
    rows = await conn.fetch("SELECT serial FROM fleet.device WHERE org_id = $1", org)
    return {r["serial"] for r in rows}


# ---- audit(G14 稽核查詢;寫入在 fleet_svc.audit) ----
_AUDIT_COLS = "id, at, actor, role, action, resource_type, resource_id, details, source_ip"


def _audit(r: asyncpg.Record) -> AuditEntry:
    d = dict(r)
    # jsonb 由 asyncpg 以字串回傳(未設 codec);轉回 dict 供模型
    if isinstance(d.get("details"), str):
        d["details"] = json.loads(d["details"])
    return AuditEntry.model_validate(d)


async def list_audit(
    conn: asyncpg.Connection,
    resource_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditEntry]:
    if resource_type is not None:
        rows = await conn.fetch(
            f"SELECT {_AUDIT_COLS} FROM fleet.audit_log WHERE resource_type = $1 "
            "ORDER BY at DESC, id DESC LIMIT $2 OFFSET $3",
            resource_type,
            limit,
            offset,
        )
    else:
        rows = await conn.fetch(
            f"SELECT {_AUDIT_COLS} FROM fleet.audit_log "
            "ORDER BY at DESC, id DESC LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
    return [_audit(r) for r in rows]


async def count_audit(conn: asyncpg.Connection, resource_type: str | None = None) -> int:
    if resource_type is not None:
        return await conn.fetchval(
            "SELECT count(*) FROM fleet.audit_log WHERE resource_type = $1", resource_type
        )
    return await conn.fetchval("SELECT count(*) FROM fleet.audit_log")

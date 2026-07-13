"""fleet-svc:機隊/裝置/韌體版本管理(對 docs/20-software/cloud-fleet.md §3「裝置註冊/機隊儀表板」)。

Phase 0→1 服務層。FastAPI + asyncpg,沿用 cloud/log_svc 的 lifespan/純函式範式。
裝置在線狀態/最後位置(遙測消費者 + SSE)屬 B2,不在本檔。

資料落既有 timescaledb 實例的 `fleet` schema(migrations/*.sql,啟動時前向套用)。
環境變數:PG_DSN。
"""

import logging
import os
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg
from fastapi import FastAPI, HTTPException, Query

from fleet_svc import repo
from fleet_svc.migrate import apply_migrations
from fleet_svc.models import (
    Device,
    DeviceCreate,
    DeviceFirmware,
    DeviceFirmwareSet,
    DeviceUpdate,
    Firmware,
    FirmwareCreate,
    Fleet,
    FleetCreate,
)

log = logging.getLogger("fleet_svc")

PG_DSN = os.environ.get("PG_DSN", "postgresql://drone:dronedev@localhost:5432/drone")
PG_CONNECT_ATTEMPTS = 30  # 啟動等 DB 就緒:最多 30 次、每 2 秒(同 ingest/log_svc)
PG_CONNECT_RETRY_S = 2


async def _connect_pool() -> asyncpg.Pool:
    import asyncio

    for attempt in range(1, PG_CONNECT_ATTEMPTS + 1):
        try:
            return await asyncpg.create_pool(PG_DSN, min_size=1, max_size=8, command_timeout=10)
        except (asyncpg.PostgresError, OSError) as e:
            if attempt == PG_CONNECT_ATTEMPTS:
                raise
            log.warning("PostgreSQL 連線失敗(%d/%d):%s;重試", attempt, PG_CONNECT_ATTEMPTS, e)
            await asyncio.sleep(PG_CONNECT_RETRY_S)
    raise RuntimeError("unreachable")


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await _connect_pool()
    async with pool.acquire() as conn:
        applied = await apply_migrations(conn)
        if applied:
            log.info("已套用 migration:%s", ", ".join(applied))
    app.state.pool = pool
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="fleet-svc", lifespan=lifespan)


def _pool(app: FastAPI) -> asyncpg.Pool:
    return app.state.pool


# ---- health ----
@app.get("/healthz")
async def healthz() -> dict:
    async with _pool(app).acquire() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}


# ---- fleets ----
@app.post("/api/v1/fleets", response_model=Fleet, status_code=201)
async def create_fleet(body: FleetCreate) -> Fleet:
    async with _pool(app).acquire() as conn:
        return await repo.create_fleet(conn, body)


@app.get("/api/v1/fleets", response_model=list[Fleet])
async def list_fleets() -> list[Fleet]:
    async with _pool(app).acquire() as conn:
        return await repo.list_fleets(conn)


@app.get("/api/v1/fleets/{fleet_id}", response_model=Fleet)
async def get_fleet(fleet_id: UUID) -> Fleet:
    async with _pool(app).acquire() as conn:
        f = await repo.get_fleet(conn, fleet_id)
    if f is None:
        raise HTTPException(status_code=404, detail="fleet 不存在")
    return f


# ---- devices ----
@app.post("/api/v1/devices", response_model=Device, status_code=201)
async def create_device(body: DeviceCreate) -> Device:
    async with _pool(app).acquire() as conn:
        try:
            return await repo.create_device(conn, body)
        except asyncpg.UniqueViolationError:
            raise HTTPException(status_code=409, detail=f"serial 已存在:{body.serial}")


@app.get("/api/v1/devices", response_model=list[Device])
async def list_devices(fleet_id: UUID | None = Query(default=None)) -> list[Device]:
    async with _pool(app).acquire() as conn:
        return await repo.list_devices(conn, fleet_id)


@app.get("/api/v1/devices/{device_id}", response_model=Device)
async def get_device(device_id: UUID) -> Device:
    async with _pool(app).acquire() as conn:
        d = await repo.get_device(conn, device_id)
    if d is None:
        raise HTTPException(status_code=404, detail="device 不存在")
    return d


@app.patch("/api/v1/devices/{device_id}", response_model=Device)
async def update_device(device_id: UUID, body: DeviceUpdate) -> Device:
    async with _pool(app).acquire() as conn:
        d = await repo.update_device(conn, device_id, body)
    if d is None:
        raise HTTPException(status_code=404, detail="device 不存在")
    return d


@app.delete("/api/v1/devices/{device_id}", status_code=204)
async def delete_device(device_id: UUID) -> None:
    async with _pool(app).acquire() as conn:
        ok = await repo.delete_device(conn, device_id)
    if not ok:
        raise HTTPException(status_code=404, detail="device 不存在")


# ---- firmware ----
@app.post("/api/v1/firmware", response_model=Firmware, status_code=201)
async def create_firmware(body: FirmwareCreate) -> Firmware:
    async with _pool(app).acquire() as conn:
        try:
            return await repo.create_firmware(conn, body)
        except asyncpg.UniqueViolationError:
            raise HTTPException(
                status_code=409, detail=f"{body.component.value} {body.version} 已存在"
            )


@app.get("/api/v1/firmware", response_model=list[Firmware])
async def list_firmware() -> list[Firmware]:
    async with _pool(app).acquire() as conn:
        return await repo.list_firmware(conn)


@app.put("/api/v1/devices/{device_id}/firmware", response_model=DeviceFirmware)
async def set_device_firmware(device_id: UUID, body: DeviceFirmwareSet) -> DeviceFirmware:
    async with _pool(app).acquire() as conn:
        d = await repo.get_device(conn, device_id)
        if d is None:
            raise HTTPException(status_code=404, detail="device 不存在")
        return await repo.set_device_firmware(conn, device_id, body.component.value, body.version)


@app.get("/api/v1/devices/{device_id}/firmware", response_model=list[DeviceFirmware])
async def list_device_firmware(device_id: UUID) -> list[DeviceFirmware]:
    async with _pool(app).acquire() as conn:
        return await repo.list_device_firmware(conn, device_id)

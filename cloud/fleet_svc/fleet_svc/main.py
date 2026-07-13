"""fleet-svc:機隊/裝置/韌體版本管理(對 docs/20-software/cloud-fleet.md §3「裝置註冊/機隊儀表板」)。

Phase 0→1 服務層。FastAPI + asyncpg,沿用 cloud/log_svc 的 lifespan/純函式範式。
裝置在線狀態/最後位置(遙測消費者 + SSE)屬 B2,不在本檔。

資料落既有 timescaledb 實例的 `fleet` schema(migrations/*.sql,啟動時前向套用)。
環境變數:PG_DSN。
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from fleet_svc import metrics, repo
from fleet_svc.auth import AUTH_ENABLED, authorize_token, require_role
from fleet_svc.consumer import run_consumer
from fleet_svc.hub import TelemetryHub
from fleet_svc.migrate import apply_migrations
from fleet_svc.models import (
    Device,
    DeviceCreate,
    DeviceFirmware,
    DeviceFirmwareSet,
    DeviceStatusView,
    DeviceUpdate,
    Firmware,
    FirmwareCreate,
    Fleet,
    FleetCreate,
)

log = logging.getLogger("fleet_svc")

PG_DSN = os.environ.get("PG_DSN", "postgresql://drone:dronedev@localhost:5432/drone")
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
PG_CONNECT_ATTEMPTS = 30  # 啟動等 DB 就緒:最多 30 次、每 2 秒(同 ingest/log_svc)
PG_CONNECT_RETRY_S = 2
SSE_KEEPALIVE_S = 15  # 無資料時定期送註解行,避免代理斷連


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
    hub = TelemetryHub()
    app.state.pool = pool
    app.state.hub = hub
    consumer = asyncio.create_task(run_consumer(pool, hub, MQTT_HOST, MQTT_PORT))
    try:
        yield
    finally:
        consumer.cancel()
        try:
            await consumer
        except asyncio.CancelledError:
            pass
        await pool.close()


app = FastAPI(title="fleet-svc", lifespan=lifespan)
metrics.instrument(app)  # /metrics(Prometheus)+ HTTP 指標 middleware(G13)

if not AUTH_ENABLED:
    log.warning("⚠ JWT 認證未啟用(dev 模式,全放行)——正式部署須設 JWT_SECRET 或 JWT_JWKS_URL")

# RBAC 依賴:讀取需 viewer,變更需 operator(healthz 不設,供 compose healthcheck)
VIEWER = Depends(require_role("viewer"))
OPERATOR = Depends(require_role("operator"))


def _pool(app: FastAPI) -> asyncpg.Pool:
    return app.state.pool


# 分頁(G12):list 端點加 limit/offset,預設上限 100(避免回全表);
# 向後相容——回應本體仍是既有陣列,total/limit/offset 走回應標頭(X-Total-Count 等),
# 不改 response_model、不破壞既有測試/煙霧。
PAGE_LIMIT_DEFAULT = 100
PAGE_LIMIT_MAX = 1000


def _set_page_headers(response: Response, total: int, limit: int, offset: int) -> None:
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)


# ---- health ----
@app.get("/healthz")
async def healthz() -> dict:
    async with _pool(app).acquire() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}


# ---- fleets ----
@app.post("/api/v1/fleets", response_model=Fleet, status_code=201, dependencies=[OPERATOR])
async def create_fleet(body: FleetCreate) -> Fleet:
    async with _pool(app).acquire() as conn:
        return await repo.create_fleet(conn, body)


@app.get("/api/v1/fleets", response_model=list[Fleet], dependencies=[VIEWER])
async def list_fleets(
    response: Response,
    limit: int = Query(default=PAGE_LIMIT_DEFAULT, ge=1, le=PAGE_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
) -> list[Fleet]:
    async with _pool(app).acquire() as conn:
        total = await repo.count_fleets(conn)
        items = await repo.list_fleets(conn, limit=limit, offset=offset)
    _set_page_headers(response, total, limit, offset)
    return items


@app.get("/api/v1/fleets/{fleet_id}", response_model=Fleet, dependencies=[VIEWER])
async def get_fleet(fleet_id: UUID) -> Fleet:
    async with _pool(app).acquire() as conn:
        f = await repo.get_fleet(conn, fleet_id)
    if f is None:
        raise HTTPException(status_code=404, detail="fleet 不存在")
    return f


# ---- devices ----
@app.post("/api/v1/devices", response_model=Device, status_code=201, dependencies=[OPERATOR])
async def create_device(body: DeviceCreate) -> Device:
    async with _pool(app).acquire() as conn:
        try:
            return await repo.create_device(conn, body)
        except asyncpg.UniqueViolationError:
            raise HTTPException(status_code=409, detail=f"serial 已存在:{body.serial}")


@app.get("/api/v1/devices", response_model=list[Device], dependencies=[VIEWER])
async def list_devices(
    response: Response,
    fleet_id: UUID | None = Query(default=None),
    limit: int = Query(default=PAGE_LIMIT_DEFAULT, ge=1, le=PAGE_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
) -> list[Device]:
    async with _pool(app).acquire() as conn:
        total = await repo.count_devices(conn, fleet_id)
        items = await repo.list_devices(conn, fleet_id, limit=limit, offset=offset)
    _set_page_headers(response, total, limit, offset)
    return items


@app.get("/api/v1/devices/{device_id}", response_model=Device, dependencies=[VIEWER])
async def get_device(device_id: UUID) -> Device:
    async with _pool(app).acquire() as conn:
        d = await repo.get_device(conn, device_id)
    if d is None:
        raise HTTPException(status_code=404, detail="device 不存在")
    return d


@app.patch("/api/v1/devices/{device_id}", response_model=Device, dependencies=[OPERATOR])
async def update_device(device_id: UUID, body: DeviceUpdate) -> Device:
    async with _pool(app).acquire() as conn:
        d = await repo.update_device(conn, device_id, body)
    if d is None:
        raise HTTPException(status_code=404, detail="device 不存在")
    return d


@app.delete("/api/v1/devices/{device_id}", status_code=204, dependencies=[OPERATOR])
async def delete_device(device_id: UUID) -> None:
    async with _pool(app).acquire() as conn:
        ok = await repo.delete_device(conn, device_id)
    if not ok:
        raise HTTPException(status_code=404, detail="device 不存在")


# ---- firmware ----
@app.post("/api/v1/firmware", response_model=Firmware, status_code=201, dependencies=[OPERATOR])
async def create_firmware(body: FirmwareCreate) -> Firmware:
    async with _pool(app).acquire() as conn:
        try:
            return await repo.create_firmware(conn, body)
        except asyncpg.UniqueViolationError:
            raise HTTPException(
                status_code=409, detail=f"{body.component.value} {body.version} 已存在"
            )


@app.get("/api/v1/firmware", response_model=list[Firmware], dependencies=[VIEWER])
async def list_firmware() -> list[Firmware]:
    async with _pool(app).acquire() as conn:
        return await repo.list_firmware(conn)


@app.put(
    "/api/v1/devices/{device_id}/firmware", response_model=DeviceFirmware, dependencies=[OPERATOR]
)
async def set_device_firmware(device_id: UUID, body: DeviceFirmwareSet) -> DeviceFirmware:
    async with _pool(app).acquire() as conn:
        d = await repo.get_device(conn, device_id)
        if d is None:
            raise HTTPException(status_code=404, detail="device 不存在")
        return await repo.set_device_firmware(conn, device_id, body.component.value, body.version)


@app.get(
    "/api/v1/devices/{device_id}/firmware",
    response_model=list[DeviceFirmware],
    dependencies=[VIEWER],
)
async def list_device_firmware(device_id: UUID) -> list[DeviceFirmware]:
    async with _pool(app).acquire() as conn:
        return await repo.list_device_firmware(conn, device_id)


# ---- status(裝置 + 最新遙測)----
@app.get("/api/v1/status", response_model=list[DeviceStatusView], dependencies=[VIEWER])
async def list_all_status() -> list[DeviceStatusView]:
    async with _pool(app).acquire() as conn:
        return await repo.list_all_status(conn)


@app.get(
    "/api/v1/devices/{device_id}/status", response_model=DeviceStatusView, dependencies=[VIEWER]
)
async def get_device_status(device_id: UUID) -> DeviceStatusView:
    async with _pool(app).acquire() as conn:
        s = await repo.get_device_status(conn, device_id)
    if s is None:
        raise HTTPException(status_code=404, detail="device 不存在")
    return s


@app.get(
    "/api/v1/fleets/{fleet_id}/status",
    response_model=list[DeviceStatusView],
    dependencies=[VIEWER],
)
async def list_fleet_status(fleet_id: UUID) -> list[DeviceStatusView]:
    async with _pool(app).acquire() as conn:
        return await repo.list_fleet_status(conn, fleet_id)


# ---- SSE 即時遙測串流 ----
async def _sse_events(request: Request, hub: TelemetryHub):
    """連上先送目前快照,之後串流更新;定期 keepalive 避免代理斷連。"""
    q = hub.subscribe()
    try:
        for data in hub.snapshot():
            yield f"data: {json.dumps(data)}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                data = await asyncio.wait_for(q.get(), timeout=SSE_KEEPALIVE_S)
                yield f"data: {json.dumps(data)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        hub.unsubscribe(q)


@app.get("/api/v1/stream")
async def stream(request: Request, token: str | None = Query(default=None)) -> StreamingResponse:
    # EventSource 無法帶 header,SSE 以查詢參數 token 認證(需 viewer)
    authorize_token(token, "viewer")
    return StreamingResponse(
        _sse_events(request, app.state.hub),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

"""mission-svc:航線/任務派遣(對 docs/20-software/cloud-fleet.md §6 派遣契約)。

把 tools/dispatch_mission.py 的派遣升為服務:航線庫 + 任務 CRUD + 派遣(MissionPlan
→ cmd/mission)+ 控制(MissionCommand → cmd/mission_ctrl)+ 進度回收(擁生命週期)。
沿用 cloud/fleet_svc 的 FastAPI + asyncpg + 輕量 migration 範式。
環境變數:PG_DSN / MQTT_HOST / MQTT_PORT。
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Query

from mission_svc import dispatch, metrics, repo
from mission_svc.auth import AUTH_ENABLED, require_role
from mission_svc.consumer import run_consumer
from mission_svc.migrate import apply_migrations
from mission_svc.models import (
    Mission,
    MissionCommandRequest,
    MissionCreate,
    Route,
    RouteCreate,
)

log = logging.getLogger("mission_svc")

PG_DSN = os.environ.get("PG_DSN", "postgresql://drone:dronedev@localhost:5432/drone")
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
PG_CONNECT_ATTEMPTS = 30
PG_CONNECT_RETRY_S = 2


async def _connect_pool() -> asyncpg.Pool:
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
    consumer = asyncio.create_task(run_consumer(pool, MQTT_HOST, MQTT_PORT))
    try:
        yield
    finally:
        consumer.cancel()
        try:
            await consumer
        except asyncio.CancelledError:
            pass
        await pool.close()


app = FastAPI(title="mission-svc", lifespan=lifespan)
metrics.instrument(app)  # /metrics(Prometheus)+ HTTP 指標 middleware(G13)

if not AUTH_ENABLED:
    log.warning("⚠ JWT 認證未啟用(dev 模式,全放行)——正式部署須設 JWT_SECRET 或 JWT_JWKS_URL")

# RBAC:讀取需 viewer,派遣/控制/建立需 operator(healthz 不設)
VIEWER = Depends(require_role("viewer"))
OPERATOR = Depends(require_role("operator"))


def _pool(app: FastAPI) -> asyncpg.Pool:
    return app.state.pool


@app.get("/healthz")
async def healthz() -> dict:
    async with _pool(app).acquire() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}


# ---- routes ----
@app.post("/api/v1/routes", response_model=Route, status_code=201, dependencies=[OPERATOR])
async def create_route(body: RouteCreate) -> Route:
    async with _pool(app).acquire() as conn:
        return await repo.create_route(conn, body)


@app.get("/api/v1/routes", response_model=list[Route], dependencies=[VIEWER])
async def list_routes() -> list[Route]:
    async with _pool(app).acquire() as conn:
        return await repo.list_routes(conn)


@app.get("/api/v1/routes/{route_id}", response_model=Route, dependencies=[VIEWER])
async def get_route(route_id: UUID) -> Route:
    async with _pool(app).acquire() as conn:
        r = await repo.get_route(conn, route_id)
    if r is None:
        raise HTTPException(status_code=404, detail="route 不存在")
    return r


# ---- missions ----
@app.post("/api/v1/missions", response_model=Mission, status_code=201, dependencies=[OPERATOR])
async def create_mission(body: MissionCreate) -> Mission:
    async with _pool(app).acquire() as conn:
        m = await repo.create_mission(conn, body)
    if m is None:
        raise HTTPException(status_code=404, detail="route 不存在")
    return m


@app.get("/api/v1/missions", response_model=list[Mission], dependencies=[VIEWER])
async def list_missions(drone_id: str | None = Query(default=None)) -> list[Mission]:
    async with _pool(app).acquire() as conn:
        return await repo.list_missions(conn, drone_id)


@app.get("/api/v1/missions/{mission_pk}", response_model=Mission, dependencies=[VIEWER])
async def get_mission(mission_pk: UUID) -> Mission:
    async with _pool(app).acquire() as conn:
        m = await repo.get_mission(conn, mission_pk)
    if m is None:
        raise HTTPException(status_code=404, detail="mission 不存在")
    return m


@app.post(
    "/api/v1/missions/{mission_pk}/dispatch", response_model=Mission, dependencies=[OPERATOR]
)
async def dispatch_mission(mission_pk: UUID) -> Mission:
    async with _pool(app).acquire() as conn:
        m = await repo.get_mission(conn, mission_pk)
        if m is None:
            raise HTTPException(status_code=404, detail="mission 不存在")
        if m.status != "created":
            raise HTTPException(status_code=409, detail=f"任務已派遣或進行中(status={m.status})")
        plan_json = dispatch.build_mission_plan_json(
            m.mission_id, [w.model_dump() for w in m.waypoints], m.rtl_after_last
        )
        await dispatch.publish_mission_plan(MQTT_HOST, MQTT_PORT, m.drone_id, plan_json)
        await repo.mark_dispatched(conn, mission_pk)
        return await repo.get_mission(conn, mission_pk)  # type: ignore[return-value]


@app.post(
    "/api/v1/missions/{mission_pk}/command", response_model=Mission, dependencies=[OPERATOR]
)
async def command_mission(mission_pk: UUID, body: MissionCommandRequest) -> Mission:
    async with _pool(app).acquire() as conn:
        m = await repo.get_mission(conn, mission_pk)
        if m is None:
            raise HTTPException(status_code=404, detail="mission 不存在")
        cmd_json = dispatch.build_mission_command_json(m.mission_id, body.command.value)
        await dispatch.publish_mission_command(MQTT_HOST, MQTT_PORT, m.drone_id, cmd_json)
        return m

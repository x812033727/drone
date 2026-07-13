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
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response

from mission_svc import audit, dispatch, metrics, repo
from mission_svc.auth import (
    AUTH_ENABLED,
    Principal,
    read_org,
    require_principal,
    require_role,
)
from mission_svc.consumer import run_consumer
from mission_svc.migrate import apply_migrations
from mission_svc.models import (
    AuditEntry,
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

# RBAC:讀取需 viewer,派遣/控制/建立需 operator(healthz 不設);審計稽核檢視需 admin。
# 依賴回 Principal(含租戶 org),端點據此做多租戶隔離(G11)並供審計取 actor
# (claims 在 principal.claims)。注入 Principal 不增加 OpenAPI 參數;同一 Depends 快取。
VIEWER = Depends(require_principal("viewer"))
OPERATOR = Depends(require_principal("operator"))
# 稽核端點 admin-only 且全域(不做 org 過濾),沿用回 claims 的 require_role 閘。
ADMIN = Depends(require_role("admin"))


def _pool(app: FastAPI) -> asyncpg.Pool:
    return app.state.pool


# 分頁(G12):list 端點加 limit/offset,預設上限 100;total/limit/offset 走回應標頭
# (X-Total-Count 等),回應本體仍是既有陣列——向後相容,不動 response_model。
PAGE_LIMIT_DEFAULT = 100
PAGE_LIMIT_MAX = 1000


def _set_page_headers(response: Response, total: int, limit: int, offset: int) -> None:
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)


@app.get("/healthz")
async def healthz() -> dict:
    async with _pool(app).acquire() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}


# ---- routes ----
@app.post("/api/v1/routes", response_model=Route, status_code=201)
async def create_route(
    body: RouteCreate, request: Request, principal: Principal = OPERATOR
) -> Route:
    # 租戶邊界:org 取自呼叫者 claim,不採信 client。
    async with _pool(app).acquire() as conn:
        route = await repo.create_route(conn, body, principal.org)
        await audit.record(
            conn, claims=principal.claims, action="create", resource_type="route",
            resource_id=route.id,
            details={"name": route.name, "waypoints": len(route.waypoints)}, request=request,
        )
    return route


@app.get("/api/v1/routes", response_model=list[Route])
async def list_routes(
    response: Response,
    org: str | None = Query(default=None, description="僅 admin:限定單一租戶(略則看全部)"),
    limit: int = Query(default=PAGE_LIMIT_DEFAULT, ge=1, le=PAGE_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
    principal: Principal = VIEWER,
) -> list[Route]:
    scope = read_org(principal, org)
    async with _pool(app).acquire() as conn:
        total = await repo.count_routes(conn, scope)
        items = await repo.list_routes(conn, org=scope, limit=limit, offset=offset)
    _set_page_headers(response, total, limit, offset)
    return items


@app.get("/api/v1/routes/{route_id}", response_model=Route)
async def get_route(route_id: UUID, principal: Principal = VIEWER) -> Route:
    async with _pool(app).acquire() as conn:
        r = await repo.get_route(conn, route_id, read_org(principal))
    if r is None:  # 跨 org 亦回 404
        raise HTTPException(status_code=404, detail="route 不存在")
    return r


# ---- missions ----
@app.post("/api/v1/missions", response_model=Mission, status_code=201)
async def create_mission(
    body: MissionCreate, request: Request, principal: Principal = OPERATOR
) -> Mission:
    # 租戶邊界:org 取自呼叫者 claim;route 亦以本 org 查找(他 org route → 404)。
    async with _pool(app).acquire() as conn:
        m = await repo.create_mission(conn, body, principal.org)
        if m is None:
            raise HTTPException(status_code=404, detail="route 不存在")
        await audit.record(
            conn, claims=principal.claims, action="create", resource_type="mission",
            resource_id=m.id,
            details={"mission_id": m.mission_id, "drone_id": m.drone_id,
                     "route_id": str(m.route_id) if m.route_id else None},
            request=request,
        )
    return m


@app.get("/api/v1/missions", response_model=list[Mission])
async def list_missions(
    response: Response,
    drone_id: str | None = Query(default=None),
    org: str | None = Query(default=None, description="僅 admin:限定單一租戶(略則看全部)"),
    limit: int = Query(default=PAGE_LIMIT_DEFAULT, ge=1, le=PAGE_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
    principal: Principal = VIEWER,
) -> list[Mission]:
    scope = read_org(principal, org)
    async with _pool(app).acquire() as conn:
        total = await repo.count_missions(conn, drone_id, scope)
        items = await repo.list_missions(conn, drone_id, org=scope, limit=limit, offset=offset)
    _set_page_headers(response, total, limit, offset)
    return items


@app.get("/api/v1/missions/{mission_pk}", response_model=Mission)
async def get_mission(mission_pk: UUID, principal: Principal = VIEWER) -> Mission:
    async with _pool(app).acquire() as conn:
        m = await repo.get_mission(conn, mission_pk, read_org(principal))
    if m is None:  # 跨 org 亦回 404
        raise HTTPException(status_code=404, detail="mission 不存在")
    return m


@app.post("/api/v1/missions/{mission_pk}/dispatch", response_model=Mission)
async def dispatch_mission(
    mission_pk: UUID, request: Request, principal: Principal = OPERATOR
) -> Mission:
    scope = read_org(principal)
    async with _pool(app).acquire() as conn:
        m = await repo.get_mission(conn, mission_pk, scope)
        if m is None:  # 跨 org 亦回 404(不得派遣他 org 任務)
            raise HTTPException(status_code=404, detail="mission 不存在")
        if m.status != "created":
            raise HTTPException(status_code=409, detail=f"任務已派遣或進行中(status={m.status})")
        plan_json = dispatch.build_mission_plan_json(
            m.mission_id, [w.model_dump() for w in m.waypoints], m.rtl_after_last
        )
        await dispatch.publish_mission_plan(MQTT_HOST, MQTT_PORT, m.drone_id, plan_json)
        await repo.mark_dispatched(conn, mission_pk)
        await audit.record(
            conn, claims=principal.claims, action="dispatch", resource_type="mission",
            resource_id=mission_pk,
            details={"mission_id": m.mission_id, "drone_id": m.drone_id}, request=request,
        )
        return await repo.get_mission(conn, mission_pk, scope)  # type: ignore[return-value]


@app.post("/api/v1/missions/{mission_pk}/command", response_model=Mission)
async def command_mission(
    mission_pk: UUID,
    body: MissionCommandRequest,
    request: Request,
    principal: Principal = OPERATOR,
) -> Mission:
    async with _pool(app).acquire() as conn:
        m = await repo.get_mission(conn, mission_pk, read_org(principal))
        if m is None:  # 跨 org 亦回 404(不得控制他 org 任務)
            raise HTTPException(status_code=404, detail="mission 不存在")
        cmd_json = dispatch.build_mission_command_json(m.mission_id, body.command.value)
        await dispatch.publish_mission_command(MQTT_HOST, MQTT_PORT, m.drone_id, cmd_json)
        await audit.record(
            conn, claims=principal.claims, action="command", resource_type="mission",
            resource_id=mission_pk,
            details={"mission_id": m.mission_id, "drone_id": m.drone_id,
                     "command": body.command.value},
            request=request,
        )
        return m


# ---- audit(G14 稽核查詢,admin only;分頁同 G12 慣例)----
@app.get("/api/v1/audit", response_model=list[AuditEntry], dependencies=[ADMIN])
async def list_audit(
    response: Response,
    resource_type: str | None = Query(default=None),
    limit: int = Query(default=PAGE_LIMIT_DEFAULT, ge=1, le=PAGE_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
) -> list[AuditEntry]:
    async with _pool(app).acquire() as conn:
        total = await repo.count_audit(conn, resource_type)
        items = await repo.list_audit(conn, resource_type, limit=limit, offset=offset)
    _set_page_headers(response, total, limit, offset)
    return items

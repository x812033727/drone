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

from fleet_svc import audit, limits, metrics, repo
from fleet_svc.auth import (
    AUTH_ENABLED,
    Principal,
    authorize_token,
    build_principal,
    read_org,
    require_principal,
    require_role,
)
from fleet_svc.consumer import run_consumer
from fleet_svc.hub import TelemetryHub
from fleet_svc.migrate import apply_migrations
from fleet_svc.models import (
    AuditEntry,
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
    Org,
    OrgCreate,
    OrgUpdate,
    UsageReport,
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

# RBAC 依賴:讀取需 viewer,變更需 operator(healthz 不設,供 compose healthcheck);
# 審計稽核檢視需 admin。依賴回 Principal(含租戶 org),端點據此做多租戶隔離(G11)並
# 供審計取 actor(claims 在 principal.claims)。注入 Principal 不增加 OpenAPI 參數。
# FastAPI 對同一 Depends 物件快取,故不會重複驗證。
VIEWER = Depends(require_principal("viewer"))
# 寫入端點(create/update/delete/set)用帶限流的 operator 依賴(G30):非 admin 每租戶
# 寫入速率受限,超限 429 + Retry-After;讀取(VIEWER)不限流。
OPERATOR = Depends(limits.require_principal_rl("operator"))
# 稽核端點 admin-only 且全域(不做 org 過濾),沿用回 claims 的 require_role 閘。
ADMIN = Depends(require_role("admin"))


def _pool(app: FastAPI) -> asyncpg.Pool:
    return app.state.pool


async def _guard_write(conn: asyncpg.Connection, principal: Principal) -> Org | None:
    """非 admin 寫入前置:取本租戶註冊列並擋 suspended(403);回 org 列供配額解析。

    admin(含 dev 模式)豁免——回 None,不查表、不受 suspended/配額約束。
    org 未在註冊表(None)亦放行:配額退回 env 全域預設(見 limits.effective_limit)。
    """
    if principal.is_admin:
        return None
    org_row = await repo.get_org(conn, principal.org)
    limits.enforce_org_active(principal, org_row)
    return org_row


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
@app.post("/api/v1/fleets", response_model=Fleet, status_code=201)
async def create_fleet(
    body: FleetCreate, request: Request, principal: Principal = OPERATOR
) -> Fleet:
    # 租戶邊界:org 取自呼叫者 claim(principal.org),不採信 client 傳入。
    async with _pool(app).acquire() as conn:
        # 租戶控制面:非 admin 先擋 suspended,並依 per-org 有效配額(覆寫→plan→env)判定。
        org_row = await _guard_write(conn, principal)
        if not principal.is_admin:
            existing = await repo.count_fleets(conn, principal.org)
            limits.enforce_quota(
                principal, existing, limits.effective_limit(org_row, "max_fleets"), "機隊"
            )
        fleet = await repo.create_fleet(conn, body, principal.org)
        await repo.increment_usage(conn, principal.org, "fleet_created", limits.current_period())
        await audit.record(
            conn, claims=principal.claims, action="create", resource_type="fleet",
            resource_id=fleet.id, details={"name": fleet.name, "org_id": fleet.org_id},
            request=request,
        )
    return fleet


@app.get("/api/v1/fleets", response_model=list[Fleet])
async def list_fleets(
    response: Response,
    org: str | None = Query(default=None, description="僅 admin:限定單一租戶(略則看全部)"),
    limit: int = Query(default=PAGE_LIMIT_DEFAULT, ge=1, le=PAGE_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
    principal: Principal = VIEWER,
) -> list[Fleet]:
    scope = read_org(principal, org)  # 非 admin 一律限本 org;admin 可跨/指定
    async with _pool(app).acquire() as conn:
        total = await repo.count_fleets(conn, scope)
        items = await repo.list_fleets(conn, org=scope, limit=limit, offset=offset)
    _set_page_headers(response, total, limit, offset)
    return items


@app.get("/api/v1/fleets/{fleet_id}", response_model=Fleet)
async def get_fleet(fleet_id: UUID, principal: Principal = VIEWER) -> Fleet:
    async with _pool(app).acquire() as conn:
        f = await repo.get_fleet(conn, fleet_id, read_org(principal))
    if f is None:  # 跨 org 亦回 404(不洩漏存在性)
        raise HTTPException(status_code=404, detail="fleet 不存在")
    return f


# ---- devices ----
@app.post("/api/v1/devices", response_model=Device, status_code=201)
async def create_device(
    body: DeviceCreate, request: Request, principal: Principal = OPERATOR
) -> Device:
    # 租戶邊界:org 取自呼叫者 claim,不採信 client。
    async with _pool(app).acquire() as conn:
        # 租戶控制面:非 admin 先擋 suspended,並依 per-org 有效配額(覆寫→plan→env)判定。
        org_row = await _guard_write(conn, principal)
        if not principal.is_admin:
            existing = await repo.count_devices(conn, None, principal.org)
            limits.enforce_quota(
                principal, existing, limits.effective_limit(org_row, "max_devices"), "裝置"
            )
        try:
            device = await repo.create_device(conn, body, principal.org)
        except asyncpg.UniqueViolationError:
            raise HTTPException(status_code=409, detail=f"serial 已存在:{body.serial}")
        await repo.increment_usage(conn, principal.org, "device_created", limits.current_period())
        await audit.record(
            conn, claims=principal.claims, action="create", resource_type="device",
            resource_id=device.id,
            details={"serial": device.serial, "name": device.name, "model": device.model},
            request=request,
        )
    return device


@app.get("/api/v1/devices", response_model=list[Device])
async def list_devices(
    response: Response,
    fleet_id: UUID | None = Query(default=None),
    org: str | None = Query(default=None, description="僅 admin:限定單一租戶(略則看全部)"),
    limit: int = Query(default=PAGE_LIMIT_DEFAULT, ge=1, le=PAGE_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
    principal: Principal = VIEWER,
) -> list[Device]:
    scope = read_org(principal, org)
    async with _pool(app).acquire() as conn:
        total = await repo.count_devices(conn, fleet_id, scope)
        items = await repo.list_devices(conn, fleet_id, org=scope, limit=limit, offset=offset)
    _set_page_headers(response, total, limit, offset)
    return items


@app.get("/api/v1/devices/{device_id}", response_model=Device)
async def get_device(device_id: UUID, principal: Principal = VIEWER) -> Device:
    async with _pool(app).acquire() as conn:
        d = await repo.get_device(conn, device_id, read_org(principal))
    if d is None:  # 跨 org 亦回 404
        raise HTTPException(status_code=404, detail="device 不存在")
    return d


@app.patch("/api/v1/devices/{device_id}", response_model=Device)
async def update_device(
    device_id: UUID, body: DeviceUpdate, request: Request, principal: Principal = OPERATOR
) -> Device:
    async with _pool(app).acquire() as conn:
        await _guard_write(conn, principal)  # 擋 suspended 租戶寫入(admin 豁免)
        d = await repo.update_device(conn, device_id, body, read_org(principal))
        if d is None:  # 跨 org 亦回 404(不得改他 org 資源)
            raise HTTPException(status_code=404, detail="device 不存在")
        await audit.record(
            conn, claims=principal.claims, action="update", resource_type="device",
            resource_id=device_id,
            details=body.model_dump(exclude_unset=True, mode="json"), request=request,
        )
    return d


@app.delete("/api/v1/devices/{device_id}", status_code=204)
async def delete_device(
    device_id: UUID, request: Request, principal: Principal = OPERATOR
) -> None:
    async with _pool(app).acquire() as conn:
        await _guard_write(conn, principal)  # 擋 suspended 租戶寫入(admin 豁免)
        ok = await repo.delete_device(conn, device_id, read_org(principal))
        if not ok:  # 跨 org 亦回 404
            raise HTTPException(status_code=404, detail="device 不存在")
        await audit.record(
            conn, claims=principal.claims, action="delete", resource_type="device",
            resource_id=device_id, request=request,
        )


# ---- firmware ----
@app.post("/api/v1/firmware", response_model=Firmware, status_code=201)
async def create_firmware(
    body: FirmwareCreate, request: Request, principal: Principal = OPERATOR
) -> Firmware:
    # 韌體版本為平台共用目錄(非租戶資料),不做 org 綁定;僅 operator 可維護。
    async with _pool(app).acquire() as conn:
        try:
            fw = await repo.create_firmware(conn, body)
        except asyncpg.UniqueViolationError:
            raise HTTPException(
                status_code=409, detail=f"{body.component.value} {body.version} 已存在"
            )
        await audit.record(
            conn, claims=principal.claims, action="create", resource_type="firmware",
            resource_id=fw.id,
            details={"component": fw.component.value, "version": fw.version}, request=request,
        )
    return fw


@app.get("/api/v1/firmware", response_model=list[Firmware], dependencies=[VIEWER])
async def list_firmware() -> list[Firmware]:
    # 平台共用韌體目錄,不含租戶資料,全體 viewer 可見(見上註)。
    async with _pool(app).acquire() as conn:
        return await repo.list_firmware(conn)


@app.put("/api/v1/devices/{device_id}/firmware", response_model=DeviceFirmware)
async def set_device_firmware(
    device_id: UUID, body: DeviceFirmwareSet, request: Request, principal: Principal = OPERATOR
) -> DeviceFirmware:
    async with _pool(app).acquire() as conn:
        await _guard_write(conn, principal)  # 擋 suspended 租戶寫入(admin 豁免)
        d = await repo.get_device(conn, device_id, read_org(principal))
        if d is None:  # 跨 org 亦回 404(不得改他 org 裝置韌體)
            raise HTTPException(status_code=404, detail="device 不存在")
        df = await repo.set_device_firmware(conn, device_id, body.component.value, body.version)
        await audit.record(
            conn, claims=principal.claims, action="set_firmware", resource_type="device",
            resource_id=device_id,
            details={"component": body.component.value, "version": body.version}, request=request,
        )
    return df


@app.get("/api/v1/devices/{device_id}/firmware", response_model=list[DeviceFirmware])
async def list_device_firmware(
    device_id: UUID, principal: Principal = VIEWER
) -> list[DeviceFirmware]:
    async with _pool(app).acquire() as conn:
        d = await repo.get_device(conn, device_id, read_org(principal))
        if d is None:  # 先確認裝置屬本 org,否則不洩其韌體清單
            raise HTTPException(status_code=404, detail="device 不存在")
        return await repo.list_device_firmware(conn, device_id)


# ---- status(裝置 + 最新遙測)----
@app.get("/api/v1/status", response_model=list[DeviceStatusView])
async def list_all_status(principal: Principal = VIEWER) -> list[DeviceStatusView]:
    async with _pool(app).acquire() as conn:
        return await repo.list_all_status(conn, read_org(principal))


@app.get("/api/v1/devices/{device_id}/status", response_model=DeviceStatusView)
async def get_device_status(
    device_id: UUID, principal: Principal = VIEWER
) -> DeviceStatusView:
    async with _pool(app).acquire() as conn:
        s = await repo.get_device_status(conn, device_id, read_org(principal))
    if s is None:  # 跨 org 亦回 404
        raise HTTPException(status_code=404, detail="device 不存在")
    return s


@app.get("/api/v1/fleets/{fleet_id}/status", response_model=list[DeviceStatusView])
async def list_fleet_status(
    fleet_id: UUID, principal: Principal = VIEWER
) -> list[DeviceStatusView]:
    async with _pool(app).acquire() as conn:
        return await repo.list_fleet_status(conn, fleet_id, read_org(principal))


# ---- usage(G30 用量報表)----
@app.get("/api/v1/usage", response_model=UsageReport)
async def get_usage(
    org: str | None = Query(default=None, description="僅 admin:查指定租戶(略則查本 org)"),
    principal: Principal = VIEWER,
) -> UsageReport:
    # 非 admin 一律查本 org(忽略 ?org=,防越權窺他 org 用量);admin 可指定,略則查自身。
    scope_org = org if (principal.is_admin and org) else principal.org
    period = limits.current_period()
    async with _pool(app).acquire() as conn:
        counters = await repo.get_usage(conn, scope_org, period)
        totals = await repo.get_usage_totals(conn, scope_org)
        devices = await repo.count_devices(conn, None, scope_org)
        fleets = await repo.count_fleets(conn, scope_org)
        org_row = await repo.get_org(conn, scope_org)  # per-org 有效配額(退回 env 全域預設)
    return UsageReport(
        org_id=scope_org,
        period=period,
        counters=counters,
        totals=totals,
        resources={"devices": devices, "fleets": fleets},
        limits={
            "max_devices": limits.effective_limit(org_row, "max_devices"),
            "max_fleets": limits.effective_limit(org_row, "max_fleets"),
        },
    )


# ---- orgs(租戶/計費控制面,admin only)----
# 平台管理者管理租戶註冊表:建立/列出/更新租戶與其 plan/status/配額覆寫,並查每租戶用量
# 彙總。RBAC 沿用 ADMIN(require_role("admin"))閘——非 admin 一律 403;dev 模式=admin 放行。
# 配額覆寫欄(max_devices/max_fleets)由 create_fleet/create_device 的 effective_limit 生效。
@app.post("/api/v1/orgs", response_model=Org, status_code=201)
async def create_org(body: OrgCreate, request: Request, claims: dict = ADMIN) -> Org:
    async with _pool(app).acquire() as conn:
        try:
            org = await repo.create_org(conn, body)
        except asyncpg.UniqueViolationError:
            raise HTTPException(status_code=409, detail=f"org 已存在:{body.org_id}")
        await audit.record(
            conn, claims=claims, action="create", resource_type="org",
            resource_id=org.org_id,
            details={"name": org.name, "plan": org.plan.value, "status": org.status.value},
            request=request,
        )
    return org


@app.get("/api/v1/orgs", response_model=list[Org])
async def list_orgs(
    response: Response,
    status: str | None = Query(default=None, description="依狀態過濾:active / suspended"),
    limit: int = Query(default=PAGE_LIMIT_DEFAULT, ge=1, le=PAGE_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
    claims: dict = ADMIN,
) -> list[Org]:
    async with _pool(app).acquire() as conn:
        total = await repo.count_orgs(conn, status)
        items = await repo.list_orgs(conn, status=status, limit=limit, offset=offset)
    _set_page_headers(response, total, limit, offset)
    return items


@app.get("/api/v1/orgs/{org_id}", response_model=Org)
async def get_org(org_id: str, claims: dict = ADMIN) -> Org:
    async with _pool(app).acquire() as conn:
        org = await repo.get_org(conn, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="org 不存在")
    return org


@app.patch("/api/v1/orgs/{org_id}", response_model=Org)
async def update_org(
    org_id: str, body: OrgUpdate, request: Request, claims: dict = ADMIN
) -> Org:
    async with _pool(app).acquire() as conn:
        org = await repo.update_org(conn, org_id, body)
        if org is None:
            raise HTTPException(status_code=404, detail="org 不存在")
        await audit.record(
            conn, claims=claims, action="update", resource_type="org",
            resource_id=org_id,
            details=body.model_dump(exclude_unset=True, mode="json"), request=request,
        )
    return org


@app.get("/api/v1/orgs/{org_id}/usage", response_model=UsageReport)
async def get_org_usage(org_id: str, claims: dict = ADMIN) -> UsageReport:
    # 某租戶用量彙總(復用 usage_counter);limits 為該租戶「有效」配額(覆寫→plan→env)。
    period = limits.current_period()
    async with _pool(app).acquire() as conn:
        org_row = await repo.get_org(conn, org_id)
        if org_row is None:
            raise HTTPException(status_code=404, detail="org 不存在")
        counters = await repo.get_usage(conn, org_id, period)
        totals = await repo.get_usage_totals(conn, org_id)
        devices = await repo.count_devices(conn, None, org_id)
        fleets = await repo.count_fleets(conn, org_id)
    return UsageReport(
        org_id=org_id,
        period=period,
        counters=counters,
        totals=totals,
        resources={"devices": devices, "fleets": fleets},
        limits={
            "max_devices": limits.effective_limit(org_row, "max_devices"),
            "max_fleets": limits.effective_limit(org_row, "max_fleets"),
        },
    )


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


# ---- SSE 即時遙測串流 ----
async def _org_serials(org: str) -> set[str]:
    """查某租戶的裝置 serial 集合(SSE 過濾用)。"""
    async with _pool(app).acquire() as conn:
        return await repo.list_org_serials(conn, org)


async def _sse_events(request: Request, hub: TelemetryHub, principal: Principal):
    """連上先送快照,之後串流更新;定期 keepalive。

    多租戶隔離(G11b):遙測 hub 以 drone_id(=device serial)為鍵廣播全機隊,
    非 admin 訂閱者**只放行本 org 裝置**的即時遙測(admin 看全部)。長連線期間
    定期刷新 org 的 serial 集合以納入新註冊裝置;未知 drone_id 對非 admin 一律不送
    (安全預設:寧可漏看,不可跨租戶洩漏即時位置)。
    """
    allowed: set[str] | None = None if principal.is_admin else await _org_serials(principal.org)

    def visible(data: dict) -> bool:
        if allowed is None:
            return True
        return data.get("drone_id") in allowed

    q = hub.subscribe()
    try:
        for data in hub.snapshot():
            if visible(data):
                yield f"data: {json.dumps(data)}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                data = await asyncio.wait_for(q.get(), timeout=SSE_KEEPALIVE_S)
                if visible(data):
                    yield f"data: {json.dumps(data)}\n\n"
            except asyncio.TimeoutError:
                # keepalive 之際順便刷新本 org 的 serial 集合(納入新裝置)
                if allowed is not None:
                    allowed = await _org_serials(principal.org)
                yield ": keepalive\n\n"
    finally:
        hub.unsubscribe(q)


@app.get("/api/v1/stream")
async def stream(request: Request, token: str | None = Query(default=None)) -> StreamingResponse:
    # EventSource 無法帶 header,SSE 以查詢參數 token 認證(需 viewer);
    # 依 principal.org 做多租戶隔離(G11b),admin 跨 org 看全部。
    principal = build_principal(authorize_token(token, "viewer"))
    return StreamingResponse(
        _sse_events(request, app.state.hub, principal),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

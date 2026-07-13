"""用量計量 + 配額 + 限流(G30 計費基礎設施)。fleet-svc / mission-svc 共用同一設計。

三件事,皆零外部依賴、可設定、admin(平台)豁免:

1. 計量(metering):計費相關操作(建裝置/機隊)按 (org, metric, UTC 日) 累計到
   `usage_counter` 表(SQL 在 repo.py)。供每日量配額與 GET /api/v1/usage 報表。
2. 配額(quota):可設定的每租戶上限。資源型上限(max_devices/max_fleets)以「現存
   數量」判定,超限回 **402 Payment Required**(語義=已達方案額度,需升級/付費);
   與限流的 429 明確區分。上限來自環境變數,預設寬鬆(dev / cloud-smoke 不觸發)。
3. 限流(rate limit):對「寫入端點」做每租戶速率限制,**DB-backed 固定視窗計數**
   (fixed window,精確且免外部依賴)。超限回 **429 + Retry-After**。計數落
   `rate_limit_counter` 表(SQL 在 repo.py),每次寫入以 `INSERT ... ON CONFLICT
   (org_id, window_start) DO UPDATE count = count + 1 RETURNING count` 原子遞增;
   count 超過上限即拒。視窗長度 = 60 秒(對齊 RATE_LIMIT_PER_MIN)。因計數在**單一
   共用 DB**,多副本(replicas>1)部署下**有效限流精確**——不再是舊記憶體 token
   bucket 的 per-process 近似(N 副本 ≈ N×設定值),故免引入 Redis。

admin 豁免:平台管理者(is_admin)不受配額/限流約束;dev 模式(認證停用)claims 即
admin,故 cloud-smoke 全放行、既有煙霧不受影響。

金流串接:方案「訂閱付費啟用」已由 fleet_svc.billing(綠界 ECPay)實作——checkout 產綠界
表單、callback 驗 CheckMacValue 後 upsert org 為該 plan+active。本模組仍只做計量/配額/限流;
usage_counter 亦可作為未來 usage-based billing(超額計費)的 metering 底座。
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request

from fleet_svc import repo
from fleet_svc.auth import Principal, require_principal

if TYPE_CHECKING:
    import asyncpg

    from fleet_svc.models import Org

# ---- 配額設定(環境變數;預設寬鬆,dev/cloud-smoke 不觸發;正式部署以 Helm 值調整)----


def _int_env(name: str, default: int) -> int:
    """讀取整數環境變數;空字串 / 非法值回退預設(compose ${VAR:-} 語義)。"""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


QUOTA_MAX_DEVICES = _int_env("QUOTA_MAX_DEVICES", 10_000)  # env 全域預設:每租戶現存裝置上限
QUOTA_MAX_FLEETS = _int_env("QUOTA_MAX_FLEETS", 1_000)  # env 全域預設:每租戶現存機隊上限

# 方案(plan)→ 預設配額。租戶在註冊表(fleet.org)未設「覆寫」欄時,配額取此表對應方案值。
# free 小(試用)/ pro 中 / enterprise 大。數值為合理起步,正式營運可調。
PLAN_QUOTAS: dict[str, dict[str, int]] = {
    "free": {"max_devices": 10, "max_fleets": 2},
    "pro": {"max_devices": 500, "max_fleets": 50},
    "enterprise": {"max_devices": 100_000, "max_fleets": 5_000},
}

# 每租戶寫入速率(每分鐘)。預設寬鬆(100/秒)確保煙霧/測試不誤傷,正式部署以環境
# 變數調降到有意義值。限流以此值為單一視窗(60 秒)上限。
RATE_LIMIT_PER_MIN = _int_env("RATE_LIMIT_PER_MIN", 6_000)

# 限流固定視窗長度(秒)。對齊 RATE_LIMIT_PER_MIN(每分鐘上限)。
RATE_LIMIT_WINDOW_SEC = 60


def current_period() -> date:
    """計量/每日配額的期間鍵:UTC 日(跨時區一致)。"""
    return datetime.now(timezone.utc).date()


# ---- 限流:DB-backed 固定視窗計數(per-org,單一 DB 下多副本精確)----


def _window_start(now: float) -> int:
    """視窗起點:UTC epoch 秒對齊到 RATE_LIMIT_WINDOW_SEC 邊界(固定視窗鍵)。"""
    return int(now // RATE_LIMIT_WINDOW_SEC) * RATE_LIMIT_WINDOW_SEC


async def enforce_rate_limit(
    conn: asyncpg.Connection,
    principal: Principal,
    *,
    limit: int | None = None,
    now: float | None = None,
) -> None:
    """對非 admin 主體套用 DB-backed 固定視窗寫入速率限制;超限抛 429 + Retry-After。

    以 (org, window_start) 原子遞增(INSERT ... ON CONFLICT DO UPDATE ... RETURNING
    count)取回本視窗遞增後計數;超過上限即拒(被拒請求亦計入,語義為固定視窗)。
    Retry-After = 到下一視窗起點的秒數。計數落單一共用 DB,故多副本部署精確。
    """
    if principal.is_admin:
        return
    cap = RATE_LIMIT_PER_MIN if limit is None else limit
    clock = time.time() if now is None else now
    window_start = _window_start(clock)
    count = await repo.incr_rate_limit(conn, principal.org, window_start)
    if count > cap:
        retry = window_start + RATE_LIMIT_WINDOW_SEC - int(clock)
        raise HTTPException(
            status_code=429,
            detail="寫入速率超限,請稍後再試",
            headers={"Retry-After": str(max(1, retry))},
        )


def require_principal_rl(min_role: str):
    """FastAPI 依賴工廠:先做角色驗證(回 Principal),再對非 admin 套 DB-backed 限流。

    供「寫入端點」取代 require_principal:讀取端點維持純 require_principal(不限流)。
    限流檢查需 DB,故此處自 pool 取一條連線(既有 acquire 模式,非每請求新連線)做
    原子遞增;admin(含 dev 模式)提前放行,不觸 DB。
    """
    base = require_principal(min_role)

    async def dependency(request: Request, principal: Principal = Depends(base)) -> Principal:
        if principal.is_admin:
            return principal
        async with request.app.state.pool.acquire() as conn:
            await enforce_rate_limit(conn, principal)
        return principal

    return dependency


# ---- 配額強制 ----


def enforce_quota(principal: Principal, current: int, maximum: int, resource: str) -> None:
    """資源型配額:現存數量達上限則抛 402(admin 豁免)。"""
    if principal.is_admin:
        return
    if current >= maximum:
        raise HTTPException(
            status_code=402,
            detail=f"已達 {resource} 配額上限({maximum});請提升方案或聯絡管理者",
        )


# ---- per-org 配額解析(#113 租戶註冊表 × #115 配額)----


def _env_quota(key: str) -> int:
    """env 全域預設(org 不在註冊表時的最終退路)。動態讀模組全域,支援測試 monkeypatch。"""
    return QUOTA_MAX_DEVICES if key == "max_devices" else QUOTA_MAX_FLEETS


def effective_limit(org: Org | None, key: str) -> int:
    """解析某租戶某資源的有效配額上限(key = max_devices / max_fleets)。

    優先序(#115 配額檢查據此,per-org 覆寫 env 全域):
      1. org 覆寫欄(fleet.org.max_devices/max_fleets)非 NULL → 硬覆寫。
      2. org.plan 的 PLAN_QUOTAS 預設。
      3. org 不在註冊表(None)或方案未知 → env 全域預設(QUOTA_MAX_*)。
    """
    if org is None:
        return _env_quota(key)
    override = getattr(org, key, None)
    if override is not None:
        return int(override)
    plan_key = org.plan.value if hasattr(org.plan, "value") else str(org.plan)
    plan_defaults = PLAN_QUOTAS.get(plan_key)
    if plan_defaults is None:
        return _env_quota(key)
    return plan_defaults[key]


def enforce_org_active(principal: Principal, org: Org | None) -> None:
    """suspended 租戶的寫入被擋(403);admin 平台管理者豁免。org 未註冊(None)不阻擋。"""
    if principal.is_admin or org is None:
        return
    status = org.status.value if hasattr(org.status, "value") else str(org.status)
    if status == "suspended":
        raise HTTPException(
            status_code=403,
            detail="租戶已停用(suspended),寫入被拒;請聯絡平台管理者",
        )


# 對外揭露的配額上限(GET /api/v1/usage 的 limits 區塊)。
QUOTA_LIMITS: dict[str, int] = {
    "max_devices": QUOTA_MAX_DEVICES,
    "max_fleets": QUOTA_MAX_FLEETS,
}

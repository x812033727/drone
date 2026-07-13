"""用量計量 + 配額 + 限流(G30 計費基礎設施)。fleet-svc / mission-svc 共用同一設計。

三件事,皆零外部依賴、可設定、admin(平台)豁免:

1. 計量(metering):計費相關操作(建裝置/機隊)按 (org, metric, UTC 日) 累計到
   `usage_counter` 表(SQL 在 repo.py)。供每日量配額與 GET /api/v1/usage 報表。
2. 配額(quota):可設定的每租戶上限。資源型上限(max_devices/max_fleets)以「現存
   數量」判定,超限回 **402 Payment Required**(語義=已達方案額度,需升級/付費);
   與限流的 429 明確區分。上限來自環境變數,預設寬鬆(dev / cloud-smoke 不觸發)。
3. 限流(rate limit):對「寫入端點」做每租戶速率限制,**記憶體 token bucket**(零依
   賴)。超限回 **429 + Retry-After**。預設寬鬆;單行程單事件迴圈,check 內無 await,
   故免鎖。多副本部署為 per-process 近似(分散式精確限流需 Redis,列 TODO)。

admin 豁免:平台管理者(is_admin)不受配額/限流約束;dev 模式(認證停用)claims 即
admin,故 cloud-smoke 全放行、既有煙霧不受影響。

TODO(付費串接):本模組只做計量/配額/限流基礎設施,**不做金流**。真實付款(方案
訂閱、超額計費、發票)需 payment provider(綠界 / Stripe 等)決策後另案串接:
usage_counter 已可作為計費來源資料(usage-based billing 的 metering 底座)。
"""

from __future__ import annotations

import math
import os
from datetime import date, datetime, timezone

from fastapi import Depends, HTTPException, Request

from fleet_svc.auth import Principal, require_principal

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


QUOTA_MAX_DEVICES = _int_env("QUOTA_MAX_DEVICES", 10_000)  # 每租戶現存裝置上限
QUOTA_MAX_FLEETS = _int_env("QUOTA_MAX_FLEETS", 1_000)  # 每租戶現存機隊上限
# 每租戶寫入速率(每分鐘);容量(burst)= 同值。預設寬鬆(100/秒)確保煙霧/測試不誤傷,
# 正式部署以環境變數調降到有意義值。
RATE_LIMIT_PER_MIN = _int_env("RATE_LIMIT_PER_MIN", 6_000)


def current_period() -> date:
    """計量/每日配額的期間鍵:UTC 日(跨時區一致)。"""
    return datetime.now(timezone.utc).date()


# ---- 限流:記憶體 token bucket(per-org 鍵)----


class _Bucket:
    __slots__ = ("tokens", "updated")

    def __init__(self, tokens: float, updated: float) -> None:
        self.tokens = tokens
        self.updated = updated


class RateLimiter:
    """每 key(此處=org)一個 token bucket。容量=burst,穩態速率=rate_per_min。

    check() 回傳 0.0 表示放行(已扣一枚 token),>0 表示超限並回傳建議 Retry-After 秒數。
    以 monotonic 時鐘防系統時間回撥;單事件迴圈內 check 無 await,故不需鎖。
    """

    def __init__(self, rate_per_min: float, burst: float | None = None) -> None:
        self.rate_per_sec = rate_per_min / 60.0
        self.capacity = float(burst if burst is not None else rate_per_min)
        self._buckets: dict[str, _Bucket] = {}

    def check(self, key: str, now: float | None = None) -> float:
        clock = now if now is not None else _now()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=self.capacity, updated=clock)
            self._buckets[key] = bucket
        # 依經過時間補充 token(上限=容量)
        elapsed = max(0.0, clock - bucket.updated)
        bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.rate_per_sec)
        bucket.updated = clock
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return 0.0
        if self.rate_per_sec <= 0.0:
            return 60.0  # 速率為 0(全關)時給一個固定退避
        return (1.0 - bucket.tokens) / self.rate_per_sec

    def reset(self) -> None:
        """清空所有 bucket(測試 / 手動重置用)。"""
        self._buckets.clear()


def _now() -> float:
    import time

    return time.monotonic()


# 模組級單例:寫入端點共用。測試可 monkeypatch 或 reset()。
write_limiter = RateLimiter(RATE_LIMIT_PER_MIN)


def enforce_rate_limit(principal: Principal) -> None:
    """對非 admin 主體套用寫入速率限制;超限抛 429 + Retry-After。"""
    if principal.is_admin:
        return
    retry = write_limiter.check(principal.org)
    if retry > 0.0:
        raise HTTPException(
            status_code=429,
            detail="寫入速率超限,請稍後再試",
            headers={"Retry-After": str(max(1, math.ceil(retry)))},
        )


def require_principal_rl(min_role: str):
    """FastAPI 依賴工廠:先做角色驗證(回 Principal),再對非 admin 套寫入限流。

    供「寫入端點」取代 require_principal:讀取端點維持純 require_principal(不限流)。
    """
    base = require_principal(min_role)

    async def dependency(request: Request, principal: Principal = Depends(base)) -> Principal:
        enforce_rate_limit(principal)
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


# 對外揭露的配額上限(GET /api/v1/usage 的 limits 區塊)。
QUOTA_LIMITS: dict[str, int] = {
    "max_devices": QUOTA_MAX_DEVICES,
    "max_fleets": QUOTA_MAX_FLEETS,
}

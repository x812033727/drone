"""用量計量 + 配額 + 限流(G30)。四層驗證,皆不碰真 DB:

1. DB-backed 固定視窗限流單元:同 org 超上限→429、視窗滾動後重置、不同 org 獨立、
   admin 不觸 DB、Retry-After = 到下一視窗秒數。以假連線模擬 (org, window) 原子遞增。
2. repo SQL 契約:usage increment/get/totals 與 rate_limit 遞增綁正確參數與 upsert 語法。
3. 配額(402):超現存上限回 402;admin 豁免;dev 模式不阻塞。
4. 限流(429):超速回 429 + Retry-After;admin 豁免;org 隔離;讀取不限流;視窗滾動重置。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from uuid import uuid4

import jwt
import pytest
from drone_common.auth import Principal
from fastapi import HTTPException
from fastapi.testclient import TestClient
from fleet_svc import auth, limits, main, repo

# ----------------------------------------------------------------------------
# 1. DB-backed 固定視窗限流單元(假連線模擬 (org, window_start) 原子遞增)
# ----------------------------------------------------------------------------


class _RLConn:
    """假連線:模擬 rate_limit_counter 的 INSERT ... ON CONFLICT ... RETURNING count。

    以 (org, window_start) 為鍵累計,回傳遞增後計數——與真 PG upsert 語義一致。
    """

    def __init__(self) -> None:
        self.counts: dict[tuple[str, int], int] = {}

    async def fetchval(self, sql, *args):
        assert "rate_limit_counter" in sql and "RETURNING count" in sql
        key = (args[0], args[1])  # (org, window_start)
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


def _principal(org: str, *, is_admin: bool = False) -> Principal:
    return Principal(claims={"org": org}, role="operator", org=org, is_admin=is_admin)


def _run_rl(conn, org, *, is_admin=False, limit=2, now=1000.0):
    return asyncio.run(
        limits.enforce_rate_limit(
            conn, _principal(org, is_admin=is_admin), limit=limit, now=now
        )
    )


def test_rate_limit_allows_up_to_limit_then_429():
    conn = _RLConn()
    # 上限 2:同視窗前 2 次放行(count 1、2),第 3 次(count 3)超限 → 429
    _run_rl(conn, "orgA", limit=2, now=1000.0)
    _run_rl(conn, "orgA", limit=2, now=1000.0)
    with pytest.raises(HTTPException) as ei:
        _run_rl(conn, "orgA", limit=2, now=1000.0)
    assert ei.value.status_code == 429
    assert "Retry-After" in ei.value.headers


def test_rate_limit_retry_after_points_to_next_window():
    conn = _RLConn()
    # now=1030(視窗 [1020,1080)),超限時 Retry-After = 1080 - 1030 = 50
    _run_rl(conn, "o", limit=1, now=1030.0)
    with pytest.raises(HTTPException) as ei:
        _run_rl(conn, "o", limit=1, now=1030.0)
    assert ei.value.headers["Retry-After"] == "50"


def test_rate_limit_window_rollover_resets():
    conn = _RLConn()
    _run_rl(conn, "o", limit=1, now=1000.0)  # 視窗 [960,1020) count=1 放行
    with pytest.raises(HTTPException):
        _run_rl(conn, "o", limit=1, now=1010.0)  # 同視窗 count=2 超限
    # 下一視窗(now=1080 → [1080,1140))計數重置,放行
    _run_rl(conn, "o", limit=1, now=1080.0)


def test_rate_limit_keys_are_independent():
    conn = _RLConn()
    _run_rl(conn, "a", limit=1, now=1000.0)  # a 用滿
    _run_rl(conn, "b", limit=1, now=1000.0)  # b 各自獨立,放行


def test_rate_limit_admin_exempt_does_not_touch_db():
    conn = _RLConn()
    for _ in range(5):
        _run_rl(conn, "plat", is_admin=True, limit=1, now=1000.0)
    assert conn.counts == {}  # admin 提前放行,未觸 DB


# ----------------------------------------------------------------------------
# 2. repo 計量 SQL 契約(stub 連線記錄 SQL/參數)
# ----------------------------------------------------------------------------


class _RecConn:
    def __init__(self, fetch_rows: list | None = None, fetchval: int = 0) -> None:
        self.execute_calls: list[tuple] = []
        self.fetch_calls: list[tuple] = []
        self.fetchval_calls: list[tuple] = []
        self._fetch_rows = fetch_rows or []
        self._fetchval = fetchval

    async def execute(self, sql, *args):
        self.execute_calls.append((sql, args))
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        return self._fetch_rows

    async def fetchval(self, sql, *args):
        self.fetchval_calls.append((sql, args))
        return self._fetchval


def test_increment_usage_atomic_upsert():
    conn = _RecConn()
    p = date(2026, 7, 13)
    asyncio.run(repo.increment_usage(conn, "acme", "device_created", p))
    sql, args = conn.execute_calls[0]
    assert "INSERT INTO fleet.usage_counter" in sql
    assert "ON CONFLICT (org_id, metric, period)" in sql
    assert "count = fleet.usage_counter.count + 1" in sql
    assert args == ("acme", "device_created", p)


def test_get_usage_scoped_by_org_and_period():
    conn = _RecConn(fetch_rows=[{"metric": "device_created", "count": 5}])
    p = date(2026, 7, 13)
    out = asyncio.run(repo.get_usage(conn, "acme", p))
    sql, args = conn.fetch_calls[0]
    assert "WHERE org_id = $1 AND period = $2" in sql and args == ("acme", p)
    assert out == {"device_created": 5}


def test_get_usage_totals_grouped():
    conn = _RecConn(fetch_rows=[{"metric": "fleet_created", "total": 9}])
    out = asyncio.run(repo.get_usage_totals(conn, "acme"))
    sql, args = conn.fetch_calls[0]
    assert "GROUP BY metric" in sql and args == ("acme",)
    assert out == {"fleet_created": 9}


def test_incr_rate_limit_atomic_upsert_returns_count():
    conn = _RecConn(fetchval=3)  # DB 回遞增後計數
    out = asyncio.run(repo.incr_rate_limit(conn, "acme", 1_000_020))
    sql, args = conn.fetchval_calls[0]
    assert "INSERT INTO fleet.rate_limit_counter" in sql
    assert "ON CONFLICT (org_id, window_start)" in sql
    assert "count = fleet.rate_limit_counter.count + 1" in sql
    assert "RETURNING count" in sql
    assert args == ("acme", 1_000_020)
    assert out == 3


# ----------------------------------------------------------------------------
# 3 & 4. 端點層:記憶體連線 + TestClient
# ----------------------------------------------------------------------------

SECRET = "test-secret-key-limits-g30-0123456789abcd"


class _MemConn:
    """支援 fleet / device 計數 + usage_counter 的記憶體連線。"""

    def __init__(self) -> None:
        self.fleets: list[dict] = []
        self.devices: list[dict] = []
        self.usage: dict[tuple, int] = {}  # (org, metric, period) -> count
        self.rl: dict[tuple, int] = {}  # (org, window_start) -> count(限流固定視窗)

    async def fetchval(self, sql, *args):
        if "rate_limit_counter" in sql:  # DB-backed 限流原子遞增回傳新計數
            key = (args[0], args[1])  # (org, window_start)
            self.rl[key] = self.rl.get(key, 0) + 1
            return self.rl[key]
        if "count(*) FROM fleet.fleet" in sql:
            rows = self.fleets
            if "org_id = $1" in sql:
                rows = [r for r in rows if r["org_id"] == args[0]]
            return len(rows)
        if "count(*) FROM fleet.device" in sql:
            rows = self.devices
            # count_devices(conn, None, org) → WHERE org_id = $1
            if "org_id = $1" in sql:
                rows = [r for r in rows if r["org_id"] == args[0]]
            return len(rows)
        return 0

    async def fetch(self, sql, *args):
        if "FROM fleet.usage_counter" in sql and "sum(count)" in sql:  # totals
            org = args[0]
            agg: dict[str, int] = {}
            for (o, metric, _p), c in self.usage.items():
                if o == org:
                    agg[metric] = agg.get(metric, 0) + c
            return [{"metric": m, "total": c} for m, c in agg.items()]
        if "FROM fleet.usage_counter" in sql:  # 當日 counters
            org, period = args[0], args[1]
            return [
                {"metric": m, "count": c}
                for (o, m, p), c in self.usage.items()
                if o == org and p == period
            ]
        return []

    async def fetchrow(self, sql, *args):
        if "INSERT INTO fleet.fleet" in sql:
            row = {
                "id": uuid4(), "name": args[0], "org_id": args[1],
                "created_at": datetime.now(timezone.utc),
            }
            self.fleets.append(row)
            return row
        if "INSERT INTO fleet.device" in sql:
            row = {
                "id": uuid4(), "serial": args[0], "name": args[1], "fleet_id": args[2],
                "org_id": args[3], "model": args[4], "status": "provisioned",
                "cert_fingerprint": None, "cert_not_after": None,
                "created_at": datetime.now(timezone.utc),
            }
            self.devices.append(row)
            return row
        return None

    async def execute(self, sql, *args):
        if "INSERT INTO fleet.usage_counter" in sql:
            key = (args[0], args[1], args[2])
            self.usage[key] = self.usage.get(key, 0) + 1
        return "INSERT 0 1"


class _MemPool:
    def __init__(self, conn: _MemConn) -> None:
        self._conn = conn

    def acquire(self):
        pool = self

        class _Acq:
            async def __aenter__(self):
                return pool._conn

            async def __aexit__(self, *a):
                return False

        return _Acq()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "JWT_SECRET", SECRET)
    monkeypatch.setattr(auth, "_jwks_client", None)
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    # 限流用寬鬆預設(6000/分),煙霧/多數測試不誤傷;需觸發時各測試自行調降上限。
    conn = _MemConn()
    main.app.state.pool = _MemPool(conn)
    return TestClient(main.app), conn


def _tok(role: str, org: str | None) -> dict:
    claims: dict = {"sub": f"{role}-{org}", "role": role}
    if org is not None:
        claims["org"] = org
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


def _fleet(c, name: str, role: str, org: str):
    return c.post("/api/v1/fleets", json={"name": name}, headers=_tok(role, org))


def _device(c, serial: str, role: str, org: str):
    return c.post("/api/v1/devices", json={"serial": serial}, headers=_tok(role, org))


# ---- 計量 ----


def test_usage_metering_increments(client):
    c, conn = client
    c.post("/api/v1/fleets", json={"name": "f1"}, headers=_tok("operator", "acme"))
    c.post("/api/v1/fleets", json={"name": "f2"}, headers=_tok("operator", "acme"))
    r = c.get("/api/v1/usage", headers=_tok("viewer", "acme"))
    assert r.status_code == 200
    body = r.json()
    assert body["org_id"] == "acme"
    assert body["counters"]["fleet_created"] == 2
    assert body["totals"]["fleet_created"] == 2
    assert body["resources"]["fleets"] == 2
    assert body["limits"]["max_fleets"] == limits.QUOTA_MAX_FLEETS


def test_usage_org_isolation(client):
    c, conn = client
    c.post("/api/v1/fleets", json={"name": "a"}, headers=_tok("operator", "orgA"))
    c.post("/api/v1/fleets", json={"name": "b1"}, headers=_tok("operator", "orgB"))
    c.post("/api/v1/fleets", json={"name": "b2"}, headers=_tok("operator", "orgB"))
    # orgA 的用量不含 orgB
    ra = c.get("/api/v1/usage", headers=_tok("viewer", "orgA"))
    assert ra.json()["counters"].get("fleet_created") == 1
    assert ra.json()["resources"]["fleets"] == 1
    # 非 admin 帶 ?org=orgB 越權 → 被忽略,仍看自己
    ra2 = c.get("/api/v1/usage", params={"org": "orgB"}, headers=_tok("viewer", "orgA"))
    assert ra2.json()["org_id"] == "orgA"


# ---- 配額(402)----


def test_quota_exceeded_returns_402(client, monkeypatch):
    c, conn = client
    monkeypatch.setattr(limits, "QUOTA_MAX_FLEETS", 2)
    assert _fleet(c, "1", "operator", "acme").status_code == 201
    assert _fleet(c, "2", "operator", "acme").status_code == 201
    assert _fleet(c, "3", "operator", "acme").status_code == 402


def test_device_quota_exceeded_returns_402(client, monkeypatch):
    c, conn = client
    monkeypatch.setattr(limits, "QUOTA_MAX_DEVICES", 1)
    assert _device(c, "S1", "operator", "acme").status_code == 201
    assert _device(c, "S2", "operator", "acme").status_code == 402


def test_quota_admin_exempt(client, monkeypatch):
    c, conn = client
    monkeypatch.setattr(limits, "QUOTA_MAX_FLEETS", 1)
    # admin 不受配額限制
    for i in range(3):
        assert _fleet(c, f"a{i}", "admin", "plat").status_code == 201


def test_quota_dev_mode_not_blocked(monkeypatch):
    # dev 模式(認證停用)= admin,配額不阻塞
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    monkeypatch.setattr(limits, "QUOTA_MAX_FLEETS", 1)
    conn = _MemConn()
    main.app.state.pool = _MemPool(conn)
    c = TestClient(main.app)
    for i in range(3):
        assert c.post("/api/v1/fleets", json={"name": f"d{i}"}).status_code == 201


# ---- 限流(429)----


def _freeze_time(monkeypatch, t: float = 1_000_000.0) -> None:
    """凍結限流所用時鐘,使一測試內所有請求落同一固定視窗(端點路徑無法注入 now)。"""
    monkeypatch.setattr(limits.time, "time", lambda: t)


def test_rate_limit_exceeded_returns_429(client, monkeypatch):
    c, conn = client
    monkeypatch.setattr(limits, "RATE_LIMIT_PER_MIN", 2)
    _freeze_time(monkeypatch)
    assert _fleet(c, "1", "operator", "acme").status_code == 201
    assert _fleet(c, "2", "operator", "acme").status_code == 201
    r = _fleet(c, "3", "operator", "acme")
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_rate_limit_admin_exempt(client, monkeypatch):
    c, conn = client
    monkeypatch.setattr(limits, "RATE_LIMIT_PER_MIN", 1)
    _freeze_time(monkeypatch)
    # admin 豁免限流:連打多次仍放行
    for i in range(4):
        assert _fleet(c, f"a{i}", "admin", "plat").status_code == 201


def test_rate_limit_per_org_isolated(client, monkeypatch):
    c, conn = client
    monkeypatch.setattr(limits, "RATE_LIMIT_PER_MIN", 1)
    _freeze_time(monkeypatch)
    # orgA 燒完額度,orgB 仍可寫(per-org 隔離)
    assert _fleet(c, "a", "operator", "orgA").status_code == 201
    assert _fleet(c, "a2", "operator", "orgA").status_code == 429
    assert _fleet(c, "b", "operator", "orgB").status_code == 201


def test_rate_limit_endpoint_window_rollover_resets(client, monkeypatch):
    c, conn = client
    monkeypatch.setattr(limits, "RATE_LIMIT_PER_MIN", 1)
    monkeypatch.setattr(limits.time, "time", lambda: 1_000_000.0)  # 視窗 [999960,1000020)
    assert _fleet(c, "a", "operator", "orgA").status_code == 201
    assert _fleet(c, "a2", "operator", "orgA").status_code == 429
    # 時間推進到下一視窗 → 計數重置,再次放行
    monkeypatch.setattr(limits.time, "time", lambda: 1_000_080.0)
    assert _fleet(c, "a3", "operator", "orgA").status_code == 201


def test_reads_not_rate_limited(client, monkeypatch):
    c, conn = client
    monkeypatch.setattr(limits, "RATE_LIMIT_PER_MIN", 1)
    _freeze_time(monkeypatch)
    # 讀取不限流:多次 GET 皆 200
    for _ in range(5):
        assert c.get("/api/v1/usage", headers=_tok("viewer", "acme")).status_code == 200

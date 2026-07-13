"""用量計量 + 配額 + 限流(G30)。四層驗證,皆不碰真 DB:

1. RateLimiter 單元:token bucket 放行至容量、超限回 Retry-After>0、隨時間補充。
2. repo 計量 SQL 契約:increment/usage_count/get/totals 綁正確參數與原子遞增語法。
3. 配額(402):每日任務量超限回 402;航線現存上限回 402;admin 豁免;dev 不阻塞。
4. 限流(429):超速回 429 + Retry-After;admin 豁免;org 隔離。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from mission_svc import auth, limits, main, repo
from mission_svc.limits import RateLimiter

# ----------------------------------------------------------------------------
# 1. RateLimiter 單元
# ----------------------------------------------------------------------------


def test_rate_limiter_allows_up_to_capacity_then_blocks():
    rl = RateLimiter(rate_per_min=60, burst=2)
    assert rl.check("o", now=0.0) == 0.0
    assert rl.check("o", now=0.0) == 0.0
    assert rl.check("o", now=0.0) > 0.0


def test_rate_limiter_refills_over_time():
    rl = RateLimiter(rate_per_min=60, burst=1)
    assert rl.check("o", now=0.0) == 0.0
    assert rl.check("o", now=0.0) > 0.0
    assert rl.check("o", now=1.0) == 0.0


# ----------------------------------------------------------------------------
# 2. repo 計量 SQL 契約
# ----------------------------------------------------------------------------


class _RecConn:
    def __init__(self, fetch_rows: list | None = None, fetchval=0) -> None:
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
    asyncio.run(repo.increment_usage(conn, "acme", "mission_created", p))
    sql, args = conn.execute_calls[0]
    assert "INSERT INTO mission.usage_counter" in sql
    assert "ON CONFLICT (org_id, metric, period)" in sql
    assert "count = mission.usage_counter.count + 1" in sql
    assert args == ("acme", "mission_created", p)


def test_usage_count_scoped():
    conn = _RecConn(fetchval=7)
    p = date(2026, 7, 13)
    out = asyncio.run(repo.usage_count(conn, "acme", "mission_created", p))
    sql, args = conn.fetchval_calls[0]
    assert "WHERE org_id = $1 AND metric = $2 AND period = $3" in sql
    assert args == ("acme", "mission_created", p) and out == 7


def test_usage_count_null_is_zero():
    conn = _RecConn(fetchval=None)
    assert asyncio.run(repo.usage_count(conn, "acme", "m", date(2026, 7, 13))) == 0


def test_get_usage_totals_grouped():
    conn = _RecConn(fetch_rows=[{"metric": "mission_created", "total": 3}])
    out = asyncio.run(repo.get_usage_totals(conn, "acme"))
    assert "GROUP BY metric" in conn.fetch_calls[0][0]
    assert out == {"mission_created": 3}


# ----------------------------------------------------------------------------
# 3 & 4. 端點層
# ----------------------------------------------------------------------------

SECRET = "test-secret-key-mission-limits-g30-0123456789"
_WPS = [{"lat_deg": 1.0, "lon_deg": 2.0}]


class _MemConn:
    """支援 route / mission 計數 + usage_counter 的記憶體連線。"""

    def __init__(self) -> None:
        self.routes: list[dict] = []
        self.missions: list[dict] = []
        self.usage: dict[tuple, int] = {}

    async def fetchval(self, sql, *args):
        if "count(*) FROM mission.route" in sql:
            rows = self.routes
            if "org_id = $1" in sql:
                rows = [r for r in rows if r["org_id"] == args[0]]
            return len(rows)
        if "count(*) FROM mission.mission" in sql:
            rows = self.missions
            if "org_id = $1" in sql:
                rows = [r for r in rows if r["org_id"] == args[0]]
            return len(rows)
        if "FROM mission.usage_counter" in sql and "SELECT count" in sql:
            key = (args[0], args[1], args[2])
            return self.usage.get(key)
        return 0

    async def fetch(self, sql, *args):
        if "FROM mission.usage_counter" in sql and "sum(count)" in sql:
            org = args[0]
            agg: dict[str, int] = {}
            for (o, metric, _p), c in self.usage.items():
                if o == org:
                    agg[metric] = agg.get(metric, 0) + c
            return [{"metric": m, "total": c} for m, c in agg.items()]
        if "FROM mission.usage_counter" in sql:
            org, period = args[0], args[1]
            return [
                {"metric": m, "count": c}
                for (o, m, p), c in self.usage.items()
                if o == org and p == period
            ]
        return []

    async def fetchrow(self, sql, *args):
        if "INSERT INTO mission.route" in sql:
            row = {
                "id": uuid4(), "name": args[0], "org_id": args[1], "waypoints": args[2],
                "rtl_after_last": args[3], "created_at": datetime.now(timezone.utc),
            }
            self.routes.append(row)
            return row
        if "FROM mission.route WHERE id = $1" in sql:
            rid = args[0]
            for r in self.routes:
                if r["id"] == rid and ("org_id = $2" not in sql or r["org_id"] == args[1]):
                    return r
            return None
        if "INSERT INTO mission.mission" in sql:
            row = {
                "id": uuid4(), "mission_id": args[0], "route_id": args[1], "org_id": args[2],
                "drone_id": args[3], "status": "created", "waypoints": args[4],
                "rtl_after_last": args[5], "current_item": None, "total_items": args[6],
                "dispatched_at": None, "finished_at": None,
                "created_at": datetime.now(timezone.utc),
            }
            self.missions.append(row)
            return row
        return None

    async def execute(self, sql, *args):
        if "INSERT INTO mission.usage_counter" in sql:
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
    monkeypatch.setattr(limits, "write_limiter", RateLimiter(rate_per_min=6000))
    conn = _MemConn()
    main.app.state.pool = _MemPool(conn)
    return TestClient(main.app), conn


def _tok(role: str, org: str | None) -> dict:
    claims: dict = {"sub": f"{role}-{org}", "role": role}
    if org is not None:
        claims["org"] = org
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


def _route(c, name: str, role: str, org: str):
    return c.post("/api/v1/routes", json={"name": name, "waypoints": _WPS}, headers=_tok(role, org))


def _mission(c, route_id: str, drone: str, role: str, org: str):
    return c.post(
        "/api/v1/missions", json={"route_id": route_id, "drone_id": drone}, headers=_tok(role, org)
    )


def _mk_route(c, org: str) -> str:
    r = _route(c, "r", "operator", org)
    assert r.status_code == 201
    return r.json()["id"]


# ---- 計量 ----


def test_usage_metering_route_and_mission(client):
    c, conn = client
    rid = _mk_route(c, "acme")
    _mission(c, rid, "d1", "operator", "acme")
    r = c.get("/api/v1/usage", headers=_tok("viewer", "acme"))
    assert r.status_code == 200
    body = r.json()
    assert body["counters"]["route_created"] == 1
    assert body["counters"]["mission_created"] == 1
    assert body["resources"]["routes"] == 1
    assert body["resources"]["missions"] == 1
    assert body["limits"]["max_missions_per_day"] == limits.QUOTA_MAX_MISSIONS_PER_DAY


def test_usage_org_isolation(client):
    c, conn = client
    _mk_route(c, "orgA")
    _mk_route(c, "orgB")
    _mk_route(c, "orgB")
    ra = c.get("/api/v1/usage", headers=_tok("viewer", "orgA"))
    assert ra.json()["counters"].get("route_created") == 1
    assert ra.json()["resources"]["routes"] == 1


# ---- 配額(402)----


def test_missions_per_day_quota_402(client, monkeypatch):
    c, conn = client
    monkeypatch.setattr(limits, "QUOTA_MAX_MISSIONS_PER_DAY", 1)
    rid = _mk_route(c, "acme")
    assert _mission(c, rid, "d1", "operator", "acme").status_code == 201
    assert _mission(c, rid, "d2", "operator", "acme").status_code == 402


def test_routes_quota_402(client, monkeypatch):
    c, conn = client
    monkeypatch.setattr(limits, "QUOTA_MAX_ROUTES", 1)
    assert _route(c, "r1", "operator", "acme").status_code == 201
    assert _route(c, "r2", "operator", "acme").status_code == 402


def test_quota_admin_exempt(client, monkeypatch):
    c, conn = client
    monkeypatch.setattr(limits, "QUOTA_MAX_ROUTES", 1)
    for i in range(3):
        assert _route(c, f"r{i}", "admin", "plat").status_code == 201


def test_quota_dev_mode_not_blocked(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    monkeypatch.setattr(limits, "QUOTA_MAX_ROUTES", 1)
    monkeypatch.setattr(limits, "write_limiter", RateLimiter(rate_per_min=6000))
    conn = _MemConn()
    main.app.state.pool = _MemPool(conn)
    c = TestClient(main.app)
    for i in range(3):
        assert c.post(
            "/api/v1/routes", json={"name": f"d{i}", "waypoints": _WPS}
        ).status_code == 201


# ---- 限流(429)----


def test_rate_limit_429(client, monkeypatch):
    c, conn = client
    monkeypatch.setattr(limits, "write_limiter", RateLimiter(rate_per_min=60, burst=2))
    assert _route(c, "1", "operator", "acme").status_code == 201
    assert _route(c, "2", "operator", "acme").status_code == 201
    r = _route(c, "3", "operator", "acme")
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_rate_limit_admin_exempt(client, monkeypatch):
    c, conn = client
    monkeypatch.setattr(limits, "write_limiter", RateLimiter(rate_per_min=60, burst=1))
    for i in range(4):
        assert _route(c, f"a{i}", "admin", "plat").status_code == 201


def test_rate_limit_per_org_isolated(client, monkeypatch):
    c, conn = client
    monkeypatch.setattr(limits, "write_limiter", RateLimiter(rate_per_min=60, burst=1))
    assert _route(c, "a", "operator", "orgA").status_code == 201
    assert _route(c, "a2", "operator", "orgA").status_code == 429
    assert _route(c, "b", "operator", "orgB").status_code == 201

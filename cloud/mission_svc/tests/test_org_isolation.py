"""多租戶 org 隔離(G11,安全關鍵)。三層驗證,皆不碰真 DB:

1. auth 層:org claim 萃取、Principal 推導、read_org 語義。
2. repo 層(SQL 契約):list/get/count 帶 org 過濾;create_route/create_mission 綁定呼叫者 org;
   create_mission 以呼叫者 org 查 route(他 org route → None)。
3. 端點層(TestClient + 記憶體連線):org A 的 viewer 看不到 org B 的航線/任務(list 不含、
   get 回 404);建立資源綁到呼叫者 org;admin 跨 org;dev 模式預設 org。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from mission_svc import auth, main, repo
from mission_svc.auth import DEV_ORG, Principal, build_principal, extract_org, read_org
from mission_svc.models import MissionCreate, RouteCreate, Waypoint

# ----------------------------------------------------------------------------
# 1. auth 層
# ----------------------------------------------------------------------------


def test_extract_org_and_principal():
    assert extract_org({"org": "acme"}) == "acme"
    assert extract_org({"org_id": "beta"}) == "beta"
    assert extract_org({}) is None
    assert build_principal({"role": "viewer", "org": "acme"}).org == "acme"
    assert build_principal({"role": "viewer"}).org == DEV_ORG  # fallback
    assert build_principal({"role": "admin", "org": "x"}).is_admin is True


def _p(org: str, admin: bool) -> Principal:
    return Principal(claims={}, role="admin" if admin else "viewer", org=org, is_admin=admin)


def test_read_org_semantics():
    assert read_org(_p("acme", False), "beta") == "acme"  # 非 admin 鎖本 org
    assert read_org(_p("plat", True), None) is None  # admin 看全部
    assert read_org(_p("plat", True), "beta") == "beta"  # admin 指定


# ----------------------------------------------------------------------------
# 2. repo 層:SQL 契約
# ----------------------------------------------------------------------------

_WPS = [Waypoint(lat_deg=25.0, lon_deg=121.5)]


class _StubConn:
    def __init__(self, row: dict | None = None) -> None:
        self.fetch_calls: list[tuple] = []
        self.fetchval_calls: list[tuple] = []
        self.fetchrow_calls: list[tuple] = []
        self._row = row

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        return []

    async def fetchval(self, sql, *args):
        self.fetchval_calls.append((sql, args))
        return 0

    async def fetchrow(self, sql, *args):
        self.fetchrow_calls.append((sql, args))
        return self._row


def _route_row(org: str) -> dict:
    return {
        "id": uuid4(), "name": "r", "org_id": org,
        "waypoints": json.dumps([w.model_dump() for w in _WPS]),
        "rtl_after_last": True, "created_at": datetime.now(timezone.utc),
    }


def _mission_row(org: str, route_id) -> dict:
    return {
        "id": uuid4(), "mission_id": "m-1", "route_id": route_id, "org_id": org,
        "drone_id": "d1", "status": "created",
        "waypoints": json.dumps([w.model_dump() for w in _WPS]),
        "rtl_after_last": True, "current_item": None, "total_items": 1,
        "dispatched_at": None, "finished_at": None, "created_at": datetime.now(timezone.utc),
    }


def test_create_route_binds_caller_org():
    conn = _StubConn(row=_route_row("acme"))
    asyncio.run(repo.create_route(conn, RouteCreate(name="r", waypoints=_WPS), "acme"))
    sql, args = conn.fetchrow_calls[0]
    assert "INSERT INTO mission.route" in sql
    assert args[0] == "r" and args[1] == "acme"  # (name, org, ...)


def test_list_routes_org_filter():
    conn = _StubConn()
    asyncio.run(repo.list_routes(conn, org="acme", limit=7, offset=3))
    sql, args = conn.fetch_calls[0]
    assert "WHERE org_id = $1" in sql and args == ("acme", 7, 3)


def test_get_route_org_scoped():
    conn = _StubConn(row=None)
    rid = uuid4()
    asyncio.run(repo.get_route(conn, rid, org="acme"))
    sql, args = conn.fetchrow_calls[0]
    assert "WHERE id = $1 AND org_id = $2" in sql and args == (rid, "acme")


def test_count_routes_org_scoped():
    conn = _StubConn()
    asyncio.run(repo.count_routes(conn, org="acme"))
    assert "WHERE org_id = $1" in conn.fetchval_calls[0][0]
    assert conn.fetchval_calls[0][1] == ("acme",)


def test_create_mission_looks_up_route_within_caller_org():
    # route 查找須帶呼叫者 org:他 org route → get_route 回 None → create 回 None
    conn = _StubConn(row=None)  # 模擬本 org 找不到該 route
    rid = uuid4()
    out = asyncio.run(
        repo.create_mission(conn, MissionCreate(route_id=rid, drone_id="d1"), "acme")
    )
    assert out is None
    sql, args = conn.fetchrow_calls[0]  # get_route
    assert "mission.route WHERE id = $1 AND org_id = $2" in sql
    assert args == (rid, "acme")


def test_create_mission_binds_caller_org():
    rid = uuid4()
    route = _route_row("acme")
    route["id"] = rid
    mission = _mission_row("acme", rid)

    class _Seq(_StubConn):
        def __init__(self):
            super().__init__()
            self._rows = [route, mission]  # 先 get_route,再 INSERT mission

        async def fetchrow(self, sql, *args):
            self.fetchrow_calls.append((sql, args))
            return self._rows.pop(0)

    conn = _Seq()
    asyncio.run(repo.create_mission(conn, MissionCreate(route_id=rid, drone_id="d1"), "acme"))
    ins_sql, ins_args = conn.fetchrow_calls[1]
    assert "INSERT INTO mission.mission" in ins_sql and "org_id" in ins_sql
    assert ins_args[2] == "acme"  # (mission_id, route_id, org, drone_id, ...)


def test_list_missions_combines_drone_and_org():
    conn = _StubConn()
    asyncio.run(repo.list_missions(conn, drone_id="d1", org="acme", limit=5, offset=2))
    sql, args = conn.fetch_calls[0]
    assert "drone_id = $1" in sql and "org_id = $2" in sql
    assert "LIMIT $3 OFFSET $4" in sql and args == ("d1", "acme", 5, 2)


def test_get_mission_org_scoped():
    conn = _StubConn(row=None)
    mid = uuid4()
    asyncio.run(repo.get_mission(conn, mid, org="acme"))
    sql, args = conn.fetchrow_calls[0]
    assert "WHERE id = $1 AND org_id = $2" in sql and args == (mid, "acme")


# ----------------------------------------------------------------------------
# 3. 端點層:記憶體連線 + TestClient
# ----------------------------------------------------------------------------


class _MemConn:
    """支援 route/mission 端點查詢的記憶體連線(org 過濾以 Python 忠實模擬)。"""

    def __init__(self) -> None:
        self.routes: list[dict] = []
        self.missions: list[dict] = []

    async def fetchval(self, sql, *args):
        table = self.routes if "mission.route" in sql else self.missions
        if "count(*)" in sql:
            if "org_id = $1" in sql:
                return len([r for r in table if r["org_id"] == args[0]])
            return len(table)
        return 0

    async def fetch(self, sql, *args):
        table = self.routes if "FROM mission.route" in sql else self.missions
        rows = list(table)
        if "WHERE org_id = $1" in sql:
            rows = [r for r in rows if r["org_id"] == args[0]]
        return rows

    async def fetchrow(self, sql, *args):
        if "INSERT INTO mission.route" in sql:
            row = {
                "id": uuid4(), "name": args[0], "org_id": args[1], "waypoints": args[2],
                "rtl_after_last": args[3], "created_at": datetime.now(timezone.utc),
            }
            self.routes.append(row)
            return row
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
        if "FROM mission.route WHERE id = $1" in sql:
            for r in self.routes:
                if r["id"] == args[0] and ("org_id = $2" not in sql or r["org_id"] == args[1]):
                    return r
            return None
        if "FROM mission.mission WHERE id = $1" in sql:
            for m in self.missions:
                if m["id"] == args[0] and ("org_id = $2" not in sql or m["org_id"] == args[1]):
                    return m
            return None
        return None

    async def execute(self, sql, *args):
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


SECRET = "test-secret-key-org-isolation-mission-0123456789"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "JWT_SECRET", SECRET)
    monkeypatch.setattr(auth, "_jwks_client", None)
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    conn = _MemConn()
    main.app.state.pool = _MemPool(conn)
    return TestClient(main.app), conn


def _tok(role: str, org: str | None) -> dict:
    claims: dict = {"sub": f"{role}-{org}", "role": role}
    if org is not None:
        claims["org"] = org
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


def _route_payload() -> dict:
    return {"name": "r", "waypoints": [{"lat_deg": 25.0, "lon_deg": 121.5}]}


def test_endpoint_route_create_binds_caller_org(client):
    c, conn = client
    r = c.post("/api/v1/routes", json=_route_payload(), headers=_tok("operator", "acme"))
    assert r.status_code == 201 and r.json()["org_id"] == "acme"
    assert conn.routes[0]["org_id"] == "acme"


def test_endpoint_cross_org_route_and_mission_isolation(client):
    c, conn = client
    # org A 建 route + mission
    ra = c.post("/api/v1/routes", json=_route_payload(), headers=_tok("operator", "orgA"))
    a_route = ra.json()["id"]
    ma = c.post(
        "/api/v1/missions", json={"route_id": a_route, "drone_id": "dA"},
        headers=_tok("operator", "orgA"),
    )
    assert ma.status_code == 201 and ma.json()["org_id"] == "orgA"
    a_mission = ma.json()["id"]

    # org B 建自己的
    rb = c.post("/api/v1/routes", json=_route_payload(), headers=_tok("operator", "orgB"))
    b_route = rb.json()["id"]

    # org B viewer:route list 只見自己的
    lb = c.get("/api/v1/routes", headers=_tok("viewer", "orgB"))
    assert [x["id"] for x in lb.json()] == [b_route]

    # org B viewer 取 A 的 route / mission → 404
    assert c.get(f"/api/v1/routes/{a_route}", headers=_tok("viewer", "orgB")).status_code == 404
    assert (
        c.get(f"/api/v1/missions/{a_mission}", headers=_tok("viewer", "orgB")).status_code == 404
    )

    # org B operator 不能以 A 的 route 建任務(route 查找限本 org → 404)
    xb = c.post(
        "/api/v1/missions", json={"route_id": a_route, "drone_id": "dB"},
        headers=_tok("operator", "orgB"),
    )
    assert xb.status_code == 404

    # org B operator 不能派遣/控制 A 的任務 → 404
    assert (
        c.post(f"/api/v1/missions/{a_mission}/dispatch", headers=_tok("operator", "orgB"))
        .status_code == 404
    )
    assert (
        c.post(
            f"/api/v1/missions/{a_mission}/command", json={"command": "pause"},
            headers=_tok("operator", "orgB"),
        ).status_code == 404
    )

    # org A 取自己的 → 200
    assert c.get(f"/api/v1/missions/{a_mission}", headers=_tok("viewer", "orgA")).status_code == 200


def test_endpoint_admin_cross_org(client):
    c, conn = client
    c.post("/api/v1/routes", json=_route_payload(), headers=_tok("operator", "orgA"))
    c.post("/api/v1/routes", json=_route_payload(), headers=_tok("operator", "orgB"))
    la = c.get("/api/v1/routes", headers=_tok("admin", "plat"))
    assert {x["org_id"] for x in la.json()} == {"orgA", "orgB"}
    lf = c.get("/api/v1/routes", params={"org": "orgB"}, headers=_tok("admin", "plat"))
    assert {x["org_id"] for x in lf.json()} == {"orgB"}


def test_endpoint_dev_mode_default_org(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    conn = _MemConn()
    main.app.state.pool = _MemPool(conn)
    c = TestClient(main.app)
    r = c.post("/api/v1/routes", json=_route_payload())
    assert r.status_code == 201 and r.json()["org_id"] == DEV_ORG

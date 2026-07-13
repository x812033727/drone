"""多租戶 org 隔離(G11,安全關鍵)。三層驗證,皆不碰真 DB:

1. auth 層:org claim 萃取、Principal 推導、read_org(admin 跨 org / 非 admin 限本 org)。
2. repo 層(SQL 契約):每個 list/get/count/update/delete 都帶 org 過濾且綁定正確 org 值;
   create 一律寫入呼叫者 org(不採信 client)。
3. 端點層(TestClient + 記憶體連線):org A 的 viewer 看不到 org B 的機隊(list 不含、
   get 回 404);建立資源綁到呼叫者 org;admin 跨 org;dev 模式預設 org。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from fleet_svc import auth, main, repo
from fleet_svc.auth import DEV_ORG, Principal, build_principal, extract_org, read_org
from fleet_svc.models import DeviceUpdate, FleetCreate

# ----------------------------------------------------------------------------
# 1. auth 層
# ----------------------------------------------------------------------------


def test_extract_org_from_org_and_org_id():
    assert extract_org({"org": "acme"}) == "acme"
    assert extract_org({"org_id": "beta"}) == "beta"
    # org 優先於 org_id
    assert extract_org({"org": "acme", "org_id": "beta"}) == "acme"
    # 去空白;空字串/缺漏視為無
    assert extract_org({"org": "  acme  "}) == "acme"
    assert extract_org({"org": "   "}) is None
    assert extract_org({}) is None


def test_build_principal_org_and_admin_flag():
    p = build_principal({"sub": "u", "role": "viewer", "org": "acme"})
    assert p.org == "acme" and p.is_admin is False and p.role == "viewer"
    a = build_principal({"sub": "b", "role": "admin", "org": "acme"})
    assert a.is_admin is True
    # 無 org claim → fallback DEV_ORG(絕不跨真實租戶)
    assert build_principal({"sub": "u", "role": "viewer"}).org == DEV_ORG


def _p(org: str, admin: bool) -> Principal:
    return Principal(claims={}, role="admin" if admin else "viewer", org=org, is_admin=admin)


def test_read_org_non_admin_locked_to_own_org():
    # 非 admin 一律限本 org,忽略 requested(防越權指定他 org)
    assert read_org(_p("acme", False), None) == "acme"
    assert read_org(_p("acme", False), "beta") == "acme"


def test_read_org_admin_cross_org():
    # admin:未指定 → None(看全部);指定 → 該 org
    assert read_org(_p("plat", True), None) is None
    assert read_org(_p("plat", True), "beta") == "beta"


def test_dev_mode_claims_carry_default_org():
    # 認證停用時 authorize_token 回 admin + org=default(cloud-smoke 全放行)
    claims = auth.authorize_token(None, "operator") if not auth.AUTH_ENABLED else None
    if claims is not None:
        assert claims["org"] == DEV_ORG
        assert build_principal(claims).is_admin is True


# ----------------------------------------------------------------------------
# 2. repo 層:SQL 契約(記錄 SQL/參數的 stub 連線)
# ----------------------------------------------------------------------------


class _StubConn:
    def __init__(self, row: dict | None = None) -> None:
        self.fetch_calls: list[tuple] = []
        self.fetchval_calls: list[tuple] = []
        self.fetchrow_calls: list[tuple] = []
        self.execute_calls: list[tuple] = []
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

    async def execute(self, sql, *args):
        self.execute_calls.append((sql, args))
        return "DELETE 1"


def _fleet_row(org: str) -> dict:
    return {"id": uuid4(), "name": "f", "org_id": org, "created_at": datetime.now(timezone.utc)}


def _device_row(org: str) -> dict:
    return {
        "id": uuid4(), "serial": "SN", "name": None, "fleet_id": None, "org_id": org,
        "model": None, "status": "active", "cert_fingerprint": None,
        "cert_not_after": None, "created_at": datetime.now(timezone.utc),
    }


def test_create_fleet_binds_caller_org_not_client():
    conn = _StubConn(row=_fleet_row("acme"))
    # 即使 client 送了別的東西,repo 只吃傳入的 org 參數
    asyncio.run(repo.create_fleet(conn, FleetCreate(name="f"), "acme"))
    sql, args = conn.fetchrow_calls[0]
    assert "INSERT INTO fleet.fleet" in sql
    assert args == ("f", "acme")  # (name, org)——org 來自呼叫者,非 client


def test_create_device_binds_caller_org():
    from fleet_svc.models import DeviceCreate
    conn = _StubConn(row=_device_row("acme"))
    asyncio.run(repo.create_device(conn, DeviceCreate(serial="SN"), "acme"))
    sql, args = conn.fetchrow_calls[0]
    assert "INSERT INTO fleet.device" in sql and "org_id" in sql
    assert args[3] == "acme"  # (serial, name, fleet_id, org, model)


def test_list_fleets_applies_org_filter():
    conn = _StubConn()
    asyncio.run(repo.list_fleets(conn, org="acme", limit=10, offset=0))
    sql, args = conn.fetch_calls[0]
    assert "WHERE org_id = $1" in sql
    assert args == ("acme", 10, 0)


def test_list_fleets_none_org_no_filter():
    conn = _StubConn()
    asyncio.run(repo.list_fleets(conn, org=None))
    sql, args = conn.fetch_calls[0]
    assert "WHERE" not in sql  # admin 全部:不加 org 過濾
    assert args == (100, 0)


def test_get_fleet_org_scoped():
    conn = _StubConn(row=None)
    fid = uuid4()
    asyncio.run(repo.get_fleet(conn, fid, org="acme"))
    sql, args = conn.fetchrow_calls[0]
    assert "WHERE id = $1 AND org_id = $2" in sql
    assert args == (fid, "acme")


def test_count_fleets_org_scoped():
    conn = _StubConn()
    asyncio.run(repo.count_fleets(conn, org="acme"))
    sql, args = conn.fetchval_calls[0]
    assert "WHERE org_id = $1" in sql and args == ("acme",)


def test_list_devices_combines_fleet_and_org_filter():
    conn = _StubConn()
    fid = uuid4()
    asyncio.run(repo.list_devices(conn, fleet_id=fid, org="acme", limit=5, offset=2))
    sql, args = conn.fetch_calls[0]
    assert "fleet_id = $1" in sql and "org_id = $2" in sql
    assert "LIMIT $3 OFFSET $4" in sql
    assert args == (fid, "acme", 5, 2)


def test_get_device_org_scoped():
    conn = _StubConn(row=None)
    did = uuid4()
    asyncio.run(repo.get_device(conn, did, org="acme"))
    sql, args = conn.fetchrow_calls[0]
    assert "WHERE id = $1 AND org_id = $2" in sql and args == (did, "acme")


def test_update_device_org_scoped_where():
    conn = _StubConn(row=_device_row("acme"))
    did = uuid4()
    asyncio.run(repo.update_device(conn, did, DeviceUpdate(name="x"), org="acme"))
    sql, args = conn.fetchrow_calls[0]
    # SET name = $1 WHERE id = $2 AND org_id = $3
    assert "WHERE id = $2 AND org_id = $3" in sql
    assert args == ("x", did, "acme")


def test_delete_device_org_scoped():
    conn = _StubConn()
    did = uuid4()
    asyncio.run(repo.delete_device(conn, did, org="acme"))
    sql, args = conn.execute_calls[0]
    assert "WHERE id = $1 AND org_id = $2" in sql and args == (did, "acme")


def test_status_queries_org_scoped():
    conn = _StubConn(row=None)
    did = uuid4()
    fid = uuid4()
    asyncio.run(repo.get_device_status(conn, did, org="acme"))
    assert "d.org_id = $3" in conn.fetchrow_calls[0][0]
    assert conn.fetchrow_calls[0][1] == (repo.ONLINE_THRESHOLD_S, did, "acme")

    conn2 = _StubConn()
    asyncio.run(repo.list_all_status(conn2, org="acme"))
    assert "d.org_id = $2" in conn2.fetch_calls[0][0]
    asyncio.run(repo.list_fleet_status(conn2, fid, org="acme"))
    assert "d.fleet_id = $2 AND d.org_id = $3" in conn2.fetch_calls[1][0]


# ----------------------------------------------------------------------------
# 3. 端點層:記憶體連線 + TestClient,證明跨租戶不可見
# ----------------------------------------------------------------------------


class _MemConn:
    """僅支援 fleet.fleet 端點所需查詢的記憶體連線(org 過濾以 Python 忠實模擬)。"""

    def __init__(self, fleets: list[dict]) -> None:
        self.fleets = fleets

    async def fetchval(self, sql, *args):
        if "count(*) FROM fleet.fleet" in sql:
            rows = self.fleets
            if "org_id = $1" in sql:
                rows = [r for r in rows if r["org_id"] == args[0]]
            return len(rows)
        return 0

    async def fetch(self, sql, *args):
        if "FROM fleet.fleet" in sql:
            rows = list(self.fleets)
            if "WHERE org_id = $1" in sql:
                rows = [r for r in rows if r["org_id"] == args[0]]
            return rows
        return []

    async def fetchrow(self, sql, *args):
        if "INSERT INTO fleet.fleet" in sql:
            row = {
                "id": uuid4(), "name": args[0], "org_id": args[1],
                "created_at": datetime.now(timezone.utc),
            }
            self.fleets.append(row)
            return row
        if "FROM fleet.fleet WHERE id = $1" in sql:
            fid = args[0]
            for r in self.fleets:
                if r["id"] == fid and ("org_id = $2" not in sql or r["org_id"] == args[1]):
                    return r
            return None
        return None

    async def execute(self, sql, *args):  # audit_log INSERT 等
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


SECRET = "test-secret-key-org-isolation-0123456789"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "JWT_SECRET", SECRET)
    monkeypatch.setattr(auth, "_jwks_client", None)
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    conn = _MemConn(fleets=[])
    main.app.state.pool = _MemPool(conn)
    # 不進入 lifespan(避免連真 DB);直接注入記憶體 pool
    return TestClient(main.app), conn


def _tok(role: str, org: str | None) -> dict:
    claims: dict = {"sub": f"{role}-{org}", "role": role}
    if org is not None:
        claims["org"] = org
    token = jwt.encode(claims, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_endpoint_create_binds_caller_org(client):
    c, conn = client
    # viewer 不能建(需 operator);用 operator。client 無從指定 org。
    r = c.post("/api/v1/fleets", json={"name": "acme-fleet"}, headers=_tok("operator", "acme"))
    assert r.status_code == 201
    assert r.json()["org_id"] == "acme"
    assert conn.fleets[0]["org_id"] == "acme"


def test_endpoint_cross_org_isolation(client):
    c, conn = client
    # org A 建一台機隊
    ra = c.post("/api/v1/fleets", json={"name": "a"}, headers=_tok("operator", "orgA"))
    a_id = ra.json()["id"]
    # org B 建一台
    c.post("/api/v1/fleets", json={"name": "b"}, headers=_tok("operator", "orgB"))

    # org B 的 viewer:list 只見自己的,不含 A
    lb = c.get("/api/v1/fleets", headers=_tok("viewer", "orgB"))
    names = [f["org_id"] for f in lb.json()]
    assert names == ["orgB"]
    assert lb.headers["X-Total-Count"] == "1"

    # org B 的 viewer 取 A 的機隊 → 404(不洩漏存在性)
    gb = c.get(f"/api/v1/fleets/{a_id}", headers=_tok("viewer", "orgB"))
    assert gb.status_code == 404

    # org A 的 viewer 取自己的 → 200
    ga = c.get(f"/api/v1/fleets/{a_id}", headers=_tok("viewer", "orgA"))
    assert ga.status_code == 200 and ga.json()["org_id"] == "orgA"


def test_endpoint_admin_sees_all_and_can_filter(client):
    c, conn = client
    c.post("/api/v1/fleets", json={"name": "a"}, headers=_tok("operator", "orgA"))
    c.post("/api/v1/fleets", json={"name": "b"}, headers=_tok("operator", "orgB"))
    # admin 無 ?org → 全部
    la = c.get("/api/v1/fleets", headers=_tok("admin", "plat"))
    assert {f["org_id"] for f in la.json()} == {"orgA", "orgB"}
    # admin ?org=orgA → 僅 orgA
    lf = c.get("/api/v1/fleets", params={"org": "orgA"}, headers=_tok("admin", "plat"))
    assert {f["org_id"] for f in lf.json()} == {"orgA"}
    # admin 可跨 org 取任一機隊
    a_id = [f["id"] for f in la.json() if f["org_id"] == "orgA"][0]
    assert c.get(f"/api/v1/fleets/{a_id}", headers=_tok("admin", "plat")).status_code == 200


def test_endpoint_non_admin_org_query_ignored(client):
    c, conn = client
    c.post("/api/v1/fleets", json={"name": "a"}, headers=_tok("operator", "orgA"))
    c.post("/api/v1/fleets", json={"name": "b"}, headers=_tok("operator", "orgB"))
    # orgB viewer 嘗試 ?org=orgA 越權 → 被忽略,仍只見自己的
    lb = c.get("/api/v1/fleets", params={"org": "orgA"}, headers=_tok("viewer", "orgB"))
    assert {f["org_id"] for f in lb.json()} == {"orgB"}


def test_endpoint_dev_mode_default_org(monkeypatch):
    # 認證停用(dev/cloud-smoke):無 token 亦放行,資源落 default org
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    conn = _MemConn(fleets=[])
    main.app.state.pool = _MemPool(conn)
    c = TestClient(main.app)
    r = c.post("/api/v1/fleets", json={"name": "dev"})
    assert r.status_code == 201 and r.json()["org_id"] == DEV_ORG
    # dev = admin → 看得到(全部)
    assert c.get("/api/v1/fleets").status_code == 200

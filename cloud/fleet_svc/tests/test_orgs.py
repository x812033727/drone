"""租戶(org)註冊表 + 每租戶配額(計費控制面)。四層驗證,皆不碰真 DB:

1. build_org_patch 純函式:PATCH 欄位映射(含 max_* 顯式清 NULL、enum→值、索引偏移)。
2. limits.effective_limit / enforce_org_active 單元:覆寫→plan→env 解析;suspended 擋寫。
3. repo 層 SQL 契約:create/get/list/count/update 綁正確參數。
4. 端點層(TestClient + 記憶體連線):admin CRUD、非 admin 403、per-org 配額覆寫生效(某 org
   低上限→402,他 org 不受影響)、suspended 寫入被擋、usage 彙總、dev 模式不阻塞。
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from uuid import uuid4

import asyncpg
import jwt
import pytest
from fastapi.testclient import TestClient
from fleet_svc import auth, limits, main, repo
from fleet_svc.limits import RateLimiter, effective_limit, enforce_org_active
from fleet_svc.models import Org, OrgCreate, OrgPlan, OrgStatus, OrgUpdate
from fleet_svc.repo import build_org_patch

# ----------------------------------------------------------------------------
# 1. build_org_patch 純函式
# ----------------------------------------------------------------------------


def test_org_patch_empty():
    clause, values = build_org_patch(OrgUpdate())
    assert clause == "" and values == []


def test_org_patch_name_and_plan_enum_to_value():
    clause, values = build_org_patch(OrgUpdate(name="Acme", plan=OrgPlan.pro))
    assert clause == "name = $1, plan = $2"
    assert values == ["Acme", "pro"]  # enum → 其字串值


def test_org_patch_explicit_null_clears_override():
    # 顯式帶 max_fleets=None(清除覆寫)須被納入 SET(→ NULL);白名單順序 max_devices 先於 max_fleets
    clause, values = build_org_patch(OrgUpdate(max_fleets=None, max_devices=5))
    assert clause == "max_devices = $1, max_fleets = $2"
    assert values == [5, None]


def test_org_patch_null_via_model_validate_included():
    # 以 dict 明確帶 max_fleets=None(exclude_unset 保留)→ SET = NULL;順序 status 先於 max_fleets
    upd = OrgUpdate.model_validate({"max_fleets": None, "status": "suspended"})
    clause, values = build_org_patch(upd)
    assert clause == "status = $1, max_fleets = $2"
    assert values == ["suspended", None]


def test_org_patch_start_index_offset():
    clause, values = build_org_patch(OrgUpdate(name="x"), start_index=7)
    assert clause == "name = $7" and values == ["x"]


# ----------------------------------------------------------------------------
# 2. effective_limit / enforce_org_active 單元
# ----------------------------------------------------------------------------


def _org(**kw) -> Org:
    base = dict(
        org_id="o", name="o", plan=OrgPlan.free, status=OrgStatus.active,
        max_devices=None, max_fleets=None,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    base.update(kw)
    return Org(**base)


def test_effective_limit_none_org_falls_back_to_env(monkeypatch):
    monkeypatch.setattr(limits, "QUOTA_MAX_FLEETS", 777)
    assert effective_limit(None, "max_fleets") == 777


def test_effective_limit_plan_default():
    o = _org(plan=OrgPlan.free)
    assert effective_limit(o, "max_fleets") == limits.PLAN_QUOTAS["free"]["max_fleets"]
    assert effective_limit(o, "max_devices") == limits.PLAN_QUOTAS["free"]["max_devices"]
    pro = _org(plan=OrgPlan.pro)
    assert effective_limit(pro, "max_devices") == limits.PLAN_QUOTAS["pro"]["max_devices"]


def test_effective_limit_override_beats_plan():
    o = _org(plan=OrgPlan.free, max_fleets=42)
    assert effective_limit(o, "max_fleets") == 42
    # 未覆寫的資源仍走 plan 預設
    assert effective_limit(o, "max_devices") == limits.PLAN_QUOTAS["free"]["max_devices"]


def _p(admin: bool, org: str = "o"):
    return auth.Principal(claims={}, role="admin" if admin else "operator", org=org, is_admin=admin)


def test_enforce_org_active_blocks_suspended_non_admin():
    with pytest.raises(Exception) as ei:
        enforce_org_active(_p(False), _org(status=OrgStatus.suspended))
    assert ei.value.status_code == 403


def test_enforce_org_active_admin_exempt():
    enforce_org_active(_p(True), _org(status=OrgStatus.suspended))  # 不拋


def test_enforce_org_active_none_and_active_pass():
    enforce_org_active(_p(False), None)  # 未註冊不阻擋
    enforce_org_active(_p(False), _org(status=OrgStatus.active))


# ----------------------------------------------------------------------------
# 3. repo 層 SQL 契約(stub 連線記錄 SQL/參數)
# ----------------------------------------------------------------------------


class _StubConn:
    def __init__(self, row: dict | None = None, val: int = 0) -> None:
        self.fetch_calls: list[tuple] = []
        self.fetchrow_calls: list[tuple] = []
        self.fetchval_calls: list[tuple] = []
        self._row = row
        self._val = val

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        return [self._row] if self._row else []

    async def fetchrow(self, sql, *args):
        self.fetchrow_calls.append((sql, args))
        return self._row

    async def fetchval(self, sql, *args):
        self.fetchval_calls.append((sql, args))
        return self._val


_ORG_ROW = {
    "org_id": "acme", "name": "Acme", "plan": "pro", "status": "active",
    "max_devices": None, "max_fleets": None,
    "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
}


def test_repo_create_org_binds_all_columns():
    conn = _StubConn(row=_ORG_ROW)
    body = OrgCreate(org_id="acme", name="Acme", plan=OrgPlan.pro, max_devices=9)
    asyncio.run(repo.create_org(conn, body))
    sql, args = conn.fetchrow_calls[0]
    assert "INSERT INTO fleet.org" in sql
    assert args == ("acme", "Acme", "pro", "active", 9, None)


def test_repo_get_org_scoped_by_id():
    conn = _StubConn(row=_ORG_ROW)
    asyncio.run(repo.get_org(conn, "acme"))
    sql, args = conn.fetchrow_calls[0]
    assert "WHERE org_id = $1" in sql and args == ("acme",)


def test_repo_list_orgs_status_filter_and_paging():
    conn = _StubConn(row=_ORG_ROW)
    asyncio.run(repo.list_orgs(conn, status="active", limit=25, offset=50))
    sql, args = conn.fetch_calls[0]
    assert "status = $1" in sql and "LIMIT $2 OFFSET $3" in sql
    assert args == ("active", 25, 50)


def test_repo_count_orgs():
    conn = _StubConn(val=3)
    assert asyncio.run(repo.count_orgs(conn)) == 3
    assert "count(*) FROM fleet.org" in conn.fetchval_calls[0][0]


def test_repo_update_org_sets_updated_at_and_binds_id_last():
    conn = _StubConn(row=_ORG_ROW)
    asyncio.run(repo.update_org(conn, "acme", OrgUpdate(status=OrgStatus.suspended)))
    sql, args = conn.fetchrow_calls[0]
    assert "UPDATE fleet.org SET status = $1, updated_at = now() WHERE org_id = $2" in sql
    assert args == ("suspended", "acme")


# ----------------------------------------------------------------------------
# 4. 端點層:記憶體連線 + TestClient
# ----------------------------------------------------------------------------

SECRET = "test-secret-key-orgs-tenant-mgmt-0123456789ab"


class _MemConn:
    """支援 fleet.org + fleet.fleet + fleet.device + usage_counter 的記憶體連線。"""

    def __init__(self) -> None:
        self.orgs: dict[str, dict] = {}
        self.fleets: list[dict] = []
        self.devices: list[dict] = []
        self.usage: dict[tuple, int] = {}

    async def fetchval(self, sql, *args):
        if "count(*) FROM fleet.org" in sql:
            rows = list(self.orgs.values())
            if "status = $1" in sql:
                rows = [r for r in rows if r["status"] == args[0]]
            return len(rows)
        if "count(*) FROM fleet.fleet" in sql:
            rows = self.fleets
            if "org_id = $1" in sql:
                rows = [r for r in rows if r["org_id"] == args[0]]
            return len(rows)
        if "count(*) FROM fleet.device" in sql:
            rows = self.devices
            if "org_id = $1" in sql:
                rows = [r for r in rows if r["org_id"] == args[0]]
            return len(rows)
        return 0

    async def fetch(self, sql, *args):
        if "FROM fleet.org" in sql:  # list_orgs
            rows = sorted(self.orgs.values(), key=lambda r: r["org_id"])
            if "status = $1" in sql:
                rows = [r for r in rows if r["status"] == args[0]]
            return rows
        if "FROM fleet.usage_counter" in sql and "sum(count)" in sql:
            org = args[0]
            agg: dict[str, int] = {}
            for (o, m, _p), c in self.usage.items():
                if o == org:
                    agg[m] = agg.get(m, 0) + c
            return [{"metric": m, "total": c} for m, c in agg.items()]
        if "FROM fleet.usage_counter" in sql:
            org, period = args[0], args[1]
            return [
                {"metric": m, "count": c}
                for (o, m, p), c in self.usage.items()
                if o == org and p == period
            ]
        return []

    async def fetchrow(self, sql, *args):
        if "INSERT INTO fleet.org" in sql:
            org_id = args[0]
            if org_id in self.orgs:
                raise asyncpg.UniqueViolationError(f"dup org {org_id}")
            now = datetime.now(timezone.utc)
            row = {
                "org_id": args[0], "name": args[1], "plan": args[2], "status": args[3],
                "max_devices": args[4], "max_fleets": args[5],
                "created_at": now, "updated_at": now,
            }
            self.orgs[org_id] = row
            return row
        if "SELECT" in sql and "FROM fleet.org WHERE org_id = $1" in sql:
            return self.orgs.get(args[0])
        if "UPDATE fleet.org SET" in sql:
            org_id = args[-1]
            row = self.orgs.get(org_id)
            if row is None:
                return None
            # 解析 SET 子句的 `col = $n`(updated_at = now() 不帶 $ 不匹配)
            set_part = sql.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
            for col, idx in re.findall(r"(\w+) = \$(\d+)", set_part):
                row[col] = args[int(idx) - 1]
            row["updated_at"] = datetime.now(timezone.utc)
            return row
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
    monkeypatch.setattr(limits, "write_limiter", RateLimiter(rate_per_min=6000))
    conn = _MemConn()
    main.app.state.pool = _MemPool(conn)
    return TestClient(main.app), conn


def _tok(role: str, org: str | None) -> dict:
    claims: dict = {"sub": f"{role}-{org}", "role": role}
    if org is not None:
        claims["org"] = org
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


def _mk_org(c, org_id: str, admin_org="plat", **body):
    payload = {"org_id": org_id, "name": body.pop("name", org_id), **body}
    return c.post("/api/v1/orgs", json=payload, headers=_tok("admin", admin_org))


# ---- admin CRUD ----


def test_admin_create_list_get_patch_org(client):
    c, conn = client
    r = _mk_org(c, "acme", name="Acme", plan="pro")
    assert r.status_code == 201
    body = r.json()
    assert body["org_id"] == "acme" and body["plan"] == "pro" and body["status"] == "active"

    # 重複 → 409
    assert _mk_org(c, "acme").status_code == 409

    # list + X-Total-Count
    lr = c.get("/api/v1/orgs", headers=_tok("admin", "plat"))
    assert lr.status_code == 200
    assert lr.headers["X-Total-Count"] == "1"
    assert [o["org_id"] for o in lr.json()] == ["acme"]

    # get 單一
    gr = c.get("/api/v1/orgs/acme", headers=_tok("admin", "plat"))
    assert gr.status_code == 200 and gr.json()["name"] == "Acme"
    assert c.get("/api/v1/orgs/nope", headers=_tok("admin", "plat")).status_code == 404

    # patch plan + status
    pr = c.patch(
        "/api/v1/orgs/acme",
        json={"plan": "enterprise", "status": "suspended"},
        headers=_tok("admin", "plat"),
    )
    assert pr.status_code == 200
    assert pr.json()["plan"] == "enterprise" and pr.json()["status"] == "suspended"
    assert c.patch("/api/v1/orgs/nope", json={"name": "x"},
                   headers=_tok("admin", "plat")).status_code == 404


def test_list_orgs_status_filter(client):
    c, conn = client
    _mk_org(c, "a", status="active")
    _mk_org(c, "s", status="suspended")
    r = c.get("/api/v1/orgs", params={"status": "suspended"}, headers=_tok("admin", "plat"))
    assert [o["org_id"] for o in r.json()] == ["s"]
    assert r.headers["X-Total-Count"] == "1"


# ---- 非 admin 不可管理 org(403)----


@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_non_admin_cannot_manage_orgs(client, role):
    c, conn = client
    assert c.post("/api/v1/orgs", json={"org_id": "x", "name": "x"},
                  headers=_tok(role, "x")).status_code == 403
    assert c.get("/api/v1/orgs", headers=_tok(role, "x")).status_code == 403
    assert c.get("/api/v1/orgs/x", headers=_tok(role, "x")).status_code == 403
    assert c.patch("/api/v1/orgs/x", json={"name": "y"},
                   headers=_tok(role, "x")).status_code == 403
    assert c.get("/api/v1/orgs/x/usage", headers=_tok(role, "x")).status_code == 403


# ---- per-org 配額覆寫生效 ----


def test_per_org_quota_override_isolated(client):
    c, conn = client
    # small 租戶覆寫 max_fleets=1;big 租戶不設(未註冊 → env 全域預設,寬鬆)
    assert _mk_org(c, "small", max_fleets=1).status_code == 201
    # small:第 1 個 OK,第 2 個 402
    assert c.post("/api/v1/fleets", json={"name": "f1"},
                  headers=_tok("operator", "small")).status_code == 201
    r = c.post("/api/v1/fleets", json={"name": "f2"}, headers=_tok("operator", "small"))
    assert r.status_code == 402
    # big 不受影響(env 預設寬鬆)
    for i in range(3):
        assert c.post("/api/v1/fleets", json={"name": f"b{i}"},
                      headers=_tok("operator", "big")).status_code == 201


def test_per_org_plan_default_quota(client, monkeypatch):
    c, conn = client
    # free 方案 max_devices 預設小;設為 1 以確定性驗證 plan 預設(非覆寫)生效
    monkeypatch.setitem(limits.PLAN_QUOTAS, "free", {"max_devices": 1, "max_fleets": 1})
    assert _mk_org(c, "trial", plan="free").status_code == 201
    assert c.post("/api/v1/devices", json={"serial": "S1"},
                  headers=_tok("operator", "trial")).status_code == 201
    assert c.post("/api/v1/devices", json={"serial": "S2"},
                  headers=_tok("operator", "trial")).status_code == 402


# ---- suspended 寫入被擋 ----


def test_suspended_org_writes_blocked(client):
    c, conn = client
    assert _mk_org(c, "acme", max_fleets=100).status_code == 201
    # active 時可寫
    assert c.post("/api/v1/fleets", json={"name": "ok"},
                  headers=_tok("operator", "acme")).status_code == 201
    # 停用後寫入被擋(403);讀取仍可
    assert c.patch("/api/v1/orgs/acme", json={"status": "suspended"},
                   headers=_tok("admin", "plat")).status_code == 200
    assert c.post("/api/v1/fleets", json={"name": "no"},
                  headers=_tok("operator", "acme")).status_code == 403
    assert c.post("/api/v1/devices", json={"serial": "D1"},
                  headers=_tok("operator", "acme")).status_code == 403
    assert c.get("/api/v1/fleets", headers=_tok("viewer", "acme")).status_code == 200


def test_suspended_admin_still_writes(client):
    c, conn = client
    assert _mk_org(c, "acme", status="suspended").status_code == 201
    # admin(平台)豁免 suspended
    assert c.post("/api/v1/fleets", json={"name": "x"},
                  headers=_tok("admin", "plat")).status_code == 201


# ---- usage 彙總 ----


def test_org_usage_summary(client):
    c, conn = client
    assert _mk_org(c, "acme", max_fleets=99).status_code == 201
    c.post("/api/v1/fleets", json={"name": "f1"}, headers=_tok("operator", "acme"))
    c.post("/api/v1/fleets", json={"name": "f2"}, headers=_tok("operator", "acme"))
    r = c.get("/api/v1/orgs/acme/usage", headers=_tok("admin", "plat"))
    assert r.status_code == 200
    b = r.json()
    assert b["org_id"] == "acme"
    assert b["counters"]["fleet_created"] == 2
    assert b["totals"]["fleet_created"] == 2
    assert b["resources"]["fleets"] == 2
    assert b["limits"]["max_fleets"] == 99  # 覆寫值
    # 未註冊 org 的 usage → 404
    assert c.get("/api/v1/orgs/ghost/usage", headers=_tok("admin", "plat")).status_code == 404


# ---- dev 模式不阻塞 ----


def test_dev_mode_org_management_and_writes(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    monkeypatch.setattr(limits, "write_limiter", RateLimiter(rate_per_min=6000))
    conn = _MemConn()
    main.app.state.pool = _MemPool(conn)
    c = TestClient(main.app)
    # dev 模式 = admin:可建 org、可無限寫(不受 suspended/配額約束)
    r = c.post("/api/v1/orgs", json={"org_id": "d", "name": "d", "status": "suspended"})
    assert r.status_code == 201
    assert c.get("/api/v1/orgs").status_code == 200
    for i in range(3):
        assert c.post("/api/v1/fleets", json={"name": f"d{i}"}).status_code == 201

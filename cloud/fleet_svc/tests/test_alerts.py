"""告警閉環查詢(GET /api/v1/alerts)+ 多租戶隔離(G11)。三層,皆不碰真 DB:

1. repo 層 SQL 契約:非 admin join fleet.device 以 org 過濾;kind 過濾;分頁綁定正確。
2. row 映射:jsonb detail(asyncpg 回字串)轉回 dict。
3. 端點層(TestClient + 記憶體連線):org A 看不到 org B 裝置的告警;admin 看全部;
   dev 模式(認證停用)= admin 看全部(cloud-smoke 放行)。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from fleet_svc import auth, main, repo


# ----------------------------------------------------------------------------
# 1. repo 層:SQL 契約
# ----------------------------------------------------------------------------
class _StubConn:
    def __init__(self, rows: list | None = None, val: int = 0) -> None:
        self.fetch_calls: list[tuple] = []
        self.fetchval_calls: list[tuple] = []
        self._rows = rows or []
        self._val = val

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        return self._rows

    async def fetchval(self, sql, *args):
        self.fetchval_calls.append((sql, args))
        return self._val


def test_list_alerts_non_admin_joins_device_and_filters_org():
    conn = _StubConn()
    asyncio.run(repo.list_alerts(conn, org="acme", limit=10, offset=5))
    sql, args = conn.fetch_calls[0]
    assert "FROM device_alerts a" in sql
    assert "JOIN fleet.device d ON d.serial = a.drone_id" in sql
    assert "d.org_id = $1" in sql
    assert "LIMIT $2 OFFSET $3" in sql
    assert args == ("acme", 10, 5)


def test_list_alerts_admin_no_join_no_filter():
    conn = _StubConn()
    asyncio.run(repo.list_alerts(conn, org=None))
    sql, args = conn.fetch_calls[0]
    assert "JOIN fleet.device" not in sql
    assert "WHERE" not in sql
    assert args == (100, 0)


def test_list_alerts_kind_filter_combines_with_org():
    conn = _StubConn()
    asyncio.run(repo.list_alerts(conn, org="acme", kind="ota", limit=20, offset=0))
    sql, args = conn.fetch_calls[0]
    assert "d.org_id = $1" in sql and "a.kind = $2" in sql
    assert "LIMIT $3 OFFSET $4" in sql
    assert args == ("acme", "ota", 20, 0)


def test_list_alerts_admin_kind_only():
    conn = _StubConn()
    asyncio.run(repo.list_alerts(conn, org=None, kind="cert"))
    sql, args = conn.fetch_calls[0]
    assert "JOIN fleet.device" not in sql
    assert "a.kind = $1" in sql
    assert args == ("cert", 100, 0)


def test_count_alerts_org_scoped():
    conn = _StubConn(val=3)
    n = asyncio.run(repo.count_alerts(conn, org="acme", kind="ota"))
    sql, args = conn.fetchval_calls[0]
    assert "SELECT count(*)" in sql and "JOIN fleet.device" in sql
    assert "d.org_id = $1" in sql and "a.kind = $2" in sql
    assert args == ("acme", "ota") and n == 3


def test_alert_row_maps_jsonb_detail_string_to_dict():
    row = {
        "time": datetime.now(timezone.utc),
        "drone_id": "dev-1",
        "kind": "cert",
        "summary": "cert_expiring",
        "detail": json.dumps({"days_remaining": 5.0}),  # asyncpg 回 jsonb 為字串
    }
    entry = repo._alert(row)
    assert entry.detail == {"days_remaining": 5.0}
    assert entry.kind == "cert" and entry.drone_id == "dev-1"


def test_alert_row_null_detail_defaults_empty():
    row = {
        "time": datetime.now(timezone.utc),
        "drone_id": "dev-1",
        "kind": "ota",
        "summary": "COMPLETED",
        "detail": None,
    }
    assert repo._alert(row).detail == {}


# ----------------------------------------------------------------------------
# 3. 端點層:記憶體連線 + TestClient
# ----------------------------------------------------------------------------
class _MemConn:
    """僅支援 device_alerts 查詢的記憶體連線(org join 過濾以 Python 忠實模擬)。

    alerts:list of {drone_id, org, kind, summary, detail(dict), time}。
    """

    def __init__(self, alerts: list[dict]) -> None:
        self.alerts = alerts

    def _filtered(self, sql, args):
        rows = list(self.alerts)
        i = 0
        if "d.org_id = $1" in sql:
            rows = [r for r in rows if r["org"] == args[i]]
            i += 1
        if "a.kind = $" in sql:
            rows = [r for r in rows if r["kind"] == args[i]]
            i += 1
        return rows, i

    async def fetchval(self, sql, *args):
        if "count(*)" in sql and "device_alerts" in sql:
            rows, _ = self._filtered(sql, args)
            return len(rows)
        return 0

    async def fetch(self, sql, *args):
        if "FROM device_alerts" in sql:
            rows, i = self._filtered(sql, args)
            limit, offset = args[i], args[i + 1]
            rows = sorted(rows, key=lambda r: r["time"], reverse=True)[offset : offset + limit]
            return [
                {
                    "time": r["time"],
                    "drone_id": r["drone_id"],
                    "kind": r["kind"],
                    "summary": r["summary"],
                    "detail": json.dumps(r["detail"]),
                }
                for r in rows
            ]
        return []


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


SECRET = "test-secret-key-alerts-isolation-0123456789"


def _alerts_seed() -> list[dict]:
    t0 = datetime(2026, 7, 13, tzinfo=timezone.utc)
    return [
        {"drone_id": "A-1", "org": "orgA", "kind": "cert", "summary": "cert_expiring",
         "detail": {"days_remaining": 10.0}, "time": t0},
        {"drone_id": "A-1", "org": "orgA", "kind": "ota", "summary": "COMPLETED",
         "detail": {"update_id": "u1"}, "time": t0 + timedelta(minutes=1)},
        {"drone_id": "B-1", "org": "orgB", "kind": "ota", "summary": "DOWNLOADING",
         "detail": {"update_id": "u2"}, "time": t0 + timedelta(minutes=2)},
    ]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "JWT_SECRET", SECRET)
    monkeypatch.setattr(auth, "_jwks_client", None)
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    conn = _MemConn(_alerts_seed())
    main.app.state.pool = _MemPool(conn)
    return TestClient(main.app)


def _tok(role: str, org: str) -> dict:
    claims = {"sub": f"{role}-{org}", "role": role, "org": org}
    token = jwt.encode(claims, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_alerts_org_isolation(client):
    # orgB viewer 只見自己裝置(B-1)的告警,不含 orgA
    r = client.get("/api/v1/alerts", headers=_tok("viewer", "orgB"))
    assert r.status_code == 200
    drones = {a["drone_id"] for a in r.json()}
    assert drones == {"B-1"}
    assert r.headers["X-Total-Count"] == "1"


def test_alerts_non_admin_org_query_ignored(client):
    # orgB viewer 嘗試 ?org=orgA 越權 → 忽略,仍只見自己的
    r = client.get("/api/v1/alerts", params={"org": "orgA"}, headers=_tok("viewer", "orgB"))
    assert {a["drone_id"] for a in r.json()} == {"B-1"}


def test_alerts_admin_sees_all_and_kind_filter(client):
    la = client.get("/api/v1/alerts", headers=_tok("admin", "plat"))
    assert {a["drone_id"] for a in la.json()} == {"A-1", "B-1"}
    # kind 過濾:只看 ota
    lo = client.get("/api/v1/alerts", params={"kind": "ota"}, headers=_tok("admin", "plat"))
    assert all(a["kind"] == "ota" for a in lo.json())
    assert {a["summary"] for a in lo.json()} == {"COMPLETED", "DOWNLOADING"}


def test_alerts_detail_deserialized(client):
    # admin 指定 orgA:detail(jsonb)還原為 dict
    la = client.get("/api/v1/alerts", params={"org": "orgA"}, headers=_tok("admin", "plat"))
    certs = [a for a in la.json() if a["kind"] == "cert"]
    assert certs and certs[0]["detail"] == {"days_remaining": 10.0}


def test_alerts_dev_mode_sees_all(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    main.app.state.pool = _MemPool(_MemConn(_alerts_seed()))
    c = TestClient(main.app)
    r = c.get("/api/v1/alerts")  # 無 token,dev=admin 看全部
    assert r.status_code == 200
    assert {a["drone_id"] for a in r.json()} == {"A-1", "B-1"}

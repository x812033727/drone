"""審計軌跡(G14):helper 寫入語義、best-effort、稽核查詢 SQL/分頁、admin RBAC 閘。

不碰真 DB:以 stub 連線記錄 SQL/參數。RBAC 直接驅動 audit 端點掛的 require_role 依賴閘。
"""

import asyncio
import json
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from mission_svc import audit, main, repo


class _StubConn:
    def __init__(self, execute_raises: Exception | None = None) -> None:
        self.execute_calls: list[tuple] = []
        self.fetch_calls: list[tuple] = []
        self.fetchval_calls: list[tuple] = []
        self._execute_raises = execute_raises

    async def execute(self, sql: str, *args):
        self.execute_calls.append((sql, args))
        if self._execute_raises is not None:
            raise self._execute_raises
        return "INSERT 0 1"

    async def fetch(self, sql: str, *args):
        self.fetch_calls.append((sql, args))
        return []

    async def fetchval(self, sql: str, *args):
        self.fetchval_calls.append((sql, args))
        return 0


# ---- actor 推導 ----
def test_actor_of_dev_mode():
    assert audit.actor_of({"sub": "dev", "roles": ["admin"]}) == ("dev", "admin")


def test_actor_of_anonymous_when_no_identity():
    assert audit.actor_of({}) == ("anonymous", None)


# ---- 寫入語義 ----
def test_record_inserts_row_with_fields():
    conn = _StubConn()
    rid = uuid4()
    asyncio.run(
        audit.record(
            conn,
            claims={"sub": "op1", "role": "operator"},
            action="dispatch",
            resource_type="mission",
            resource_id=rid,
            details={"mission_id": "m-abc"},
        )
    )
    assert len(conn.execute_calls) == 1
    sql, args = conn.execute_calls[0]
    assert "INSERT INTO mission.audit_log" in sql
    assert args[0] == "op1"
    assert args[1] == "operator"
    assert args[2] == "dispatch"
    assert args[3] == "mission"
    assert args[4] == str(rid)
    assert json.loads(args[5]) == {"mission_id": "m-abc"}
    assert args[6] is None


def test_record_best_effort_swallows_db_error():
    conn = _StubConn(execute_raises=RuntimeError("db boom"))
    asyncio.run(
        audit.record(
            conn,
            claims={"sub": "op1", "role": "operator"},
            action="command",
            resource_type="mission",
            resource_id=uuid4(),
            details={"command": "pause"},
        )
    )
    assert len(conn.execute_calls) == 1


# ---- 稽核查詢 SQL / 分頁 / details 反序列化 ----
def test_list_audit_defaults_and_order():
    conn = _StubConn()
    asyncio.run(repo.list_audit(conn))
    sql, args = conn.fetch_calls[0]
    assert "FROM mission.audit_log" in sql
    assert "ORDER BY at DESC" in sql
    assert "LIMIT $1 OFFSET $2" in sql
    assert args == (100, 0)


def test_list_audit_resource_filter_shifts_indices():
    conn = _StubConn()
    asyncio.run(repo.list_audit(conn, resource_type="route", limit=10, offset=5))
    sql, args = conn.fetch_calls[0]
    assert "WHERE resource_type = $1" in sql
    assert "LIMIT $2 OFFSET $3" in sql
    assert args == ("route", 10, 5)


def test_count_audit_respects_filter():
    conn = _StubConn()
    asyncio.run(repo.count_audit(conn, resource_type="mission"))
    sql, args = conn.fetchval_calls[0]
    assert "count(*)" in sql
    assert "WHERE resource_type = $1" in sql
    assert args == ("mission",)


def test_audit_row_maps_jsonb_string_to_dict():
    import datetime as _dt

    row = {
        "id": 1,
        "at": _dt.datetime.now(_dt.timezone.utc),
        "actor": "dev",
        "role": "admin",
        "action": "dispatch",
        "resource_type": "mission",
        "resource_id": "m-abc",
        "details": '{"drone_id": "d-1"}',
        "source_ip": None,
    }
    entry = repo._audit(row)
    assert entry.details == {"drone_id": "d-1"}


# ---- admin RBAC 閘(audit 端點實掛的依賴)----
def _audit_gate():
    route = next(
        r for r in main.app.routes
        if getattr(r, "path", None) == "/api/v1/audit" and "GET" in getattr(r, "methods", set())
    )
    deps = route.dependant.dependencies
    assert len(deps) == 1, "audit 端點應只掛一個 admin 依賴閘"
    return deps[0].call


def _drive_gate(gate, token: str):
    cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return asyncio.run(gate(cred))


def test_audit_endpoint_admin_only(monkeypatch):
    from mission_svc import auth
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-key-audit-0123456789")
    monkeypatch.setattr(auth, "_jwks_client", None)
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    gate = _audit_gate()
    secret = "test-secret-key-audit-0123456789"

    for role in ("viewer", "operator"):
        tok = jwt.encode({"sub": "u", "role": role}, secret, algorithm="HS256")
        with pytest.raises(HTTPException) as ei:
            _drive_gate(gate, tok)
        assert ei.value.status_code == 403

    admin_tok = jwt.encode({"sub": "boss", "role": "admin"}, secret, algorithm="HS256")
    claims = _drive_gate(gate, admin_tok)
    assert claims["sub"] == "boss"

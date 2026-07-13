"""審計軌跡(G14):helper 寫入語義、best-effort、稽核查詢 SQL/分頁、admin RBAC 閘。

不碰真 DB:以 stub 連線記錄 SQL/參數(同 test_pagination 風格)。RBAC 直接驅動
audit 端點掛的 require_role 依賴閘(operator/viewer 被拒、admin 放行)。
"""

import asyncio
import json
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fleet_svc import audit, main, repo


class _StubConn:
    """記錄 execute/fetch/fetchval 的呼叫;execute 可設為拋錯以驗 best-effort。"""

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
    # dev 模式(認證停用)authorize 回 {"sub":"dev","roles":["admin"]}
    assert audit.actor_of({"sub": "dev", "roles": ["admin"]}) == ("dev", "admin")


def test_actor_of_operator_and_username_fallbacks():
    assert audit.actor_of({"sub": "u1", "role": "operator"}) == ("u1", "operator")
    assert audit.actor_of({"preferred_username": "bob", "roles": ["viewer"]}) == ("bob", "viewer")


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
            action="create",
            resource_type="device",
            resource_id=rid,
            details={"serial": "SN-1"},
        )
    )
    assert len(conn.execute_calls) == 1
    sql, args = conn.execute_calls[0]
    assert "INSERT INTO fleet.audit_log" in sql
    # (actor, role, action, resource_type, resource_id, details, source_ip)
    assert args[0] == "op1"
    assert args[1] == "operator"
    assert args[2] == "create"
    assert args[3] == "device"
    assert args[4] == str(rid)  # UUID 轉字串存
    assert json.loads(args[5]) == {"serial": "SN-1"}
    assert args[6] is None  # 無 request → source_ip 為空


def test_record_best_effort_swallows_db_error():
    # 審計寫入失敗不可外溢(主操作不受影響)
    conn = _StubConn(execute_raises=RuntimeError("db boom"))
    # 不應拋出
    asyncio.run(
        audit.record(
            conn,
            claims={"sub": "op1", "role": "operator"},
            action="delete",
            resource_type="device",
            resource_id=uuid4(),
        )
    )
    assert len(conn.execute_calls) == 1  # 嘗試過一次


# ---- 稽核查詢 SQL / 分頁 / details 反序列化 ----
def test_list_audit_defaults_and_order():
    conn = _StubConn()
    asyncio.run(repo.list_audit(conn))
    sql, args = conn.fetch_calls[0]
    assert "FROM fleet.audit_log" in sql
    assert "ORDER BY at DESC" in sql
    assert "LIMIT $1 OFFSET $2" in sql
    assert args == (100, 0)


def test_list_audit_resource_filter_shifts_indices():
    conn = _StubConn()
    asyncio.run(repo.list_audit(conn, resource_type="mission", limit=10, offset=5))
    sql, args = conn.fetch_calls[0]
    assert "WHERE resource_type = $1" in sql
    assert "LIMIT $2 OFFSET $3" in sql
    assert args == ("mission", 10, 5)


def test_count_audit_respects_filter():
    conn = _StubConn()
    asyncio.run(repo.count_audit(conn, resource_type="device"))
    sql, args = conn.fetchval_calls[0]
    assert "count(*)" in sql
    assert "WHERE resource_type = $1" in sql
    assert args == ("device",)


def test_audit_row_maps_jsonb_string_to_dict():
    row = {
        "id": 1,
        "at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        "actor": "dev",
        "role": "admin",
        "action": "create",
        "resource_type": "device",
        "resource_id": "SN-1",
        "details": '{"serial": "SN-1"}',  # asyncpg jsonb 以字串回傳
        "source_ip": None,
    }
    entry = repo._audit(row)
    assert entry.details == {"serial": "SN-1"}
    assert entry.actor == "dev"


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
    from fleet_svc import auth
    # 啟用認證(HS256),讓 require_role 真正驗角色
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret-key-audit-0123456789")
    monkeypatch.setattr(auth, "_jwks_client", None)
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    gate = _audit_gate()
    secret = "test-secret-key-audit-0123456789"

    # 非 admin 被拒(403)
    for role in ("viewer", "operator"):
        tok = jwt.encode({"sub": "u", "role": role}, secret, algorithm="HS256")
        with pytest.raises(HTTPException) as ei:
            _drive_gate(gate, tok)
        assert ei.value.status_code == 403

    # admin 放行,claims 帶回
    admin_tok = jwt.encode({"sub": "boss", "role": "admin"}, secret, algorithm="HS256")
    claims = _drive_gate(gate, admin_tok)
    assert claims["sub"] == "boss"

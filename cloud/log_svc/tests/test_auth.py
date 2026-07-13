"""JWT 認證/RBAC 測試:純邏輯(角色萃取/權級/HS256)+ 授權判定(dev 放行/401/403)。

授權判定測試以 monkeypatch 環境變數後 importlib.reload(log_svc.auth),
因為 AUTH_ENABLED / JWT_SECRET 等在 import 時求值(對齊 fleet-svc / mission-svc 設計)。
"""

import importlib

import jwt
import pytest
from fastapi import HTTPException

import log_svc.auth as auth


@pytest.fixture(autouse=True)
def _reset_auth_module():
    """每個測試後把 auth 模組還原成無環境變數的預設(dev)狀態,避免互相污染。"""
    yield
    for var in ("JWT_SECRET", "JWT_JWKS_URL", "JWT_ALGORITHM", "JWT_AUDIENCE", "JWT_ISSUER"):
        os_environ_pop(var)
    importlib.reload(auth)


def os_environ_pop(var: str) -> None:
    import os

    os.environ.pop(var, None)


# ---- 純邏輯(不依賴環境) ----

def test_extract_roles_single():
    assert auth.extract_roles({"role": "operator"}) == {"operator"}


def test_extract_roles_list_and_realm():
    assert auth.extract_roles({"roles": ["viewer", "admin", "bogus"]}) == {"viewer", "admin"}
    assert auth.extract_roles({"realm_access": {"roles": ["operator"]}}) == {"operator"}


def test_extract_roles_ignores_unknown():
    assert auth.extract_roles({"role": "superuser"}) == set()
    assert auth.extract_roles({}) == set()


def test_role_rank_ordering():
    assert auth.role_rank({"viewer"}) == 0
    assert auth.role_rank({"operator"}) == 1
    assert auth.role_rank({"admin"}) == 2
    assert auth.role_rank({"viewer", "admin"}) == 2  # 取最高
    assert auth.role_rank(set()) == -1


# ---- 授權判定:dev 模式放行 ----

def test_dev_mode_allows_without_token():
    """未設 JWT_SECRET/JWKS(cloud-smoke 情境)→ 放行為 admin,免帶 token。"""
    importlib.reload(auth)  # 確保無環境變數狀態
    assert auth.AUTH_ENABLED is False
    claims = auth.authorize_token(None, "operator")
    assert claims["roles"] == ["admin"]


# ---- 授權判定:設 JWT_SECRET 時未授權回 401/403 ----

def _reload_with_secret(monkeypatch, secret="unit-test-secret-key-0123456789abcdef"):
    monkeypatch.setenv("JWT_SECRET", secret)
    importlib.reload(auth)
    assert auth.AUTH_ENABLED is True
    return secret


def test_secret_mode_missing_token_401(monkeypatch):
    _reload_with_secret(monkeypatch)
    with pytest.raises(HTTPException) as ei:
        auth.authorize_token(None, "viewer")
    assert ei.value.status_code == 401


def test_secret_mode_invalid_token_401(monkeypatch):
    _reload_with_secret(monkeypatch)
    with pytest.raises(HTTPException) as ei:
        auth.authorize_token("not-a-jwt", "viewer")
    assert ei.value.status_code == 401


def test_secret_mode_insufficient_role_403(monkeypatch):
    secret = _reload_with_secret(monkeypatch)
    viewer_token = jwt.encode({"sub": "u1", "role": "viewer"}, secret, algorithm="HS256")
    with pytest.raises(HTTPException) as ei:
        auth.authorize_token(viewer_token, "operator")  # viewer < operator
    assert ei.value.status_code == 403


def test_secret_mode_sufficient_role_ok(monkeypatch):
    secret = _reload_with_secret(monkeypatch)
    op_token = jwt.encode({"sub": "u1", "role": "operator"}, secret, algorithm="HS256")
    claims = auth.authorize_token(op_token, "operator")
    assert claims["sub"] == "u1"
    # viewer 端點也允許 operator(權級足夠)
    assert auth.authorize_token(op_token, "viewer")["sub"] == "u1"

"""JWT 認證/RBAC 純邏輯測試(角色萃取、權級、HS256 解碼)。"""

import jwt
import pytest
from fleet_svc.auth import extract_roles, role_rank


def test_extract_roles_single():
    assert extract_roles({"role": "operator"}) == {"operator"}


def test_extract_roles_list_and_realm():
    assert extract_roles({"roles": ["viewer", "admin", "bogus"]}) == {"viewer", "admin"}
    assert extract_roles({"realm_access": {"roles": ["operator"]}}) == {"operator"}


def test_extract_roles_ignores_unknown():
    assert extract_roles({"role": "superuser"}) == set()
    assert extract_roles({}) == set()


def test_role_rank_ordering():
    assert role_rank({"viewer"}) == 0
    assert role_rank({"operator"}) == 1
    assert role_rank({"admin"}) == 2
    assert role_rank({"viewer", "admin"}) == 2  # 取最高
    assert role_rank(set()) == -1


def test_hs256_decode_roundtrip():
    # 驗證 pyjwt HS256 編解碼(_decode 在 JWT_SECRET 模式走此路徑)
    secret = "test-secret"
    token = jwt.encode({"sub": "u1", "role": "operator"}, secret, algorithm="HS256")
    claims = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_aud": False})
    assert claims["role"] == "operator"
    assert role_rank(extract_roles(claims)) == 1


def test_hs256_bad_secret_rejected():
    token = jwt.encode({"sub": "u1"}, "right-secret", algorithm="HS256")
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, "wrong-secret", algorithms=["HS256"], options={"verify_aud": False})

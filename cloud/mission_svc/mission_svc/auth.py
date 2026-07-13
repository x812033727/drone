"""JWT 認證 + RBAC(OIDC-ready)。fleet-svc / mission-svc 共用同一設計。

模式(依環境變數):
- JWT_JWKS_URL 設定 → 生產:RS256,經 JWKS 驗簽(外部 IdP / OIDC)。
- 否則 JWT_SECRET 設定 → 簡易/dev:HS256 對稱密鑰。
- 兩者皆未設 → **dev 模式:認證停用**(放行為 admin),啟動時警告。
  正式部署(Helm)必設其一,security.md §8 Phase 1 落地。

角色(claim `role` 字串 / `roles` 陣列 / Keycloak `realm_access.roles`):
viewer < operator < admin。讀取需 viewer,變更/派遣需 operator。

(cloud/common 抽出後兩服務共用此檔——屬 Wave 1 A1;現各服務自帶,同 migrate.py。)
"""

from __future__ import annotations

import logging
import os

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

log = logging.getLogger("mission_svc.auth")

# 空字串環境變數(compose ${VAR:-} 的預設)視為未設 → None
JWT_SECRET = os.environ.get("JWT_SECRET") or None
JWT_JWKS_URL = os.environ.get("JWT_JWKS_URL") or None
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM") or "HS256"
JWT_AUDIENCE = os.environ.get("JWT_AUDIENCE") or None
JWT_ISSUER = os.environ.get("JWT_ISSUER") or None
AUTH_ENABLED = bool(JWT_SECRET or JWT_JWKS_URL)

ROLE_ORDER = {"viewer": 0, "operator": 1, "admin": 2}

_bearer = HTTPBearer(auto_error=False)
_jwks_client = jwt.PyJWKClient(JWT_JWKS_URL) if JWT_JWKS_URL else None


def extract_roles(claims: dict) -> set[str]:
    """從 JWT claims 萃取角色(相容單一 role、roles 陣列、Keycloak realm_access)。"""
    roles: set[str] = set()
    role = claims.get("role")
    if isinstance(role, str):
        roles.add(role)
    rs = claims.get("roles")
    if isinstance(rs, list):
        roles.update(r for r in rs if isinstance(r, str))
    realm = claims.get("realm_access")
    if isinstance(realm, dict) and isinstance(realm.get("roles"), list):
        roles.update(r for r in realm["roles"] if isinstance(r, str))
    return {r for r in roles if r in ROLE_ORDER}


def role_rank(roles: set[str]) -> int:
    """已知角色中的最高權級;無任何已知角色回 -1。"""
    return max((ROLE_ORDER[r] for r in roles), default=-1)


def _decode(token: str) -> dict:
    options = {"verify_aud": JWT_AUDIENCE is not None}
    if _jwks_client is not None:
        key = _jwks_client.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token, key, algorithms=["RS256"], audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER, options=options,
        )
    return jwt.decode(
        token, JWT_SECRET, algorithms=[JWT_ALGORITHM], audience=JWT_AUDIENCE,
        issuer=JWT_ISSUER, options=options,
    )


def require_role(min_role: str):
    """FastAPI 依賴工廠:要求 bearer token 帶 >= min_role 的角色。"""

    async def dependency(
        cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> dict:
        if not AUTH_ENABLED:
            return {"sub": "dev", "roles": ["admin"]}  # dev 模式放行
        if cred is None:
            raise HTTPException(status_code=401, detail="缺少 Bearer token")
        try:
            claims = _decode(cred.credentials)
        except jwt.PyJWTError as e:
            raise HTTPException(status_code=401, detail=f"token 無效:{e}")
        if role_rank(extract_roles(claims)) < ROLE_ORDER[min_role]:
            raise HTTPException(status_code=403, detail=f"需要 {min_role} 以上角色")
        return claims

    return dependency

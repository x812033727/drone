"""JWT 認證 + RBAC(OIDC-ready)。fleet-svc / mission-svc 共用同一設計。

模式(依環境變數):
- JWT_JWKS_URL 設定 → 生產:RS256,經 JWKS 驗簽(外部 IdP / OIDC)。
- 否則 JWT_SECRET 設定 → 簡易/dev:HS256 對稱密鑰。
- 兩者皆未設 → **dev 模式:認證停用**(放行為 admin),啟動時警告。
  正式部署(Helm)必設其一,security.md §8 Phase 1 落地。

角色(claim `role` 字串 / `roles` 陣列 / Keycloak `realm_access.roles`):
viewer < operator < admin。讀取需 viewer,變更/派遣需 operator。

多租戶隔離(G11):JWT 帶 `org`(或 `org_id`)claim 表示使用者所屬租戶。
- viewer/operator:只能看/改本 org 的資源(查詢一律 WHERE org_id = 本人 org)。
- admin(平台管理):可跨 org——讀取不加 org 過濾(或以 ?org= 指定單一 org)。
- 建立資源時 org 一律取自呼叫者 claim,**不信任 client 傳入值**(防越權寫入他 org)。
- dev 模式(認證停用)claims 視為 admin + org=`default`,故 cloud-smoke 全放行不受影響。

(cloud/common 抽出後兩服務共用此檔——屬 Wave 1 A1;現各服務自帶,同 migrate.py。)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

log = logging.getLogger("fleet_svc.auth")

# dev 模式(認證停用)與無 org claim 時的預設租戶。真實部署每個 token 應帶自己的 org。
DEV_ORG = "default"

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


_RANK_TO_ROLE = {rank: name for name, rank in ROLE_ORDER.items()}


def highest_role(claims: dict) -> str | None:
    """claims 的最高角色名(viewer/operator/admin);無已知角色回 None。"""
    return _RANK_TO_ROLE.get(role_rank(extract_roles(claims)))


def extract_org(claims: dict) -> str | None:
    """從 JWT claims 萃取租戶識別。相容 `org` 與 `org_id`(top-level 字串)。

    找不到回 None(呼叫端據情境決定:寫入/讀取一律 fallback 到 DEV_ORG,
    確保無 org claim 的 token 只落在 default 租戶,絕不跨真實租戶。)
    """
    for key in ("org", "org_id"):
        v = claims.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


@dataclass(frozen=True)
class Principal:
    """一次請求的認證主體:claims 原文 + 推導出的角色/租戶/是否 admin。

    - org:呼叫者所屬租戶(寫入一律用此值,永不採信 client 傳入)。
    - is_admin:平台管理者,讀取可跨 org。
    """

    claims: dict
    role: str | None
    org: str
    is_admin: bool


def build_principal(claims: dict) -> Principal:
    rank = role_rank(extract_roles(claims))
    return Principal(
        claims=claims,
        role=_RANK_TO_ROLE.get(rank),
        org=extract_org(claims) or DEV_ORG,
        is_admin=rank >= ROLE_ORDER["admin"],
    )


def read_org(principal: Principal, requested: str | None = None) -> str | None:
    """算出讀取查詢要套用的 org 過濾值。

    - admin:回 requested(給定則限單一 org;None 則回 None = 看全部,不加 org 過濾)。
    - 非 admin:一律回本人 org(忽略 requested,防越權指定他 org)。
    """
    if principal.is_admin:
        return requested
    return principal.org


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


def authorize_token(token: str | None, min_role: str) -> dict:
    """驗證 raw token 字串並檢查角色。供 REST(Bearer)與 SSE(查詢參數)共用。

    EventSource 無法帶 Authorization header,故 SSE 端以查詢參數 token 走此函式。
    """
    if not AUTH_ENABLED:
        return {"sub": "dev", "roles": ["admin"], "org": DEV_ORG}  # dev 模式放行
    if not token:
        raise HTTPException(status_code=401, detail="缺少 token")
    try:
        claims = _decode(token)
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"token 無效:{e}")
    if role_rank(extract_roles(claims)) < ROLE_ORDER[min_role]:
        raise HTTPException(status_code=403, detail=f"需要 {min_role} 以上角色")
    return claims


def require_role(min_role: str):
    """FastAPI 依賴工廠:要求 bearer token 帶 >= min_role 的角色(回 claims)。"""

    async def dependency(
        cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> dict:
        return authorize_token(cred.credentials if cred else None, min_role)

    return dependency


def require_principal(min_role: str):
    """FastAPI 依賴工廠:驗角色後回 Principal(含租戶 org),供端點做 org 隔離。

    注入 Principal(而非只掛在 dependencies)不會增加 OpenAPI 參數,契約不變。
    """

    async def dependency(
        cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> Principal:
        claims = authorize_token(cred.credentials if cred else None, min_role)
        return build_principal(claims)

    return dependency

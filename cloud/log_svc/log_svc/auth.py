"""JWT 認證 + RBAC(OIDC-ready)執行期層。fleet-svc / mission-svc / log-svc 共用同一設計。

純邏輯(角色萃取、權級)已抽到 drone_common.auth(Wave 1 A1)。本檔保留**環境相依的
執行期層**:env 常數、_decode、authorize_token、require_role——因單元測試以 monkeypatch
本模組級全域(AUTH_ENABLED / JWT_SECRET / _jwks_client …)與 importlib.reload(本模組)
驗證,這些狀態必須留在被 patch/reload 的服務模組內,不可抽離。

模式(依環境變數):
- JWT_JWKS_URL 設定 → 生產:RS256,經 JWKS 驗簽(外部 IdP / OIDC)。
- 否則 JWT_SECRET 設定 → 簡易/dev:HS256 對稱密鑰。
- 兩者皆未設 → **dev 模式:認證停用**(放行為 admin),啟動時警告。
  正式部署(Helm)必設其一,security.md §8 Phase 1 落地。

角色(claim `role` 字串 / `roles` 陣列 / Keycloak `realm_access.roles`):
viewer < operator < admin。讀取需 viewer,上傳/寫入需 operator。
"""

from __future__ import annotations

import logging
import os

import jwt
from drone_common.auth import ROLE_ORDER, extract_roles, role_rank
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

log = logging.getLogger("log_svc.auth")

# 空字串環境變數(compose ${VAR:-} 的預設)視為未設 → None
JWT_SECRET = os.environ.get("JWT_SECRET") or None
JWT_JWKS_URL = os.environ.get("JWT_JWKS_URL") or None
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM") or "HS256"
JWT_AUDIENCE = os.environ.get("JWT_AUDIENCE") or None
JWT_ISSUER = os.environ.get("JWT_ISSUER") or None
AUTH_ENABLED = bool(JWT_SECRET or JWT_JWKS_URL)

_bearer = HTTPBearer(auto_error=False)
_jwks_client = jwt.PyJWKClient(JWT_JWKS_URL) if JWT_JWKS_URL else None


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
        return {"sub": "dev", "roles": ["admin"]}  # dev 模式放行
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
    """FastAPI 依賴工廠:要求 bearer token 帶 >= min_role 的角色。"""

    async def dependency(
        cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> dict:
        return authorize_token(cred.credentials if cred else None, min_role)

    return dependency


# 純邏輯自 drone_common.auth 再匯出,保留 `from log_svc.auth import ...` 既有路徑不變。
__all__ = [
    "AUTH_ENABLED",
    "ROLE_ORDER",
    "authorize_token",
    "extract_roles",
    "require_role",
    "role_rank",
]

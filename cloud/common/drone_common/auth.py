"""共用 JWT/RBAC 純邏輯(OIDC-ready)。fleet-svc / mission-svc / log-svc 共用同一設計。

**此模組只放與環境變數 / JWKS 執行期狀態無關的純函式**:角色萃取、權級、租戶(org)
隔離、Principal。各服務的 auth.py 仍保留自己的執行期層(env 常數、_bearer、
_jwks_client、_decode、authorize_token、require_role/principal)——因單元測試以
monkeypatch 服務模組的模組級全域(AUTH_ENABLED / JWT_SECRET / _jwks_client …)與
importlib.reload(服務模組)驗證,那些狀態必須留在被 patch/reload 的服務模組內;
抽離會使 patch 失效。故此處只抽「可安全共用、行為零改變」的純邏輯(Wave 1 A1 去重)。

角色(claim `role` 字串 / `roles` 陣列 / Keycloak `realm_access.roles`):
viewer < operator < admin。讀取需 viewer,變更/派遣需 operator。

多租戶隔離(G11):JWT 帶 `org`(或 `org_id`)claim 表示使用者所屬租戶。
- viewer/operator:只能看/改本 org 的資源(查詢一律 WHERE org_id = 本人 org)。
- admin(平台管理):可跨 org——讀取不加 org 過濾(或以 ?org= 指定單一 org)。
- 建立資源時 org 一律取自呼叫者 claim,**不信任 client 傳入值**(防越權寫入他 org)。
- dev 模式(認證停用)claims 視為 admin + org=`default`,故 cloud-smoke 全放行不受影響。
"""

from __future__ import annotations

from dataclasses import dataclass

# dev 模式(認證停用)與無 org claim 時的預設租戶。真實部署每個 token 應帶自己的 org。
DEV_ORG = "default"

ROLE_ORDER = {"viewer": 0, "operator": 1, "admin": 2}

_RANK_TO_ROLE = {rank: name for name, rank in ROLE_ORDER.items()}


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


__all__ = [
    "DEV_ORG",
    "ROLE_ORDER",
    "Principal",
    "build_principal",
    "extract_org",
    "extract_roles",
    "highest_role",
    "read_org",
    "role_rank",
]

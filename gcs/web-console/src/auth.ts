// 極簡 token 儲存(localStorage)。生產 OIDC 可換成 redirect 流程 + 靜默續期。
const KEY = "drone_token";

export function getToken(): string | null {
  return localStorage.getItem(KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(KEY);
}

// REST 401/403 → 需要(重新)認證
export class AuthError extends Error {}

// ---- 前端 RBAC gating ----
// 與後端 cloud/fleet_svc/fleet_svc/auth.py 的角色模型對齊:viewer < operator < admin。
// 這只是 UX 閘門(隱藏/停用寫入動作),真正授權仍由後端 JWT 驗簽 + RBAC 強制;
// 偽造前端角色只會被後端 403 擋下。

export type Role = "viewer" | "operator" | "admin";

const ROLE_ORDER: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };

function b64urlDecode(seg: string): string {
  const pad = seg.length % 4 === 0 ? "" : "=".repeat(4 - (seg.length % 4));
  const b64 = seg.replace(/-/g, "+").replace(/_/g, "/") + pad;
  return atob(b64);
}

// 解出 JWT payload(不驗簽——僅供 UI 判斷;信任邊界在後端)。
function decodeClaims(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  if (parts.length < 2) return null;
  try {
    return JSON.parse(b64urlDecode(parts[1])) as Record<string, unknown>;
  } catch {
    return null;
  }
}

// 從 claims 萃取角色(相容單一 role、roles 陣列、Keycloak realm_access.roles)。
function extractRoles(claims: Record<string, unknown>): Set<Role> {
  const roles = new Set<Role>();
  const add = (r: unknown) => {
    if (typeof r === "string" && r in ROLE_ORDER) roles.add(r as Role);
  };
  add(claims.role);
  if (Array.isArray(claims.roles)) claims.roles.forEach(add);
  const realm = claims.realm_access;
  if (realm && typeof realm === "object" && Array.isArray((realm as { roles?: unknown }).roles)) {
    (realm as { roles: unknown[] }).roles.forEach(add);
  }
  return roles;
}

// 目前 token 的最高權級;無 token 或無已知角色 → -1。
export function roleRank(): number {
  const token = getToken();
  if (!token) return -1;
  const claims = decodeClaims(token);
  if (!claims) return -1;
  const roles = extractRoles(claims);
  return Math.max(-1, ...[...roles].map((r) => ROLE_ORDER[r]));
}

// 目前 token 是否具備 >= min 的角色(供 UI 顯示/啟用寫入動作)。
export function hasRole(min: Role): boolean {
  return roleRank() >= ROLE_ORDER[min];
}

// 顯示用:目前最高角色名稱(認證停用/無角色時回 null)。
export function currentRoleLabel(): Role | null {
  const rank = roleRank();
  if (rank < 0) return null;
  return (Object.keys(ROLE_ORDER) as Role[]).find((r) => ROLE_ORDER[r] === rank) ?? null;
}

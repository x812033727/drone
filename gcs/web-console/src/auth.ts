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

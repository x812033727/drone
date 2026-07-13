// OIDC 授權碼 + PKCE 公開客戶端登入流程(SSO)。config 由 VITE_OIDC_* 提供;
// 未設則停用(退回貼 token)。取得的 id_token 交由既有 auth/api 使用
// (fleet-svc 以 JWT_JWKS_URL 對同一 IdP 的 JWKS 驗簽)。

const CFG = {
  authUrl: import.meta.env.VITE_OIDC_AUTH_URL,
  tokenUrl: import.meta.env.VITE_OIDC_TOKEN_URL,
  clientId: import.meta.env.VITE_OIDC_CLIENT_ID,
  redirectUri:
    import.meta.env.VITE_OIDC_REDIRECT_URI ??
    window.location.origin + window.location.pathname,
  scope: import.meta.env.VITE_OIDC_SCOPE ?? "openid profile",
};

export function oidcEnabled(): boolean {
  return !!(CFG.authUrl && CFG.tokenUrl && CFG.clientId);
}

function b64url(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(n: number): string {
  const a = new Uint8Array(n);
  crypto.getRandomValues(a);
  return b64url(a);
}

async function sha256(input: string): Promise<Uint8Array> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return new Uint8Array(digest);
}

export async function beginLogin(): Promise<void> {
  const verifier = randomString(48);
  const state = randomString(16);
  sessionStorage.setItem("oidc_verifier", verifier);
  sessionStorage.setItem("oidc_state", state);
  const challenge = b64url(await sha256(verifier));
  const p = new URLSearchParams({
    response_type: "code",
    client_id: CFG.clientId!,
    redirect_uri: CFG.redirectUri,
    scope: CFG.scope,
    code_challenge: challenge,
    code_challenge_method: "S256",
    state,
  });
  window.location.assign(`${CFG.authUrl}?${p.toString()}`);
}

// 若本次載入是 OIDC 回呼(URL 帶 ?code),交換 token 並回傳;否則 null。
export async function handleCallback(): Promise<string | null> {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  if (!code) return null;
  if (params.get("state") !== sessionStorage.getItem("oidc_state")) {
    throw new Error("OIDC state 不符(疑似 CSRF)");
  }
  const verifier = sessionStorage.getItem("oidc_verifier") ?? "";
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: CFG.redirectUri,
    client_id: CFG.clientId!,
    code_verifier: verifier,
  });
  const res = await fetch(CFG.tokenUrl!, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });
  if (!res.ok) throw new Error(`OIDC token 交換失敗:${res.status}`);
  const data = (await res.json()) as { id_token?: string; access_token?: string };
  sessionStorage.removeItem("oidc_verifier");
  sessionStorage.removeItem("oidc_state");
  window.history.replaceState({}, "", CFG.redirectUri);
  return data.id_token ?? data.access_token ?? null;
}

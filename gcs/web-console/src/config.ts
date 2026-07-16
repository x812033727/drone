// 執行期(runtime)設定讀取。讀取優先序:
//   1. window.__APP_CONFIG__ —— 由容器啟動時 entrypoint 依環境變數產生的 /config.js 注入
//      (見 docker-entrypoint.d/40-render-app-config.sh),讓「一份映像多環境部署」免重 build。
//   2. import.meta.env.VITE_* —— build-time 內嵌,保留 dev(vite)與既有建置相容。
//   3. 內建預設值。
// 空字串視為「未設定」而往下退回(entrypoint 對未提供的環境變數會輸出空字串)。

export interface AppRuntimeConfig {
  apiBase?: string;
  oidcAuthUrl?: string;
  oidcTokenUrl?: string;
  oidcClientId?: string;
  oidcRedirectUri?: string;
  oidcScope?: string;
  mapStyle?: string;
  videoBase?: string;
  videoAuth?: string;
}

declare global {
  interface Window {
    __APP_CONFIG__?: AppRuntimeConfig;
  }
}

const RUNTIME: AppRuntimeConfig =
  (typeof window !== "undefined" && window.__APP_CONFIG__) || {};

// 依優先序取第一個非空(去頭尾空白)的值,皆空則回傳 undefined。
function pick(runtime: string | undefined, build: string | undefined): string | undefined {
  const r = runtime?.trim();
  if (r) return r;
  const b = build?.trim();
  if (b) return b;
  return undefined;
}

// 讀取端一律走此物件;各欄位已套用「runtime → VITE_ → 預設」退回鏈。
export const config = {
  apiBase: pick(RUNTIME.apiBase, import.meta.env.VITE_API_BASE) ?? "/api/v1",
  oidcAuthUrl: pick(RUNTIME.oidcAuthUrl, import.meta.env.VITE_OIDC_AUTH_URL),
  oidcTokenUrl: pick(RUNTIME.oidcTokenUrl, import.meta.env.VITE_OIDC_TOKEN_URL),
  oidcClientId: pick(RUNTIME.oidcClientId, import.meta.env.VITE_OIDC_CLIENT_ID),
  oidcRedirectUri: pick(RUNTIME.oidcRedirectUri, import.meta.env.VITE_OIDC_REDIRECT_URI),
  oidcScope: pick(RUNTIME.oidcScope, import.meta.env.VITE_OIDC_SCOPE) ?? "openid profile",
  mapStyle: pick(RUNTIME.mapStyle, import.meta.env.VITE_MAP_STYLE),
  // 即時影像(WHEP):反代前綴與 dev 用讀取帳密(user:pass;JWT 橋接後改帶 token)
  videoBase: pick(RUNTIME.videoBase, import.meta.env.VITE_VIDEO_BASE) ?? "/video",
  videoAuth: pick(RUNTIME.videoAuth, import.meta.env.VITE_VIDEO_AUTH),
};

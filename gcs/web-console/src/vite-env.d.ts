/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_OIDC_AUTH_URL?: string;
  readonly VITE_OIDC_TOKEN_URL?: string;
  readonly VITE_OIDC_CLIENT_ID?: string;
  readonly VITE_OIDC_REDIRECT_URI?: string;
  readonly VITE_OIDC_SCOPE?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}

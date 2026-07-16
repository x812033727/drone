// tier-1 E2E:mock API(page.route)+ 真 mock_oidc(PKCE 全流程)。
// 全網路 mock、無 docker,決定性高 → 掛 web-ci 為 blocking(retries=2 保險)。
// tier-2(compose 真棧,nightly)另有 workflow。
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  retries: 2,
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: [
    {
      // vite preview 服務已建置的 dist/(CI 先 npm run build)
      command: "npm run preview -- --host 127.0.0.1 --port 4173 --strictPort",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      // 真 OIDC mock(授權碼 + PKCE + RS256 JWKS)
      command: "python3 mock_oidc.py 19500 operator",
      url: "http://127.0.0.1:19500/jwks",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
});

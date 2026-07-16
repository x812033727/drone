// OIDC SSO 登入(授權碼 + PKCE):真 mock_oidc(webServer 起於 :19500)全流程。
// API mock 對未帶 token 的請求回 401 → 觸發登入 overlay → SSO → 導回 ?code →
// 前端向 mock_oidc /token 換 RS256 id_token(真 HTTP)→ overlay 消失。
import { expect, test } from "@playwright/test";
import { DEVICES } from "./helpers";

const OIDC_BASE = "http://127.0.0.1:19500";

test("PKCE SSO 全流程:401 → 登入 → 換 token → 進入主畫面", async ({ page }) => {
  // runtime config 以攔截 /config.js 注入(addInitScript 會被靜態 config.js
  // 後載覆蓋,實測;攔截檔案本身才是正解)
  await page.route("**/config.js", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: `window.__APP_CONFIG__ = ${JSON.stringify({
        oidcAuthUrl: `${OIDC_BASE}/authorize`,
        oidcTokenUrl: `${OIDC_BASE}/token`,
        oidcClientId: "web-console-e2e",
        oidcRedirectUri: "http://127.0.0.1:4173/",
      })};`,
    }),
  );

  // 帶 token 放行、未帶 401(驅動 authRequired → overlay)
  await page.route("**/api/v1/**", (route) => {
    const auth = route.request().headers()["authorization"];
    if (!auth) return route.fulfill({ status: 401, json: { detail: "缺少 token" } });
    return route.fulfill({ json: [], headers: { "X-Total-Count": "0" } });
  });
  await page.route("**/api/v1/status**", (route) => {
    const auth = route.request().headers()["authorization"];
    if (!auth) return route.fulfill({ status: 401, json: { detail: "缺少 token" } });
    return route.fulfill({ json: DEVICES });
  });
  // SSE(EventSource 無 header;登入後 token 走查詢參數)
  await page.route("**/api/v1/stream**", (route) => {
    const hasToken = route.request().url().includes("token=");
    if (!hasToken) return route.fulfill({ status: 401 });
    // 不能回 data: {}——App 的 SSE 合併對缺欄位事件會 RangeError(見 helpers)
    return route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: ": keepalive\n\n",
    });
  });

  await page.goto("/");
  await expect(page.getByText("需要登入")).toBeVisible();
  await page.getByRole("button", { name: "以 SSO 登入" }).click();
  // mock_oidc 自動核可導回 ?code=...;前端換 token 後 overlay 消失
  await expect(page.getByText("需要登入")).toHaveCount(0, { timeout: 15_000 });
  await expect(page.locator(".device .serial").first()).toHaveText("e2e-drone-1");
});

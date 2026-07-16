// tier-2:對 compose 真棧驗端到端資料流(dev 模式=無 auth=admin)。
// 前置:compose 全棧 up + mqtt_fanin 已灌假機(CI workflow 負責)。
import { expect, test } from "@playwright/test";

// dev 模式後端無認證,但前端 RBAC 仍依 localStorage token 顯示寫入按鈕。
// 注入一顆 admin 假 token(前端只 decode 不驗簽;後端 dev 模式忽略)以啟用寫入。
function adminToken(): string {
  const b64 = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({
    sub: "e2e",
    role: "admin",
    org: "default",
    exp: Math.floor(Date.now() / 1000) + 3600,
  })}.stack-e2e`;
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript((tok: string) => {
    window.localStorage.setItem("drone_token", tok);
  }, adminToken());
});

test("真棧:灌入的假機出現在地圖清單", async ({ page }) => {
  await page.goto("/");
  // dev 模式無登入 overlay;mqtt_fanin 灌的 loadgen-xxx 機經 SSE/輪詢出現
  await expect(page.locator(".device").first()).toBeVisible({ timeout: 30_000 });
  const count = await page.locator(".device").count();
  expect(count).toBeGreaterThan(0);
});

test("真棧:UI 新增航線 → 真 mission_svc 落庫並列出", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "任務" }).click();
  await page.getByRole("button", { name: "+ 新增航線" }).click();

  const uniqueName = `e2e-stack-${Date.now()}`;
  // 名稱輸入:modal 內第一個 text input(label「名稱 *」包裹)
  const nameInput = page.locator(".form input[required]").first();
  await nameInput.fill(uniqueName);
  await page.getByPlaceholder("lat").first().fill("25.033");
  await page.getByPlaceholder("lon").first().fill("121.5654");
  await page.getByPlaceholder("alt").first().fill("30");

  const created = page.waitForResponse(
    (r) => r.url().includes("/api/v1/routes") && r.request().method() === "POST" && r.status() === 201,
  );
  await page.getByRole("button", { name: "建立", exact: true }).click();
  await created; // 真 mission_svc 回 201(端到端寫入落庫)

  // 航線出現在清單(console → mission_svc → DB → 回讀 → 渲染)
  await expect(page.getByText(uniqueName)).toBeVisible({ timeout: 15_000 });
});

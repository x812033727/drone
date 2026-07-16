// 裝置清單 + 地圖分頁 + 影像面板出現(mock API)。
import { expect, test } from "@playwright/test";
import { loginAs, mockApi } from "./helpers";

test.beforeEach(async ({ page }) => {
  await loginAs(page, "viewer");
  await mockApi(page);
});

test("裝置清單渲染兩台機(在線/離線)", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".device .serial").first()).toHaveText("e2e-drone-1");
  await expect(page.locator(".device")).toHaveCount(2);
  await expect(page.locator(".device .dot.on")).toHaveCount(1);
  await expect(page.locator(".device .dot.off")).toHaveCount(1);
});

test("選中機顯示即時影像面板", async ({ page }) => {
  await page.goto("/");
  await page.locator(".device", { hasText: "e2e-drone-1" }).click();
  await expect(page.locator(".video-panel-header")).toContainText("e2e-drone-1");
});

test("告警分頁渲染兩筆 + 頂欄 badge", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".tab-badge")).toHaveText("2");
  await page.getByRole("button", { name: /告警/ }).click();
  await expect(page.getByText("裝置憑證 30 天內到期")).toBeVisible();
  await expect(page.getByText("OTA 進度 50%")).toBeVisible();
});

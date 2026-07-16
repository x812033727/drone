// operator 派遣全流程(mock API):新增航線 → 建立任務 → 派遣,斷言請求 payload。
import { expect, test } from "@playwright/test";
import { loginAs, mockApi } from "./helpers";

const ROUTE = {
  id: "33333333-3333-3333-3333-333333333333",
  name: "e2e-route",
  org_id: "e2e",
  waypoints: [
    { lat_deg: 25.033, lon_deg: 121.5654, rel_alt_m: 30, hold_s: 0, speed_ms: 0 },
  ],
  rtl_after_last: true,
  created_at: new Date().toISOString(),
};

const MISSION = {
  id: "44444444-4444-4444-4444-444444444444",
  mission_id: "e2e-m-1",
  route_id: ROUTE.id,
  drone_id: "e2e-drone-1",
  status: "created",
  waypoints: ROUTE.waypoints,
  rtl_after_last: true,
  created_at: new Date().toISOString(),
};

test("新增航線:表單送出的 waypoints 正確", async ({ page }) => {
  await loginAs(page, "operator");
  await mockApi(page);
  const posted = page.waitForRequest(
    (req) => req.url().includes("/api/v1/routes") && req.method() === "POST",
  );
  await page.goto("/");
  await page.getByRole("button", { name: "任務" }).click();
  await page.getByRole("button", { name: "+ 新增航線" }).click();
  await page.getByLabel(/名稱/).fill("e2e-route");
  await page.getByPlaceholder("lat").fill("25.033");
  await page.getByPlaceholder("lon").fill("121.5654");
  await page.getByPlaceholder("alt").fill("30");
  await page.getByRole("button", { name: "建立", exact: true }).click();
  const req = await posted;
  const body = req.postDataJSON();
  expect(body.name).toBe("e2e-route");
  expect(body.waypoints).toHaveLength(1);
  expect(body.waypoints[0].lat_deg).toBeCloseTo(25.033);
});

test("建立任務 + 派遣:狀態按鈕與 dispatch 請求", async ({ page }) => {
  await loginAs(page, "operator");
  await mockApi(page, { routes: [ROUTE], missions: [MISSION] });
  let dispatched = false;
  await page.route("**/api/v1/missions/*/dispatch", (route) => {
    dispatched = true;
    return route.fulfill({ json: { ...MISSION, status: "dispatched" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "任務" }).click();
  await expect(page.getByText("e2e-m-1")).toBeVisible();
  await page.getByRole("button", { name: "派遣" }).click();
  await expect.poll(() => dispatched).toBe(true);
});

test("viewer 看不到寫入按鈕(前端 RBAC gating)", async ({ page }) => {
  await loginAs(page, "viewer");
  await mockApi(page, { routes: [ROUTE], missions: [MISSION] });
  await page.goto("/");
  await page.getByRole("button", { name: "任務" }).click();
  await expect(page.getByRole("button", { name: "+ 新增航線" })).toHaveCount(0);
});

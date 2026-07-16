// e2e 共用:假 JWT 鑄造(前端只 decode 不驗簽)、API mock、runtime config 注入。
import type { Page } from "@playwright/test";

// 前端 auth.ts 只 base64 decode claims(驗簽在後端);e2e 全網路 mock,
// 自組三段式 token 即可驅動角色 gating。
export function mintFakeJwt(role: string, org = "e2e"): string {
  const b64url = (obj: unknown) =>
    Buffer.from(JSON.stringify(obj)).toString("base64url");
  const header = b64url({ alg: "HS256", typ: "JWT" });
  const payload = b64url({
    sub: "e2e-user",
    role,
    org,
    exp: Math.floor(Date.now() / 1000) + 3600,
  });
  return `${header}.${payload}.e2e-fake-signature`;
}

export const DEVICES = [
  {
    device_id: "11111111-1111-1111-1111-111111111111",
    serial: "e2e-drone-1",
    name: "測試機一",
    fleet_id: null,
    status: "active",
    online: true,
    last_seen: new Date().toISOString(),
    lat_deg: 25.033,
    lon_deg: 121.5654,
    rel_alt_m: 30,
    battery_pct: 88,
    flight_mode: "MISSION",
    armed: true,
  },
  {
    device_id: "22222222-2222-2222-2222-222222222222",
    serial: "e2e-drone-2",
    name: null,
    fleet_id: null,
    status: "active",
    online: false,
    last_seen: null,
    lat_deg: null,
    lon_deg: null,
    rel_alt_m: null,
    battery_pct: null,
    flight_mode: null,
    armed: null,
  },
];

export const ALERTS = [
  {
    time: new Date().toISOString(),
    drone_id: "e2e-drone-1",
    kind: "cert",
    summary: "裝置憑證 30 天內到期",
    detail: { days_left: 12 },
  },
  {
    time: new Date().toISOString(),
    drone_id: "e2e-drone-2",
    kind: "ota",
    summary: "OTA 進度 50%",
    detail: { phase: "download", pct: 50 },
  },
];

// 攔下全部 /api/**(未列舉者回空陣列,避免真請求外洩);SSE 以最小合法回應收掉。
export async function mockApi(
  page: Page,
  opts: { routes?: unknown[]; missions?: unknown[] } = {},
): Promise<void> {
  // ⚠️ Playwright route 為 LIFO(後註冊優先):兜底最先註冊、specifics 其後。
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({ json: [], headers: { "X-Total-Count": "0" } }),
  );
  await page.route("**/api/v1/stream**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      // App 的 SSE 合併會做 new Date(unix_time_ms).toISOString():欄位必須齊全,
      // 缺 unix_time_ms 會 RangeError 炸掉整個 React render(實測)。
      body: `data: ${JSON.stringify({
        drone_id: "e2e-drone-1",
        unix_time_ms: Date.now(),
        lat_deg: 25.033,
        lon_deg: 121.5654,
        rel_alt_m: 30,
        battery_pct: 88,
        flight_mode: "MISSION",
        armed: true,
      })}\n\n`,
    }),
  );
  await page.route("**/api/v1/status**", (route) =>
    route.fulfill({ json: DEVICES }),
  );
  await page.route("**/api/v1/alerts**", (route) =>
    route.fulfill({ json: ALERTS, headers: { "X-Total-Count": "2" } }),
  );
  await page.route("**/api/v1/routes**", (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      return route.fulfill({
        status: 201,
        json: { id: "33333333-3333-3333-3333-333333333333", org_id: "e2e", ...body },
      });
    }
    return route.fulfill({
      json: opts.routes ?? [],
      headers: { "X-Total-Count": String((opts.routes ?? []).length) },
    });
  });
  await page.route("**/api/v1/missions**", (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      return route.fulfill({
        status: 201,
        json: {
          id: "44444444-4444-4444-4444-444444444444",
          mission_id: "e2e-m-1",
          status: "created",
          waypoints: [],
          rtl_after_last: true,
          created_at: new Date().toISOString(),
          ...body,
        },
      });
    }
    return route.fulfill({
      json: opts.missions ?? [],
      headers: { "X-Total-Count": String((opts.missions ?? []).length) },
    });
  });
}

// 以 operator token 進入已登入狀態(localStorage;App 讀 drone_token)。
export async function loginAs(page: Page, role: string): Promise<void> {
  const token = mintFakeJwt(role);
  await page.addInitScript((t: string) => {
    window.localStorage.setItem("drone_token", t);
  }, token);
}

// tier-2 E2E:對 compose 真棧(dev 模式,無 auth=admin)。
// 驗真資料流:mqtt_fanin 灌假機 → 地圖真裝置 → 真 dispatch(mission 狀態機)。
// 登入流程由 tier-1(mock API + mock_oidc)覆蓋,tier-2 專驗端到端資料。
// 無 webServer:compose 提供 webconsole;BASE_URL 由環境變數指入。
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e-stack",
  retries: 1,
  timeout: 60_000,
  use: {
    baseURL: process.env.STACK_BASE_URL ?? "http://127.0.0.1:8080",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});

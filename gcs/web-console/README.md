# web-console — 無人機機隊 Web 指揮中心

> 對 [docs/20-software/ground-station.md](../../docs/20-software/ground-station.md) 的 Web 指揮中心與
> [cloud-fleet.md §3](../../docs/20-software/cloud-fleet.md)「機隊儀表板/遙測即時圖」Phase 1 最小版。
> 消費 [fleet-svc](../../cloud/fleet_svc/README.md) 的 `/api/v1/status`(輪詢)+ `/api/v1/stream`(SSE),
> 以及 devices/fleets/firmware CRUD;寫入類任務由 [mission-svc](../../cloud/mission_svc/README.md)
> 的 routes/missions CRUD + 派遣/控制契約提供。

React + Vite + TypeScript + MapLibre GL。

## 功能

分頁視圖(頂欄切換,單頁 SPA,狀態沿用 React hooks,不引入 Redux;分頁依角色顯示):

- **地圖監控**:機隊清單(在線/離線、飛行模式、電量、相對高度、最後遙測時間)+ MapLibre
  即時地圖(綠=在線/灰=離線,SSE 即時更新,首次自動框住全機隊,點選置中開 popup)。
- **機隊管理**:列出機隊/裝置;新增機隊;新增/編輯/退役裝置(退役=PATCH `status=retired`)。
- **任務**:列出航線/任務;以表單輸入航點(緯度/經度/相對高度列)建立航線;由航線 + 目標機
  建立任務;派遣(POST dispatch)、暫停/恢復/中止(POST command);顯示任務狀態機進度。
- **用量**(所有登入者):讀 `GET /api/v1/usage`(本 org),以長條顯示裝置/機隊配額用量比例
  (現存 / 上限,≥80% 轉黃、達上限轉紅),並列本期計費計數與歷來累計。
- **租戶**(**僅 admin 顯示**):讀 `GET /api/v1/orgs`(分頁,total 走 `X-Total-Count`)列出租戶
  (org_id/名稱/方案/狀態/配額覆寫);建立(POST)、編輯 plan/狀態(active↔suspended)/配額覆寫
  (PATCH,留空=用方案預設);點「用量」看該租戶 `GET /api/v1/orgs/{id}/usage` 彙總。

其它:

- **前端 RBAC**:解析 JWT 的 `role`/`roles`/Keycloak `realm_access.roles`(對後端
  `cloud/fleet_svc/fleet_svc/auth.py`,viewer<operator<admin)。viewer 只能看,operator 以上才
  顯示/啟用寫入動作;**「租戶」分頁與其動作僅 admin 可見**(對 `/orgs` 的 admin only 閘門)。
  此為 UX 閘門,真正授權仍由後端 JWT 驗簽 + RBAC 強制(偽造前端角色仍被後端 403 擋下)。
- **告警**:低電量(<20%)、離線、任務 FAILED 以 toast 提示(僅在狀態「進入」轉移時,不刷屏)。

## API 反代

fleet-svc 與 mission-svc 的 `/api/v1` 路徑前綴不衝突,故前端共用同一 base;由反代依前綴分流:

| 路徑前綴 | 目標 |
|----------|------|
| `/api/v1/routes`、`/api/v1/missions` | mission-svc(:8092) |
| 其餘 `/api/`(status/devices/fleets/firmware/stream/**orgs/usage**) | fleet-svc(:8091) |

`/orgs`、`/usage` 皆在 fleet-svc(:8091),落在既有 catch-all,**無需改 nginx.conf**。

正式部署見 `nginx.conf`(較長前綴優先);開發見 `vite.config.ts`(proxy)。

## 開發

```bash
npm install
# 需先起 fleet-svc(根 make dev);dev server 把 /api 代理到 FLEETSVC_PORT
VITE_DEV_API_TARGET=http://localhost:38091 npm run dev
npm run lint && npm run typecheck && npm run build
```

## 設定(執行期注入 / 一份映像多環境)

設定讀取採**執行期注入**,不再綁在 build。前端(`src/config.ts`)依序退回:

1. **`window.__APP_CONFIG__`** —— 由容器啟動時 entrypoint 依**環境變數**產生的 `/config.js`
   注入。**同一份 nginx 映像**改環境變數即可部署到不同環境(不同 OIDC/API/地圖),**免重 build**。
2. **`import.meta.env.VITE_*`** —— build-time 內嵌,保留 dev(vite)與既有建置相容。
3. 內建預設值。

`index.html` 於 app bundle 前載入 `<script src="/config.js">`。空字串視為「未設定」而往下退回。

### 可注入環境變數(容器)

容器啟動時 `docker-entrypoint.d/40-render-app-config.sh`(由 nginx 官方 entrypoint 自動執行)
讀下列變數產生 `/usr/share/nginx/html/config.js`。未設者留空 → 前端退回 `VITE_*` / 內建預設。

| 環境變數 | 對應設定 | 預設(未設時) | 說明 |
|----------|----------|----------------|------|
| `APP_API_BASE` | `apiBase` | `/api/v1` | API 前綴(正式由 nginx 依前綴分流至 fleet/mission-svc) |
| `APP_OIDC_AUTH_URL` | `oidcAuthUrl` | (停用 OIDC) | OIDC 授權端點 |
| `APP_OIDC_TOKEN_URL` | `oidcTokenUrl` | (停用 OIDC) | OIDC token 端點 |
| `APP_OIDC_CLIENT_ID` | `oidcClientId` | (停用 OIDC) | OIDC 公開客戶端 ID |
| `APP_OIDC_REDIRECT_URI` | `oidcRedirectUri` | 目前頁面 origin+path | OIDC 回呼位址 |
| `APP_OIDC_SCOPE` | `oidcScope` | `openid profile` | OIDC scope |
| `APP_MAP_STYLE` | `mapStyle` | 內嵌 OSM raster | 私有部署可換離線/自建 tile 伺服器的 style URL |
| `APP_CONFIG_PATH` | — | `/usr/share/nginx/html/config.js` | 產出檔路徑(通常不需改) |

`oidcAuthUrl`/`oidcTokenUrl`/`oidcClientId` 三者齊備才啟用 SSO,否則退回貼 token。

用法範例(一份映像、兩個環境):

```bash
docker run -e APP_API_BASE=/api/v1 \
  -e APP_OIDC_AUTH_URL=https://idp.a.example/auth \
  -e APP_OIDC_TOKEN_URL=https://idp.a.example/token \
  -e APP_OIDC_CLIENT_ID=drone-web \
  -e APP_MAP_STYLE=https://tiles.a.example/style.json \
  web-console   # 換一組 env 即部署到另一環境,毋須重 build
```

### 建置期 env(dev / vite,仍相容)

| 變數 | 預設 | 說明 |
|------|------|------|
| `VITE_API_BASE` / `VITE_OIDC_*` / `VITE_MAP_STYLE` | 同上 | build-time 內嵌;僅在無執行期注入時生效 |
| `VITE_DEV_API_TARGET` | `http://localhost:38091` | 僅 dev:vite proxy 至 fleet-svc |
| `VITE_DEV_MISSION_TARGET` | `http://localhost:38092` | 僅 dev:vite proxy 至 mission-svc(routes/missions) |

dev(vite)以 `public/config.js`(各欄留空)提供 `/config.js`,故本地開發行為與過往一致
(全數退回 `VITE_*` / 內建預設)。

## 未做(需設計決策,列 TODO)

- 地圖點擊繪製航點(目前以表單輸入 lat/lon/alt 列)。
- 租戶(org)管理 UI、token 靜默續期。
- 韌體指派 UI(後端 `PUT /devices/{id}/firmware` 已存在,前端尚未接)。

## 部署

`Dockerfile`(多階段:node 建置 → nginx)服務靜態檔並把 `/api` 反代 `fleetsvc:8091`
(SSE 已關 buffering)。啟動時 entrypoint 依環境變數產生 `/config.js`(見上「可注入環境變數」),
故同一映像可多環境部署。隨 compose `webconsole` 服務起(見 `cloud/deploy/compose`)。
私有部署設 `APP_MAP_STYLE`(或 build-time `VITE_MAP_STYLE`)指向離線 tile,即可資料與地圖皆不出機房。

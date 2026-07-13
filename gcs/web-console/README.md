# web-console — 無人機機隊 Web 指揮中心

> 對 [docs/20-software/ground-station.md](../../docs/20-software/ground-station.md) 的 Web 指揮中心與
> [cloud-fleet.md §3](../../docs/20-software/cloud-fleet.md)「機隊儀表板/遙測即時圖」Phase 1 最小版。
> 消費 [fleet-svc](../../cloud/fleet_svc/README.md) 的 `/api/v1/status`(輪詢)+ `/api/v1/stream`(SSE),
> 以及 devices/fleets/firmware CRUD;寫入類任務由 [mission-svc](../../cloud/mission_svc/README.md)
> 的 routes/missions CRUD + 派遣/控制契約提供。

React + Vite + TypeScript + MapLibre GL。

## 功能

三個分頁視圖(頂欄切換,單頁 SPA,狀態沿用 React hooks,不引入 Redux):

- **地圖監控**:機隊清單(在線/離線、飛行模式、電量、相對高度、最後遙測時間)+ MapLibre
  即時地圖(綠=在線/灰=離線,SSE 即時更新,首次自動框住全機隊,點選置中開 popup)。
- **機隊管理**:列出機隊/裝置;新增機隊;新增/編輯/退役裝置(退役=PATCH `status=retired`)。
- **任務**:列出航線/任務;以表單輸入航點(緯度/經度/相對高度列)建立航線;由航線 + 目標機
  建立任務;派遣(POST dispatch)、暫停/恢復/中止(POST command);顯示任務狀態機進度。

其它:

- **前端 RBAC**:解析 JWT 的 `role`/`roles`/Keycloak `realm_access.roles`(對後端
  `cloud/fleet_svc/fleet_svc/auth.py`,viewer<operator<admin)。viewer 只能看,operator 以上才
  顯示/啟用寫入動作。此為 UX 閘門,真正授權仍由後端 JWT 驗簽 + RBAC 強制。
- **告警**:低電量(<20%)、離線、任務 FAILED 以 toast 提示(僅在狀態「進入」轉移時,不刷屏)。

## API 反代

fleet-svc 與 mission-svc 的 `/api/v1` 路徑前綴不衝突,故前端共用同一 base;由反代依前綴分流:

| 路徑前綴 | 目標 |
|----------|------|
| `/api/v1/routes`、`/api/v1/missions` | mission-svc(:8092) |
| 其餘 `/api/`(status/devices/fleets/firmware/stream) | fleet-svc(:8091) |

正式部署見 `nginx.conf`(較長前綴優先);開發見 `vite.config.ts`(proxy)。

## 開發

```bash
npm install
# 需先起 fleet-svc(根 make dev);dev server 把 /api 代理到 FLEETSVC_PORT
VITE_DEV_API_TARGET=http://localhost:38091 npm run dev
npm run lint && npm run typecheck && npm run build
```

## 設定(建置期 env)

| 變數 | 預設 | 說明 |
|------|------|------|
| `VITE_API_BASE` | `/api/v1` | API 前綴(正式由 nginx 依前綴分流至 fleet/mission-svc) |
| `VITE_MAP_STYLE` | 內嵌 OSM raster | 私有部署可換離線/自建 tile 伺服器的 style URL |
| `VITE_DEV_API_TARGET` | `http://localhost:38091` | 僅 dev:vite proxy 至 fleet-svc |
| `VITE_DEV_MISSION_TARGET` | `http://localhost:38092` | 僅 dev:vite proxy 至 mission-svc(routes/missions) |

## 未做(需設計決策,列 TODO)

- 地圖點擊繪製航點(目前以表單輸入 lat/lon/alt 列)。
- 執行期(而非建置期)注入 API base / OIDC 設定。
- 租戶(org)管理 UI、token 靜默續期。
- 韌體指派 UI(後端 `PUT /devices/{id}/firmware` 已存在,前端尚未接)。

## 部署

`Dockerfile`(多階段:node 建置 → nginx)服務靜態檔並把 `/api` 反代 `fleetsvc:8091`
(SSE 已關 buffering)。隨 compose `webconsole` 服務起(見 `cloud/deploy/compose`)。
私有部署改 `VITE_MAP_STYLE` 指向離線 tile,即可資料與地圖皆不出機房。

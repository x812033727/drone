# web-console — 無人機機隊 Web 指揮中心

> 對 [docs/20-software/ground-station.md](../../docs/20-software/ground-station.md) 的 Web 指揮中心與
> [cloud-fleet.md §3](../../docs/20-software/cloud-fleet.md)「機隊儀表板/遙測即時圖」Phase 1 最小版。
> 消費 [fleet-svc](../../cloud/fleet_svc/README.md) 的 `/api/v1/status`(輪詢)+ `/api/v1/stream`(SSE)。

React + Vite + TypeScript + MapLibre GL。

## 功能(MVP)

- 機隊清單:每台裝置的在線/離線、飛行模式、電量、相對高度、最後遙測時間。
- 即時地圖:MapLibre 上以顏色標記(綠=在線/灰=離線)顯示各機位置,SSE 即時更新;首次自動框住全機隊,點選置中並開 popup。
- 頂欄:總數 / 在線數 / 串流連線狀態。

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
| `VITE_API_BASE` | `/api/v1` | fleet-svc API 前綴(正式由 nginx 代理) |
| `VITE_MAP_STYLE` | 內嵌 OSM raster | 私有部署可換離線/自建 tile 伺服器的 style URL |
| `VITE_DEV_API_TARGET` | `http://localhost:38091` | 僅 dev:vite proxy 目標 |

## 部署

`Dockerfile`(多階段:node 建置 → nginx)服務靜態檔並把 `/api` 反代 `fleetsvc:8091`
(SSE 已關 buffering)。隨 compose `webconsole` 服務起(見 `cloud/deploy/compose`)。
私有部署改 `VITE_MAP_STYLE` 指向離線 tile,即可資料與地圖皆不出機房。

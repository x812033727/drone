# fleet-svc — 機隊/裝置/韌體版本管理

> 對 [docs/20-software/cloud-fleet.md §3](../../docs/20-software/cloud-fleet.md)「裝置註冊/機隊儀表板」。
> 服務層 Phase 0→1 雛形;沿用 [cloud/log_svc](../log_svc/README.md) 的 FastAPI + asyncpg 範式。

## 職責

- 機隊(fleet)、裝置(device)、韌體版本(firmware_version)、裝置安裝韌體(device_firmware)的 CRUD。
- 資料落**既有 timescaledb 實例**的 `fleet` schema(與 `public` 的遙測時序表分離),前向 SQL migration 啟動時自動套用(`migrations/*.sql`)。
- **在線狀態/最後位置(遙測消費 + SSE)屬 B2,不在本服務**(下一個 PR)。

## API(前綴 `/api/v1`)

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/fleets` | 建機隊 |
| GET | `/fleets` · `/fleets/{id}` | 列出 / 取單筆 |
| POST | `/devices` | 建裝置(serial 唯一,重複 409) |
| GET | `/devices?fleet_id=` · `/devices/{id}` | 列出(可依機隊)/ 取單筆 |
| PATCH | `/devices/{id}` | 更新(name/fleet_id/model/status) |
| DELETE | `/devices/{id}` | 刪除(204) |
| POST | `/firmware` · GET `/firmware` | 韌體版本目錄 |
| PUT | `/devices/{id}/firmware` | 記錄裝置某元件安裝版本(upsert) |
| GET | `/devices/{id}/firmware` | 裝置各元件安裝版本 |
| GET | `/healthz` | DB 探活(compose healthcheck) |

## 設計決策

- **不另立 PostGIS 實例**:專案現況是單一 timescaledb(pg16)。fleet 關聯資料用同實例的 `fleet` schema;位置(B2)先存 lat/lon 雙精度。PostGIS geography 待有空間查詢需求(geofence/半徑搜尋)再以 migration 引入。
- **輕量前向 SQL migration**(`fleet_svc.migrate`,asyncpg 原生),不引入 SQLAlchemy/Alembic;改 schema 一律新增 `NNNN_*.sql`,不改既有已套用檔。
- **認證(Wave 4 C3)**:REST 端點帶 JWT + RBAC(讀取需 viewer、變更需 operator)。
  `JWT_SECRET`(HS256/dev)或 `JWT_JWKS_URL`(RS256/OIDC 生產)設定其一即啟用;
  兩者皆空為 dev 模式(全放行,啟動警告)。`healthz` 與 SSE `/stream` 不 gate
  (EventSource 無法帶 header;SSE 查詢參數 token 認證留後續)。

## 本機

```bash
# 隨 make dev 一併起(見根 Makefile / DEVELOPMENT.md)
curl -s localhost:38091/api/v1/fleets            # 埠見 compose FLEETSVC_PORT
```

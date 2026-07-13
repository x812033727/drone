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
| POST | `/billing/checkout` | 為本 org 發起訂閱結帳(operator/admin),回綠界表單參數 |
| POST | `/billing/callback` | 綠界 server 回調(驗 CheckMacValue,付款成功啟用方案) |
| GET | `/billing/subscription` | 本 org 目前方案/狀態/最近交易 |
| GET | `/healthz` | DB 探活(compose healthcheck) |

## 設計決策

- **不另立 PostGIS 實例**:專案現況是單一 timescaledb(pg16)。fleet 關聯資料用同實例的 `fleet` schema;位置(B2)先存 lat/lon 雙精度。PostGIS geography 待有空間查詢需求(geofence/半徑搜尋)再以 migration 引入。
- **輕量前向 SQL migration**(`fleet_svc.migrate`,asyncpg 原生),不引入 SQLAlchemy/Alembic;改 schema 一律新增 `NNNN_*.sql`,不改既有已套用檔。
- **認證(Wave 4 C3)**:REST 端點帶 JWT + RBAC(讀取需 viewer、變更需 operator)。
  `JWT_SECRET`(HS256/dev)或 `JWT_JWKS_URL`(RS256/OIDC 生產)設定其一即啟用;
  兩者皆空為 dev 模式(全放行,啟動警告)。`healthz` 與 SSE `/stream` 不 gate
  (EventSource 無法帶 header;SSE 查詢參數 token 認證留後續)。

## 訂閱金流(綠界 ECPay)

把 #118 的 org 方案(free/pro/enterprise)從 admin 手動設定,升級為**自助結帳付費啟用**。
不新增獨立服務,金流控制面內嵌本服務;CheckMacValue 以標準庫 `hashlib`(SHA256)計算,**零新依賴**。

**流程**:

1. operator/admin 呼叫 `POST /billing/checkout`(指定 `plan`)→ 服務落一筆 `pending`
   `billing_transaction`,回傳綠界 AioCheckOut 表單參數(含 `CheckMacValue`)。
2. 前端把 `params` 以表單 `POST` 到 `action_url`(綠界結帳頁),使用者付款。
3. 綠界 server 端 `POST` 回調 `/billing/callback`(`application/x-www-form-urlencoded`)。
4. 服務**驗 `CheckMacValue`**(壞章 400 拒絕);`RtnCode=1` 付款成功 → 交易轉 `paid`、
   **upsert `fleet.org` 為該 plan + status=active**,回綠界要求的純文字 `1|OK`。回調具冪等性
   (已 `paid` 的訂單重送不重複啟用),支撐綠界重送。

**CheckMacValue**:參數 A→Z 排序 → 前綴 `HashKey=`/後綴 `&HashIV=` → URL encode → 轉小寫
→ .NET `HttpUtility.UrlEncode` 相容字元還原 → SHA256 → 轉大寫。以綠界官方文件
([檢查碼機制](https://developers.ecpay.com.tw/2902/))的已知測試向量驗證(見 `tests/test_billing.py`)。

**方案月費(TWD,可 env 覆寫)**:free=0(不可結帳)、pro=3000、enterprise=30000。

**環境變數**:

| 變數 | 說明 |
|------|------|
| `ECPAY_MERCHANT_ID` | 綠界商店代號(MerchantID) |
| `ECPAY_HASH_KEY` | 綠界 HashKey |
| `ECPAY_HASH_IV` | 綠界 HashIV |
| `ECPAY_RETURN_URL` | 綠界 server 回調本服務 `/billing/callback` 的**公開可達** URL |
| `ECPAY_CLIENT_BACK_URL` | 使用者付款後返回的前端 URL(可選) |
| `ECPAY_STAGE` | `true` 時即使有正式憑證仍打綠界測試環境(預設 false) |
| `ECPAY_PRICE_PRO` / `ECPAY_PRICE_ENTERPRISE` | 各方案月費覆寫 |

**沙箱/停用模式**:三個憑證(MERCHANT_ID/HASH_KEY/HASH_IV)缺任一 → 自動走**沙箱**:
使用綠界**官方公開**的測試商店代號/金鑰(全網文件公開、非機敏、**非正式憑證**)並打測試環境
(`payment-stage.ecpay.com.tw`),`checkout` 回應 `sandbox: true`。此模式不真實扣款,
故 cloud-smoke(未設 `ECPAY_*`)不受影響。**正式部署務必經 env 提供真實憑證,絕不硬編。**



```bash
# 隨 make dev 一併起(見根 Makefile / DEVELOPMENT.md)
curl -s localhost:38091/api/v1/fleets            # 埠見 compose FLEETSVC_PORT
```

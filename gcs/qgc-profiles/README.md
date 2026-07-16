# qgc-profiles — stock QGC 預設檔(選項 A 交付物)

> 決策依據:[docs/20-software/gcs-qgc-evaluation.md §5](../../docs/20-software/gcs-qgc-evaluation.md)——Phase 0 採 stock QGC + 預設檔,不 build、零 CI。
> 本目錄是操作人拿到官方 QGC 安裝檔之後,「開箱設定到可安全操作 PA-1 開發機」的全部隨附物。

## 目錄規劃

| 路徑 | 內容 | 狀態 |
|------|------|------|
| `VERSION.md` | QGC 版本 pin(版號 + 官方下載連結 + 升版驗證清單) | ✅ 本 PR |
| `params/` | 參數預設檔指標(單一事實來源=[tools/flight_ops/params/](../../tools/flight_ops/params/),不複製;PA-1 專屬包待 rev A 定容) | ✅ |
| `plans/` | 標準任務範本(`.plan`:矩形測繪 `survey-rect-demo`、定點巡檢 `inspect-point-demo`;結構由 `tools/tests/test_qgc_plans.py` 守門) | ✅ |
| 本檔 §台灣圖源 | NLSC 圖源設定步驟(stock 自訂圖源 URL 途徑) | ✅ 本 PR |

## QGC 版本 pin

見 [VERSION.md](VERSION.md)。原則:

- pin 到官方 **stable** 版號;升版時跑 VERSION.md 內的回歸清單(載入參數檔、載入任務範本、圖源可用)再改 pin。
- 開發機(Pixhawk 6X,PX4 v1.15.x)與 QGC 版本的相容性以 PX4 官方支援表為準。

## 台灣圖源設定(stock 途徑)

QGC stock 支援自訂圖磚源(XYZ 樣式 URL)。國土測繪中心(NLSC)WMTS 服務可用 XYZ 樣式 REST 路徑存取:

1. QGC → Application Settings → Offline Maps(或 Map Provider 設定,依版本)→ 自訂圖源。
2. 電子地圖(EMAP):`https://wmts.nlsc.gov.tw/wmts/EMAP/default/GoogleMapsCompatible/{z}/{y}/{x}`
3. 正射影像(PHOTO2):`https://wmts.nlsc.gov.tw/wmts/PHOTO2/default/GoogleMapsCompatible/{z}/{y}/{x}`
4. 作業區域先在有網路處以 Offline Maps 預抓圖磚(離線作業需求見 [ground-station.md §3](../../docs/20-software/ground-station.md));圖資發布日期 > 30 天的告警口徑見同文件 §5.2。

⚠️ 合規注意(評估文件 §4.2 既有口徑):NLSC 圖磚商用授權條款在正式對外服務前需確認;開發/內部驗證用途先行。

## 明確不在本目錄範圍

- branding、鎖機型、簡化 UI、內建預載圖資 → 選項 B(`qgc-custom/`,Phase 1 立項再開)。
- Web 主控台的地圖與任務規劃 → [web-console/](../web-console/)。

# 50-6 平台 SLO 與可觀測性(G13)

> rev 1 · 2026-07。定義 drone 雲端平台的 **SLO(服務水準目標)**,並把每項目標
> 對應到**已落地的 `/metrics` 指標**與 [alert-rules.yaml](../../../cloud/deploy/observability/alert-rules.yaml) 的告警。
> 可用性目標對齊 [cloud-fleet.md §5](../../20-software/cloud-fleet.md)(平台目標可用性 99.5%)。
>
> **以現有實作為準**:下表指標皆為服務程式內**實際暴露**的 Prometheus 指標;
> 尚未落地者一律明標「⏳ 待補」,不杜撰。飛行安全**不**依賴雲端(SLA 壓力可控)。

## 0. 範圍與非目標

- **範圍**:雲端控制面四服務——`fleetsvc`、`missionsvc`、`logsvc`(FastAPI)與
  `ingest`(MQTT→TimescaleDB 消費者)。
- **非目標**:機載飛行安全(離線自主,不受雲端 SLA 影響);影音串流品質(mediamtx,另議)。
- **量測窗**:滾動 30 天,除非另註。錯誤預算 = (1 − SLO) × 窗長。

## 1. SLO 一覽

| # | SLO | 目標 | 量測(PromQL 概念) | 對應指標 | 告警 |
|---|-----|------|---------------------|----------|------|
| 1 | 控制面可用性 | 99.5%(30 天) | `avg_over_time(up{job=~"fleetsvc\|missionsvc\|logsvc\|ingest"}[30d])` | `up`(抓取存活) | `ServiceDown` |
| 2 | API 成功率 | ≥ 99%(非 5xx) | `1 − (5xx 率 ÷ 總請求率)` | `http_requests_total{status}` | `HighHttp5xxRate` |
| 3 | API 延遲 | p95 < 1s | `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))` | `http_request_duration_seconds` | `HighApiLatencyP95` |
| 4 | 遙測落庫成功率 | ≥ 99% | `ok ÷ (ok+error)` | `ingest_db_writes_total{result}` | `IngestDbWriteFailureRate` |
| 5 | 遙測端到端不停滯 | 有入站即持續落庫 | `parsed>0 且 ok==0 視為故障` | `ingest_messages_total{result}` + `ingest_db_writes_total` | `TelemetryIngestionStalled` |
| 6 | 入站不積壓 | 處理中 ≤ 100 | `ingest_messages_inflight` | `ingest_messages_inflight` | `IngestBacklogHigh` |

> **端到端遙測延遲**(裝置發送→落庫)目前**無跨程序追蹤 span**,故以「落庫成功率 +
> 不停滯 + 不積壓」三項間接守住(SLO 4/5/6)。真正的 e2e 延遲直方圖需 gateway 於
> 訊息帶發送時戳並在落庫端相減 —— **⏳ 待補(Phase 1 gateway,見 [cloud/ingest/README.md](../../../cloud/ingest/README.md))**。

## 2. 指標來源(已落地)

四服務啟動即暴露 Prometheus 文字格式;皆含 `process_*`(RSS/CPU/開檔數)與
`python_gc_*` 標準收集器,並用**各自獨立的 CollectorRegistry**(同行程多服務匯入不撞名)。

| 服務 | 端點 | 業務指標 |
|------|------|----------|
| `fleetsvc` | `GET :8091/metrics` | `http_requests_total{method,path,status}`、`http_request_duration_seconds{method,path}` |
| `missionsvc` | `GET :8092/metrics` | 同上 |
| `logsvc` | `GET :8090/metrics` | 同上 |
| `ingest` | `GET :9090/metrics`(獨立埠) | `ingest_messages_total{route,result}`、`ingest_db_writes_total{result}`、`ingest_messages_inflight` |

實作細節:
- **FastAPI 服務**:純 ASGI middleware 記錄每次請求的 `method` / **路由樣板**
  `path`(如 `/api/v1/devices/{device_id}`,而非帶 UUID 的實路徑,避免高基數) / `status`
  與延遲直方圖。`/metrics` 為獨立路由(非 mount,無尾斜線轉址)。
- **ingest**:非 HTTP 服務,以 `prometheus_client.start_http_server` 於啟動時另開
  metrics 埠。埠由環境變數 **`METRICS_PORT`** 設定(**預設 9090**;設為 `0` 則停用)。
  `route` 標籤取主題末段(`telemetry`、`mission/progress`、`sensors/attitude`……),
  **不含機隊 id**,基數受控。`result` ∈ `parsed` / `decode_error` / `unknown_topic`;
  DB 寫入 `result` ∈ `ok` / `error`。
- **失效隔離**:埋點僅遞增計數、與請求/消費主路徑解耦;`/metrics` 或 metrics 埠
  異常**不得**影響業務 API 或落庫(ingest metrics 埠起不起來只記 log、續跑消費迴圈)。

## 3. 接 Prometheus / Grafana

本倉庫交付的是**服務端指標 + 告警規則**;Prometheus 部署本身**待客戶提供,或由後續
Helm 加 `ServiceMonitor` 自動接線(G13 後續)**。最小接法:

1. **抓取設定**(客戶 `prometheus.yml`,job 名對齊 compose 服務名):

   ```yaml
   scrape_configs:
     - job_name: fleetsvc
       static_configs: [{ targets: ["fleetsvc:8091"] }]
     - job_name: missionsvc
       static_configs: [{ targets: ["missionsvc:8092"] }]
     - job_name: logsvc
       static_configs: [{ targets: ["logsvc:8090"] }]
     - job_name: ingest
       static_configs: [{ targets: ["ingest:9090"] }]
   ```

2. **載入告警規則**:把 [cloud/deploy/observability/alert-rules.yaml](../../../cloud/deploy/observability/alert-rules.yaml)
   放進 `rule_files:`,並接 Alertmanager 通知。

   ```yaml
   rule_files:
     - /etc/prometheus/rules/alert-rules.yaml
   ```

3. **Grafana**:倉庫已有 TimescaleDB 資料源與飛行看板
   ([cloud/deploy/compose/grafana](../../../cloud/deploy/compose/grafana));上述 Prometheus 指標的
   SLO/延遲/錯誤率儀表板 **⏳ 待補**(可由 job 標籤直接建 RED 面板)。

> **接線邊界(誠實標註)**:compose 與 Helm 的 scrape/ServiceMonitor 接線**不在本 PR**
> (由部署主流程另補,避免與進行中的 Helm PR 衝突)。本 PR 只保證**服務端已暴露指標**
> 與**規則檔可用**;客戶當下即可用上方 static_configs 手動抓取驗證。

## 4. 錯誤預算與回應

- 可用性 99.5%/30 天 ≈ **每月約 3h39m** 允許停機;耗盡則凍結非必要變更、優先修穩定性。
- `critical`(ServiceDown / IngestDbWriteFailureRate / TelemetryIngestionStalled)= 立即處置;
  `warning`(5xx / p95 延遲 / 積壓)= 當班觀察、趨勢惡化再升級。
- 對應排障步驟見 [deployment-runbook.md](deployment-runbook.md) 的健康檢查與 compose 探活。

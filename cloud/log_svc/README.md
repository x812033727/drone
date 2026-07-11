# log-svc — ULog 回收服務(Phase 0 雛形)

對 [docs/20-software/cloud-fleet.md](../../docs/20-software/cloud-fleet.md) 的
log-svc「ULog 自動上傳與解析」。FastAPI + uvicorn,隨
[cloud/deploy/compose](../deploy/compose/docker-compose.yml) 起(服務名 `logsvc`,
宿主埠 `127.0.0.1:${LOGSVC_PORT:-8090}`)。

資料流(與 drone-agent 的 ULog 自動回收閉環,見
[onboard/drone_agent/README.md](../../onboard/drone_agent/README.md)):

```
drone-agent(disarm 觸發)→ POST /api/v1/logs/{drone_id}(multipart)
  → 存 /data/ulog/{drone_id}/{UTC 時戳}_{原檔名}(named volume ulog-archive)
  → 背景 subprocess 跑 tools/ulog_report.py → 全文存同名 .report.txt
  → 摘要落 DB 表 flight_logs(report_ok + 前 500 字 + 異常規則條目 alerts)
  → Grafana「飛行日誌」面板(alerts 有值紅底)
```

alerts 欄 = ulog_report「⚠ 異常提示」區段逐條解析(振動超標、電壓低垂、
GPS 品質),是 cloud-fleet.md §3「異常規則自動開維保單」的 Phase 0 雛形:
先落庫上看板,開單流程屬 Phase 1。

## API

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/v1/logs/{drone_id}` | multipart `file` 上傳 ULog;201 回存檔名與大小,報告在背景跑 |
| GET | `/api/v1/logs/{drone_id}` | 該機回收清單(近 100 筆 JSON) |
| GET | `/healthz` | 探活(含 DB SELECT 1;compose healthcheck 用) |

報告失敗(非法 ULog / 崩潰 / 逾時 300 s)**不擋回收**:檔案照存、
`report_ok=false` 照落庫,壞檔在看板浮現。`drone_id` 與原檔名只取
basename,拒絕路徑跳脫。

Phase 0 邊界(Phase 1 再補):無認證(同 broker 的內網豁免,見
docs/20-software/security.md §8)、異常規則自動開維保單、簽章與保存年限
(firmware.md §6)、物件儲存(現為 named volume)。

## 本機驗證

```bash
cd cloud/deploy/compose && docker compose up -d --build --wait
echo x > /tmp/fake.ulg
curl -F "file=@/tmp/fake.ulg" http://localhost:8090/api/v1/logs/dev-1
curl http://localhost:8090/api/v1/logs/dev-1   # list;report_ok=false(非法 ULog)
```

# ingest — Phase 0 遙測落庫服務

> **定位**:Phase 0 雛形(Python,~100 行)。Phase 1 由 Go 裝置閘道(mTLS、裝置註冊,見 [cloud/README.md](../README.md))取代;wire format 是 [interfaces/proto](../../interfaces/README.md) 契約,語言汰換不影響機上端。

訂閱 `fleet/+/telemetry` 與 `fleet/+/mission/progress`(proto3 JSON),解回 proto 後寫入 TimescaleDB。壞 payload 記 log 丟棄;MQTT 斷線自動重連。

## 跑法

正常情況由 [cloud/deploy/compose](../deploy/compose/docker-compose.yml) 帶起。單獨開發:

```bash
pip install -r requirements.txt
pip install -e ../../interfaces/proto/gen/python   # 契約生成碼
MQTT_HOST=localhost PG_DSN=postgresql://drone:dronedev@localhost:5432/drone \
  python -m ingest.main
```

測試(不需 MQTT/DB):

```bash
pytest tests -q
```

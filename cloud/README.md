# cloud — 雲端機隊管理平台

> 規劃依據:[docs/20-software/cloud-fleet.md](../docs/20-software/cloud-fleet.md)

## 結構(規劃)

```
cloud/
├── gateway/        # 裝置閘道:mTLS 終結、MQTT(EMQX/NATS)、裝置註冊(Go)
├── fleet-svc/      # 機隊/裝置/韌體版本管理(Go)
├── mission-svc/    # 任務/航線/排程(Go)
├── log-svc/        # ULog 解析與異常規則(Python,複用 tools/ulog_report 核心)
├── media/          # WebRTC SFU 部署設定(LiveKit 級)
├── web/            # Web 指揮中心(React + MapLibre)
└── deploy/         # Helm charts(雲廠商中立;私有部署交付物)
```

## 原則

- **雲廠商中立**:K8s + S3 相容儲存 + PostgreSQL/PostGIS + 時序 DB;私有部署是產品賣點
- 飛行安全不依賴雲端:斷線時機上自主,雲端只做監控/派遣/資料沉澱
- Phase 0 最小目標:單一 compose 檔跑起 MQTT broker + 簡易遙測落庫 + Grafana 看板;
  任務下行以 CLI 工具([tools/dispatch_mission.py](../tools/dispatch_mission.py) 發
  `fleet/{drone_id}/cmd/mission`)代替 mission-svc(Phase 0 內網豁免:anonymous
  broker、無 TLS/ACL,見 [security.md §8](../docs/20-software/security.md))

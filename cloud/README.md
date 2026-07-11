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

## 影像錄存回放(S21,Phase 0 邊界)

compose 內的 `mediamtx` 服務(官方 image v1.12.3)常駐收 RTSP 推流並
fMP4 錄存(1 s part / 15 min 分段 / 72 h 自動清理,volume
`mediamtx-recordings`),回放走 MediaMTX playback API
(`GET :9996/list?path=stream`、`GET :9996/get?path=stream&start=…&duration=…`)。
常駐棧只收 RTSP + 錄存 + 回放(rtmp/hls/srt/webrtc 全關);回放/管理 API
只綁 loopback(內網豁免同上)。WebRTC 直播上雲(media/ SFU)是 Phase 1。
煙霧驗證:[deploy/compose/video_smoke.sh](deploy/compose/video_smoke.sh)
(本地/CI 共用;本地請帶隔離埠 `RTSP_PORT/PLAYBACK_PORT/MTX_API_PORT`
與獨特 `COMPOSE_PROJECT`)。機上推流端見
[onboard/video_pipeline](../onboard/video_pipeline/README.md)
(`sender.py --source test|v4l2:/dev/videoN`)。

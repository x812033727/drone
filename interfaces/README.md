# interfaces — 介面契約(單一事實來源)

機上 / 地面站 / 雲端三方共用的協議定義,**契約先行、獨立版本化**,三方 codegen 取用。

```
interfaces/
├── mavlink/        # 自訂 MAVLink dialect XML(酬載狀態、噴灑遙測、電池詳情)
├── proto/          # Protobuf schema(機-雲遙測與指令:MQTT/gRPC 用)
└── payload/        # 酬載描述檔 schema(QR-S/QR-L 介面的 EEPROM 內容定義)
```

## 規則

1. 任何跨端資料結構改動先改這裡,PR 需標註影響方(firmware / onboard / gcs / cloud)
2. Schema 版本語意化(SemVer);破壞性變更需提供相容期(機隊 OTA 是分批的,
   雲端必須同時支援 N 與 N-1 版)
3. MAVLink dialect 基於 upstream common.xml 擴充,message ID 使用私有區段(24150–24199 級)

## proto — 機-雲遙測與任務契約(v0.1.0)

Protobuf 為契約本體。**Phase 0 線上傳輸走 proto3 JSON mapping**(除錯友善,
`mosquitto_sub` 直接可讀),Phase 1 切換 binary(schema 不變,只換編碼)。

### 訊息清單(package `drone.v1`)

| 訊息 | 檔案 | 用途 |
|------|------|------|
| `TelemetrySummary` | `proto/drone/v1/telemetry.proto` | 機上 1 Hz 遙測摘要(位置/姿態/電池/模式/健康) |
| `Waypoint` / `MissionPlan` | `proto/drone/v1/mission.proto` | 航點與任務計畫(雲端 → 機上) |
| `MissionProgress` | `proto/drone/v1/mission.proto` | 任務進度事件(含 `State` 狀態機) |

### MQTT 主題約定

| 主題 | 訊息 | 方向 | 頻率 / QoS |
|------|------|------|-----------|
| `fleet/{drone_id}/telemetry` | `TelemetrySummary` | 機 → 雲 | 1 Hz,QoS 1 |
| `fleet/{drone_id}/mission/progress` | `MissionProgress` | 機 → 雲 | 事件觸發,QoS 1 |
| `fleet/{drone_id}/cmd/mission` | `MissionPlan` | 雲 → 機 | 事件觸發,QoS 1(已實作;Phase 0 內網豁免見下) |

> `cmd/mission` 下行已於 Phase 0 實作(drone_agent 訂閱、mission_exec 執行、
> `tools/dispatch_mission.py` 派遣)。**Phase 0 安全豁免**:broker 為 anonymous、
> 無 TLS/ACL——內網任何人可對任何機派任務,屬
> [security.md §8](../docs/20-software/security.md) 明列的已知狀態,僅限開發內網;
> Phase 1 起 mTLS + 裝置憑證 + 主題 ACL 才對外。

### SemVer 規則

- **MAJOR**(破壞性):刪欄位、改欄位編號/型別、改語意 → 開新 package(`drone.v2`),
  與 `drone.v1` 並行一個相容期
- **MINOR**:加欄位、加訊息、加 enum 值(proto3 天然向後相容)
- **PATCH**:註解、文件、codegen 工具鏈調整(wire format 不變)
- 版本號記錄於 `proto/gen/python/pyproject.toml`(目前 0.1.0)

### codegen(生成碼 commit 進版控)

```bash
pip install -r interfaces/proto/requirements-dev.txt   # 固定版 grpcio-tools
bash interfaces/proto/generate.sh                       # 產出至 proto/gen/python/drone/v1/
```

生成的 Python 套件(distribution 名 `drone-proto`)可直接安裝使用;
import 路徑刻意與 proto package 一致(`drone.v1`):

```bash
pip install -e interfaces/proto/gen/python
```

```python
from drone.v1 import telemetry_pb2, mission_pb2
msg = telemetry_pb2.TelemetrySummary(drone_id="dev-001", battery_pct=87.5)
```

CI(`.github/workflows/proto.yml`)對 `interfaces/**` 的 PR 跑 `buf lint`(STANDARD),
並重跑 codegen 後 `git diff --exit-code interfaces/proto/gen/`,確保生成碼不漂移。
本地不強制裝 buf;lint 交給 CI 把關即可。

# interfaces — 介面契約(單一事實來源)

機上 / 地面站 / 雲端三方共用的協議定義,**契約先行、獨立版本化**,三方 codegen 取用。

```
interfaces/
├── mavlink/        # 自訂 MAVLink dialect XML(酬載狀態、噴灑遙測、電池詳情)——目錄骨架已建(見其 README),Phase 1 啟用
├── proto/          # Protobuf schema(機-雲遙測與指令:MQTT/gRPC 用)——Phase 0 已實作
└── payload/        # 酬載描述檔 schema(QR-S/QR-L 介面的 EEPROM 內容定義)——目錄骨架已建(見其 README),Phase 1 啟用
```

## 規則

1. 任何跨端資料結構改動先改這裡,PR 需標註影響方(firmware / onboard / gcs / cloud)
2. Schema 版本語意化(SemVer);破壞性變更需提供相容期(機隊 OTA 是分批的,
   雲端必須同時支援 N 與 N-1 版)
3. MAVLink dialect 基於 upstream common.xml 擴充,message ID 使用私有區段(24150–24199 級)

## proto — 機-雲遙測與任務契約(v0.6.0)

Protobuf 為契約本體。**Phase 0 線上傳輸走 proto3 JSON mapping**(除錯友善,
`mosquitto_sub` 直接可讀),Phase 1 切換 binary(schema 不變,只換編碼)。

### 訊息清單(package `drone.v1`)

| 訊息 | 檔案 | 用途 |
|------|------|------|
| `TelemetrySummary` | `proto/drone/v1/telemetry.proto` | 機上 1 Hz 遙測摘要(位置/姿態/電池/模式/健康;v0.3.0 新增 GPS 品質與垂直速度) |
| `Waypoint` / `MissionPlan` | `proto/drone/v1/mission.proto` | 航點與任務計畫(雲端 → 機上) |
| `MissionProgress` | `proto/drone/v1/mission.proto` | 任務進度事件(含 `State` 狀態機;v0.2.0 新增 `STATE_PAUSED`) |
| `MissionCommand` | `proto/drone/v1/mission.proto` | 任務控制命令 PAUSE/RESUME/ABORT(v0.2.0 新增,雲端 → 機上) |
| `FlightEvent` | `proto/drone/v1/events.proto` | 飛行事件 ARMED/DISARMED(v0.3.0 新增,armed 邊緣觸發;消費者:S20 ULog 回收、看板) |
| `SensorAttitude` / `SensorGps` / `SensorLocalPosition` | `proto/drone/v1/sensors.proto` | 高頻感測器流(v0.4.0 新增,S22;源 PX4 uXRCE-DDS /fmu/out/*,px4_mqtt_bridge 節流外發;`px4_timestamp_us` 為 PX4 boot-time 原始值非 epoch) |
| `DeviceHeartbeat` | `proto/drone/v1/device.proto` | 裝置心跳(v0.5.0 新增;agent 存活 + 軟韌體版本 + uptime,獨立於飛行遙測定期發，供看板「最後上線/版本」) |
| `FleetMission` | `proto/drone/v1/dispatch.proto` | 雲端派遣單(v0.6.0 新增;工單層,**不上線下發**;生命週期 CREATED/ASSIGNED/EXECUTING/COMPLETED/CANCELLED;供 mission-svc 派遣器與 Web 指揮中心共用) |
| `MissionAssignment` | `proto/drone/v1/dispatch.proto` | 指派事件(v0.6.0 新增;派遣單 ↔ drone_id 綁定與前置檢查結果,供多機調度審計與追溯) |

### MQTT 主題約定

| 主題 | 訊息 | 方向 | 頻率 / QoS |
|------|------|------|-----------|
| `fleet/{drone_id}/telemetry` | `TelemetrySummary` | 機 → 雲 | 1 Hz,QoS 1 |
| `fleet/{drone_id}/mission/progress` | `MissionProgress` | 機 → 雲 | 事件觸發,QoS 1 |
| `fleet/{drone_id}/events` | `FlightEvent` | 機 → 雲 | 事件觸發,QoS 1(v0.3.0;armed 邊緣,at-least-once,消費端容忍重複) |
| `fleet/{drone_id}/sensors/attitude` | `SensorAttitude` | 機 → 雲 | 5 Hz 預設,**QoS 0**(v0.4.0;高頻容失,與 1 Hz 摘要 QoS 1 區隔) |
| `fleet/{drone_id}/sensors/gps` | `SensorGps` | 機 → 雲 | 5 Hz 預設,**QoS 0**(v0.4.0;同上) |
| `fleet/{drone_id}/sensors/local_position` | `SensorLocalPosition` | 機 → 雲 | 5 Hz 預設,**QoS 0**(v0.4.0;同上) |
| `fleet/{drone_id}/heartbeat` | `DeviceHeartbeat` | 機 → 雲 | 30 s 預設,QoS 1(v0.5.0;agent 存活即發,獨立於遙測斷流) |
| `fleet/{drone_id}/cmd/mission` | `MissionPlan` | 雲 → 機 | 事件觸發,QoS 1(已實作;Phase 0 內網豁免見下) |
| `fleet/{drone_id}/cmd/mission_ctrl` | `MissionCommand` | 雲 → 機 | 事件觸發,QoS 1(proto3 JSON;**S23 已實作**:mission_exec 任務執行期間直訂,`tools/dispatch_mission.py --ctrl` 發送;ABORT 終態以 `STATE_FAILED` 承載,契約無 ABORTED) |

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
- 版本號記錄於 `proto/gen/python/pyproject.toml`(目前 0.5.0)
  - v0.2.0 = MINOR:新增 `MissionCommand` 訊息與
    `MissionProgress.State.STATE_PAUSED = 6`,純增量
  - v0.3.0 = MINOR:`TelemetrySummary` 新增 `satellites` / `gps_fix_type` /
    `hdop` / `vertical_speed_ms` 四欄(編號 13–16 續用);新增 `FlightEvent`
    訊息(`events.proto`)與主題 `fleet/{drone_id}/events`,純增量
  - v0.4.0 = MINOR:新增 `sensors.proto`(`SensorAttitude` / `SensorGps` /
    `SensorLocalPosition`)與主題 `fleet/{drone_id}/sensors/*`(5 Hz,QoS 0),
    純增量;S22 DDS→MQTT 橋(onboard/ros2_ws/src/px4_mqtt_bridge)外發、
    cloud/ingest 落庫三張 hypertable
  - v0.5.0 = MINOR:新增 `device.proto`(`DeviceHeartbeat`)與主題
    `fleet/{drone_id}/heartbeat`(30 s,QoS 1),純增量;drone_agent 定期外發、
    cloud/ingest 落庫 `device_heartbeat` 表(裝置存活/版本觀測性)
  - v0.6.0 = MINOR:新增 `dispatch.proto`(`FleetMission` / `MissionAssignment`)
    雲端任務派遣工單契約(契約草案見
    [cloud-fleet.md §6](../docs/20-software/cloud-fleet.md)),純增量。
    工單層,**不上線下發**——機上契約不變,仍只認 `MissionPlan` /
    `MissionProgress` / `MissionCommand`;`FleetMission.mission_id` 貫穿派遣單與
    機上執行,為端到端追溯鍵;去重/冪等沿用 QoS 1 at-least-once 既定語意
    (cloud-fleet §6.4)。消費端(mission-svc 派遣器、Web 指揮中心)後續接。

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

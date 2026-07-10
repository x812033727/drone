# drone_agent — 遙測上雲常駐服務(Phase 0 雛形)

機載電腦上的**非 ROS** 常駐服務:純 MAVSDK 連 PX4,把關鍵遙測彙整成
`drone.v1.TelemetrySummary`(契約:[interfaces/proto/drone/v1/telemetry.proto](../../interfaces/proto/drone/v1/telemetry.proto)),
以 1 Hz、QoS 1 發佈到 MQTT 主題 `fleet/{drone_id}/telemetry`。
Phase 0 線上編碼為 proto3 JSON mapping(`mosquitto_sub` 直接可讀),Phase 1 切 binary。

由 [tools/telemetry_monitor.py](../../tools/telemetry_monitor.py) 重構而來:
各 `watch_*` 訂閱協程改為寫入共享 `TelemetryState`(只存最新快照),
publisher 以固定頻率取樣組包 —— 純函式 `snapshot()` 與 I/O 分離,單測不需 SITL/MQTT。

## 結構

```
drone_agent/
├── state.py        # TelemetryState + MAVSDK 各流訂閱協程(position/heading/velocity/
│                   #   flight_mode/armed/battery/health)
├── publisher.py    # snapshot() 純函式 + publish_loop()(MQTT 斷線自動重連)
└── main.py         # CLI 進入點
```

## 跑法

安裝依賴(repo 根目錄下):

```bash
pip install -r onboard/drone_agent/requirements.txt
pip install -e interfaces/proto/gen/python        # 契約生成碼 drone-proto
```

### SITL(開發)

```bash
# 1. PX4 SITL(任一方式,offboard 埠 14540)+ 本機 mosquitto
# 2. 於 onboard/drone_agent/ 下:
python -m drone_agent.main --drone-id dev-1
```

### 實機(Jetson,經序列埠數傳或 Ethernet)

```bash
python -m drone_agent.main --url serial:///dev/ttyUSB0:57600 \
    --mqtt-host <雲端 broker> --drone-id qs-0001
```

CLI 參數:`--url`(MAVSDK 連線字串,預設 `udpin://0.0.0.0:14540`)、
`--mqtt-host`(預設 localhost)、`--mqtt-port`(預設 1883)、
`--drone-id`(必填)、`--rate`(預設 1 Hz)。

## 行為約定

- **MQTT 斷線**:自動重連;重連期間遙測**直接丟棄,不緩存**(Phase 0 不做補傳)。
- **尚未收到某遙測流**:對應欄位維持 proto3 預設值(0 / 空字串 / false),
  `unix_time_ms` 一律取系統時間。
- **MAVSDK 訂閱異常結束**:整個行程結束,交給 systemd 重啟(Phase 0 策略)。

## 與 onboard 安全邊界的關係

[onboard/README.md](../README.md) 的安全邊界規範感知模組只對 PX4 發速度限制與
setpoint 修正。drone_agent 比這更保守:**唯讀遙測、不對 PX4 發任何指令**,
崩潰或斷線只影響雲端可見性,不影響飛行。後續指令下行(`fleet/{id}/cmd/mission`,
Phase 0 預留)進場時,將經 mission_exec 轉譯而非由本服務直接下 MAVLink。

## 測試

```bash
pytest onboard/drone_agent/tests -q
```

# drone_agent — 遙測上雲 + 任務下行常駐服務(Phase 0 雛形)

機載電腦上的**非 ROS** 常駐服務:純 MAVSDK 連 PX4,把關鍵遙測彙整成
`drone.v1.TelemetrySummary`(契約:[interfaces/proto/drone/v1/telemetry.proto](../../interfaces/proto/drone/v1/telemetry.proto)),
以 1 Hz、QoS 1 發佈到 MQTT 主題 `fleet/{drone_id}/telemetry`;同時訂閱
`fleet/{drone_id}/cmd/mission` 接受雲端任務派遣(見下「雲端派遣」節)。
Phase 0 線上編碼為 proto3 JSON mapping(`mosquitto_sub` 直接可讀),Phase 1 切 binary。

由 [tools/telemetry_monitor.py](../../tools/telemetry_monitor.py) 重構而來:
各 `watch_*` 訂閱協程改為寫入共享 `TelemetryState`(只存最新快照),
publisher 以固定頻率取樣組包 —— 純函式 `snapshot()` 與 I/O 分離,單測不需 SITL/MQTT。

## 結構

```
drone_agent/
├── state.py        # TelemetryState + MAVSDK 各流訂閱協程(position/heading/velocity/
│                   #   flight_mode/armed/battery/health);每次更新後 touch() 記錄取樣時間
├── publisher.py    # snapshot()/is_stale() 純函式 + publish_loop()(MQTT 斷線自動重連、
│                   #   遙測斷流暫停上報)
├── command.py      # cmd/mission 訂閱 + mission_exec 子程序管理(單一任務互斥、
│                   #   逾時 kill、輸出收進 log、異常補發 FAILED)
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
`--drone-id`(必填)、`--rate`(預設 1 Hz)、
`--stale-timeout`(遙測斷流判定秒數,預設 5)、
`--mavsdk-address`(`host:port`,連既有 mavsdk_server,見下)、
`--enable-cmd` / `--no-enable-cmd`(雲端派遣,**預設開**,見下)、
`--cmd-timeout`(任務子程序逾時秒數,預設 900)。

### 同機多程序(共用 mavsdk_server)

MAVSDK Python 每個 `System()` 預設會自行 spawn 一個 mavsdk_server(佔 gRPC 埠
50051,且會綁 `--url` 的飛控埠)。同一台機器上多個 MAVSDK 程序(如 drone_agent
與 mission_exec)併跑時,**只能一個程序 spawn,其他程序必須顯式共用**,否則後起
的程序綁埠失敗、gRPC client 可能連上別人的 server 而不自知:

```bash
# 程序 A:自行 spawn(佔 50051 與飛控埠 14540)
python -m drone_agent.main --drone-id dev-1

# 程序 B(同機):顯式共用 A 的 server,不自行 spawn
python -m drone_agent.main --mavsdk-address localhost:50051 --drone-id dev-1
```

給 `--mavsdk-address` 時不會啟動內嵌 server,飛控連線由既有 server 決定,
`--url` 不生效。

## 雲端派遣(cmd/mission 下行)

`--enable-cmd`(**預設開**,關閉用 `--no-enable-cmd`)時訂閱
`fleet/{drone_id}/cmd/mission`(QoS 1),payload 為
[`drone.v1.MissionPlan`](../../interfaces/proto/drone/v1/mission.proto) 的
proto3 JSON。雲端側以 [tools/dispatch_mission.py](../../tools/dispatch_mission.py) 派遣:

```bash
python tools/dispatch_mission.py --drone-id dev-1 \
    --mission onboard/mission_exec/missions/demo_square.json --wait
```

收到任務後的流程(細節見 [drone_agent/command.py](drone_agent/command.py)):

1. **Parse 級把關**:合法 MissionPlan JSON + `mission_id` 非空;未過只記 log
   (拿不到可信 mission_id,無從對應事件)。語意驗證(waypoints 非空、經緯度
   範圍)由 mission_exec 載入任務檔時把關,不重複實作。
2. **單一任務互斥**:已有任務子程序存活 → 拒絕,發 `STATE_FAILED` 進度事件
   (Phase 0 不做佇列)。
3. **子程序執行**:任務寫入暫存檔,以
   `python -m mission_exec.main --mission <暫存檔> --mavsdk-address localhost:50051
   --mqtt-host … --drone-id …` 執行。**`--mavsdk-address` 必給**:agent 已 spawn
   mavsdk_server(佔 14540 與 gRPC 50051),mission_exec 顯式共用同一 server,
   絕不能自行 spawn(會搶飛控埠);agent 自己連既有 server 時則透傳同一位址。
   進度事件(`RECEIVED → … → COMPLETED/FAILED`)由 mission_exec 直接發
   `fleet/{drone_id}/mission/progress`。
4. **回收**:子程序 stdout/stderr 逐行收進 agent log;逾 `--cmd-timeout`
   (預設 900 秒)kill;結束碼記錄——`exit 1` mission_exec 已自行發過 FAILED,
   其餘非零(驗證錯 `2`、逾時 kill)由 agent 補發 `STATE_FAILED`。

**Phase 0 安全豁免**(對齊 [security.md §8](../../docs/20-software/security.md)
分階段落地表,明列的已知狀態):broker 為 anonymous、無 TLS/ACL——**開發內網上
任何人都能對任何機派任務**,僅限開發內網部署。機上把關只防呆、不防敵:
訂閱主題寫死為自身 drone_id(不收別機指令)+ payload Parse 把關。
Phase 1 起 mTLS + 裝置憑證 + 主題 ACL 才對外。

## 行為約定

- **MQTT 斷線**:自動重連;重連期間遙測**直接丟棄,不緩存**(Phase 0 不做補傳)。
- **尚未收到某遙測流**:對應欄位維持 proto3 預設值(0 / 空字串 / false)。
- **`unix_time_ms` = 取樣時間**(契約語意):取「最後一次任一流更新」的
  wall-clock 時間,而非發佈當下時間;完全沒收過任何流時退回當下系統時間
  (此時 `health_all_ok` 必為 false,雲端可辨識)。
- **遙測斷流即停止上報**:飛控鏈路中斷後 MAVSDK 流可能靜默(不結束、不拋錯),
  若照常發布會變成「時間戳全新、內容凍結」的殭屍遙測。故全部流超過
  `--stale-timeout`(預設 5 秒)無更新時**跳過發布**並記 WARNING(狀態轉換時
  各記一次,不逐秒刷);恢復更新後自動恢復發布。雲端據此以「訊息停止」判定失聯。
- **MAVSDK 訂閱異常結束**:整個行程結束,交給 systemd 重啟(Phase 0 策略)。

## 與 onboard 安全邊界的關係

[onboard/README.md](../README.md) 的安全邊界規範感知模組只對 PX4 發速度限制與
setpoint 修正。drone_agent 本體比這更保守:**唯讀遙測、自身不對 PX4 發任何指令**,
崩潰或斷線只影響雲端可見性,不影響飛行。指令下行(`fleet/{id}/cmd/mission`)
一律經 mission_exec 子程序轉譯下發(受 PX4 驗證與失效保護約束),
本服務不直接下 MAVLink——agent 崩潰時進行中的任務子程序不受牽連,
PX4 端任務照常由飛控自主完成。

## 測試

```bash
pytest onboard/drone_agent/tests -q
```

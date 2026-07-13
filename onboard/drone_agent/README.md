# drone_agent — 遙測上雲 + 任務下行常駐服務(Phase 0 雛形)

機載電腦上的**非 ROS** 常駐服務:純 MAVSDK 連 PX4,把關鍵遙測彙整成
`drone.v1.TelemetrySummary`(契約:[interfaces/proto/drone/v1/telemetry.proto](../../interfaces/proto/drone/v1/telemetry.proto)),
以 1 Hz、QoS 1 發佈到 MQTT 主題 `fleet/{drone_id}/telemetry`;armed 邊緣
(解鎖/上鎖)另以 `drone.v1.FlightEvent` 發佈到 `fleet/{drone_id}/events`
(事件觸發,QoS 1,見下「飛行事件」節);另以 `drone.v1.DeviceHeartbeat`
定期(預設 30 s,QoS 1)發佈到 `fleet/{drone_id}/heartbeat`——證明 agent
程序存活與軟韌體版本,獨立於飛行遙測是否斷流(雲端據此區分「機掛了」與
「鏈路掛了」);同時訂閱
`fleet/{drone_id}/cmd/mission` 接受雲端任務派遣(見下「雲端派遣」節)。
Phase 0 線上編碼為 proto3 JSON mapping(`mosquitto_sub` 直接可讀),Phase 1 切 binary。

由 [tools/telemetry_monitor.py](../../tools/telemetry_monitor.py) 重構而來:
各 `watch_*` 訂閱協程改為寫入共享 `TelemetryState`(只存最新快照),
publisher 以固定頻率取樣組包 —— 純函式 `snapshot()` 與 I/O 分離,單測不需 SITL/MQTT。

## 結構

```
drone_agent/
├── state.py        # TelemetryState + MAVSDK 各流訂閱協程(position/heading/velocity/
│                   #   flight_mode/armed/battery/health/gps_info/raw_gps);每次更新後
│                   #   touch() 記錄取樣時間;armed 邊緣排入 pending_events
├── publisher.py    # snapshot()/is_stale()/flight_event() 純函式 + publish_loop()
│                   #   (MQTT 斷線自動重連、遙測斷流暫停上報、飛行事件上報)
├── log_uploader.py # S20 ULog 自動回收:disarm 觸發下載最新日誌並上傳 log-svc
│                   #   (選配 --log-svc-url;互斥/逾時/失敗即放棄)
├── command.py      # cmd/mission 訂閱 + mission_exec 子程序管理(重複投遞去重、
│                   #   單一任務互斥、逾時 kill、輸出收進 log、非零結束補發 FAILED)
├── ota.py          # cmd/ota 訂閱 + 機載 OTA 代理(G23,預設關):下載(斷點續傳)→
│                   #   SHA-256+Ed25519 驗簽 → A/B slot 套用 → 健康檢查 → 提交/回滾 →
│                   #   進度回報;軟體套件版,實體 firmware 代燒屬 Phase 3(見下)
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
`--cmd-timeout`(任務子程序逾時秒數,預設 900)、
`--log-svc-url`(ULog 自動回收,**預設關**,見下)、
`--log-download-timeout`(ULog 下載逾時秒數,預設 300)、
`--enable-ota` / `--no-enable-ota`(OTA 機載代理,**預設關**,見下)、
`--ota-work-dir` / `--ota-root` / `--ota-max-retries`(OTA slot/暫存/續傳)。

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

## 遙測欄位(v0.3.0 擴充)

TelemetrySummary 於 v0.3.0 新增四欄(來源皆 MAVSDK telemetry):

| 欄位 | 來源 | 說明 |
|------|------|------|
| `satellites` | `gps_info().num_satellites` | 可視衛星數 |
| `gps_fix_type` | `gps_info().fix_type`(enum 名) | 如 `FIX_3D`、`RTK_FIXED` |
| `hdop` | `raw_gps().hdop` | 水平精度因子 |
| `vertical_speed_ms` | `velocity_ned().down` 反號 | 垂直速度,向上為正 |

## 飛行事件(events 上行)

armed 遙測流的邊緣(False→True = 解鎖、True→False = 上鎖)觸發一筆
[`drone.v1.FlightEvent`](../../interfaces/proto/drone/v1/events.proto)
(EVENT_ARMED / EVENT_DISARMED),發佈到 `fleet/{drone_id}/events`(QoS 1,
proto3 JSON)。消費者:雲端看板(飛行事件表)、S20 ULog 回收(以 DISARMED 觸發)。

- **啟動後第一筆 armed 值不算邊緣**(只是初始狀態,避免 agent 重啟誤發事件)。
- 事件與遙測共用同一 MQTT 連線,由發佈迴圈每輪(1/rate 秒)清空佇列;
  斷線期間事件**留在佇列不丟**,重連後補發 —— 語意 **at-least-once**,
  消費端需容忍重複(與 mission progress 終態事件同約定)。
- 事件不受遙測斷流跳發影響(armed 邊緣本身就是流有更新的證據)。

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
2. **重複投遞去重**:QoS 1 為 at-least-once,同一 mission_id 可能重複到達。
   與**執行中**任務同 id → 重複投遞,只記 log 忽略(不發 FAILED,避免誤殺
   進行中任務的終態);與**最近一筆已終結**任務同 id → 遲到的重複投遞,
   同樣忽略(防已完成後 dup 重飛)。
3. **單一任務互斥**:新 mission_id 但已有任務子程序存活 → 拒絕,發
   `STATE_FAILED` 進度事件(帶新任務的 mission_id;Phase 0 不做佇列)。
4. **子程序執行**:任務寫入暫存檔,以
   `python -m mission_exec.main --mission <暫存檔> --mavsdk-address localhost:50051
   --mqtt-host … --drone-id …` 執行。**`--mavsdk-address` 必給**:agent 已 spawn
   mavsdk_server(佔 14540 與 gRPC 50051),mission_exec 顯式共用同一 server,
   絕不能自行 spawn(會搶飛控埠);agent 自己連既有 server 時則透傳同一位址。
   進度事件(`RECEIVED → … → COMPLETED/FAILED`)由 mission_exec 直接發
   `fleet/{drone_id}/mission/progress`。spawn 失敗不會拖垮 agent:log 後
   盡力補發 `STATE_FAILED` 並清暫存檔,command loop 照常收下一筆。
5. **回收**:子程序 stdout/stderr 逐行收進 agent log;逾 `--cmd-timeout`
   (預設 900 秒)kill;**非零結束碼一律由 agent 補發 `STATE_FAILED`**。
   `exit 1` 不可信任為「mission_exec 已自行發過 FAILED」——任何未處理例外
   (MQTT 連線失敗、import 錯等)也會 exit 1 且 FAILED 從未發出,故不做特例。
   終態事件因此為 **at-least-once**:同一任務的終態可能重複,消費端以
   **首個終態為準**(dispatch_mission 收到第一個終態即退出;DB 落庫多一列
   無害)。dispatch_mission 的 `--timeout` 預設 960 秒即對應此逾時
   (> 900,等得到逾時 kill 後補發的 FAILED)。

**Phase 0 安全豁免**(對齊 [security.md §8](../../docs/20-software/security.md)
分階段落地表,明列的已知狀態):broker 為 anonymous、無 TLS/ACL——**開發內網上
任何人都能對任何機派任務**,僅限開發內網部署。機上把關只防呆、不防敵:
訂閱主題寫死為自身 drone_id(不收別機指令)+ payload Parse 把關。
Phase 1 起 mTLS + 裝置憑證 + 主題 ACL 才對外。

**互斥與逾時是「子程序」層級,不是「飛行」層級**:kill 子程序或補發 FAILED
只代表 mission_exec 不在場,**飛控可能仍在執行已上傳的任務**(PX4 自主續飛,
這正是 agent 崩潰不牽連飛行的設計);重派前操作者須以遙測確認機況(降落/
Hold/RTL)再決定。同理,`COMPLETED` 於**最後一個航點完成時**即發出,RTL
返航段不屬任務進度——此時互斥已釋放,新任務可被接受,操作者需自行留意
返航中的機體。

## OTA 機載代理(G23,cmd/ota 下行,選配)

`--enable-ota`(**預設關**)時訂閱 `fleet/{drone_id}/cmd/ota`(QoS 1),接受雲端
軟體套件 OTA 指令。落地 [docs/20-software/ota.md](../../docs/20-software/ota.md) 的
**機載代理側,以軟體套件/設定 OTA 的可驗證版**實作;細節與流程見
[drone_agent/ota.py](drone_agent/ota.py) 模組 docstring。

指令與進度**皆走 JSON**(events.proto/mission.proto 無 OTA 型別,刻意不動 proto,
與憑證告警 alerts 同策略)。指令 payload 範例(install):

```json
{
  "action": "install", "update_id": "ota-2026-07-13-01", "component": "onboard",
  "version": "1.4.0", "url": "https://mirror/onboard-1.4.0.tar.gz",
  "size": 12345678, "sha256": "<hex>", "signature": "<base64 Ed25519 sig>"
}
```

收到 install 後的流程:

1. **下載(斷點續傳)**:寫 `.part` 暫存,以已收位元組為續傳起點,斷線用 HTTP Range
   自斷點續傳、不重頭來(ota.md §1);HTTPS 沿用機-雲既有裝置憑證(mTLS,MQTT_TLS_*)。
2. **驗簽(收檔後驗簽點,ota.md §4)**:先 SHA-256 校驗,再 **Ed25519** 公鑰驗簽;
   **任一不過一律拒絕套用**(REJECTED),不寫入 slot。簽章對象為套件的 SHA-256 摘要
   (32 bytes);公鑰來源 env `OTA_PUBLIC_KEY`(Ed25519 PEM 檔)——**未設公鑰 = 無法
   驗簽 = 一律拒絕安裝(fail-closed)**,釋出私鑰存離線 HSM(security.md §4)。
3. **A/B slot 套用(ota.md §3)**:以 `{ota-root}/slots/{a,b}` + `current` symlink 模擬
   A/B 分區——驗簽套件寫入**非活動 slot**,原子切換 `current` 指向它。
4. **健康檢查 + 自動回滾(ota.md §3)**:套用後跑健康檢查;失敗即把 `current` 切回舊
   slot(回滾),回報 `ROLLED_BACK`。預設健康檢查僅驗套件落地(佔位),**接真實探測
   (關鍵服務/DDS/雲連線)為 Phase 1 TODO**。
5. **進度回報**:各階段(RECEIVED→DOWNLOADING→VERIFYING→APPLYING→HEALTH_CHECK→
   COMPLETED / REJECTED / FAILED / ROLLED_BACK)發 JSON 到 `fleet/{drone_id}/ota/progress`
   (QoS 1),語意 **at-least-once**(消費端以 `update_id`+`state` 去重)。

暫停/回滾(ota.md §6):`pause`/`resume` 設清暫停旗標(進行中的下載於下一塊中止、
保留 `.part` 續傳段);`rollback` 把 `current` 切回前一 slot。**單一更新互斥**、重複
投遞去重(對齊 cmd/mission)。

CLI:`--enable-ota` / `--no-enable-ota`、`--ota-work-dir`(下載暫存)、`--ota-root`
(A/B slot 根)、`--ota-max-retries`(斷線續傳重試上限,預設 5);env 對應
`OTA_PUBLIC_KEY` / `OTA_WORK_DIR` / `OTA_ROOT`。

### 實作現況 vs Phase 3 硬體代燒(誠實說明)

本模組是 ota.md **機載代理側「程式可達部分」的可驗證實作**,標的為
**軟體套件/設定**,以目錄 slot + symlink **模擬** A/B 分區來驗證代理側的
下載→驗簽→套用→健康檢查→回滾→回報**編排邏輯**。以下屬 **Phase 3**(實體硬體,
本環境不可達),於 [ota.py](drone_agent/ota.py) 對應位置以 `TODO` 標明,**尚未實作**:

| ota.md 項目 | 現況 |
|-------------|------|
| §2 飛控韌體雙 bank 交換 / Jetson 代燒(方案 A/B 實體 flash) | **Phase 3 TODO**(SlotManager.stage 只複製檔案,不 dd 分區、不 DFU) |
| §3 rootfs 分區實體寫入 + bootloader 啟動計數回退 | **Phase 3 TODO**(以 symlink 切換模擬「提交/回滾」) |
| §3 真實健康檢查(服務/DDS/雲連線) | **Phase 1 TODO**(default_health_check 為佔位,僅驗套件落地;可注入真檢查) |
| §5 相容性矩陣強制檢查(firmware×onboard×gcs×payload) | 未實作(屬 fleet-svc + 安裝前再驗,Phase 2) |
| §6 灰度 ring 編排 / 72h 觀察期 / 批次失敗率暫停 | 雲端編排面,未在機載代理實作(機載只做 pause/resume/rollback 指令端) |
| §1 差分更新(delta/OSTree/casync) | 未實作(Phase 2 評估) |
| §1 斷點續傳、§4 收檔驗簽、§3 A/B 套用+健康檢查回滾、進度回報、pause/resume/rollback | **已實作並單元測試涵蓋** |

安全註記:驗簽採 **Ed25519**(標準庫 `cryptography`,已為既有依賴生態);簽章失敗
與無公鑰皆 **fail-closed** 拒絕。**Phase 0/1 開發簽章金鑰**(ota.md §7:Phase 1「簽章鏈
仍用開發簽章」)——正式離線 HSM 簽章鏈與防降級(拒裝低於吊銷版本號)屬 Phase 2,
本模組尚未做版本吊銷比對。

## ULog 自動回收(S20 閉環,選配)

`--log-svc-url`(如 `http://localhost:8090`)啟用;**未給則整個功能停用**
(預設關,Phase 0 選配)。上鎖(DISARMED 邊緣)自動把最新飛行日誌收回雲端:

```
disarm → LogFiles.get_entries()(取 date 最新)→ MAVLink 下載到暫存
       → POST multipart {--log-svc-url}/api/v1/logs/{drone_id}(httpx)
       → log-svc 存檔 + 背景 ulog_report + 摘要落 flight_logs → Grafana「飛行日誌」
```

雲端側見 [cloud/log_svc/README.md](../../cloud/log_svc/README.md)。行為約定
(細節見 [drone_agent/log_uploader.py](drone_agent/log_uploader.py)):

- **全程獨立 task,絕不阻塞遙測**:disarm 回呼只 `create_task` 就返回。
- **單一回收互斥**:上傳進行中再次 disarm 忽略並記 log(不排隊)。
- **下載逾時**:MAVLink 下載加總逾 `--log-download-timeout`(預設 300 秒)
  放棄並記 log——SITL 日誌小,實機大檔經數傳可能極慢,視鏈路調大。
- **失敗即放棄**:下載/上傳失敗記 log 後放棄,**無重試佇列**(Phase 0;
  日誌仍留在飛控 SD 卡,可事後以 `tools/flight_ops/archive_flight.py` 人工歸檔)。

## 行為約定

- **MQTT 斷線(離線緩衝 store-and-forward,G24)**:自動重連;**斷線期間遙測
  續存於有界環形緩衝**(`--telemetry-buffer-max`/env `TELEMETRY_BUFFER_MAX`,
  預設 600 筆 ≈ 1 Hz 十分鐘),重連後依原取樣順序 **FIFO 補發**(先發佈成功
  才 popleft,中途斷線的那筆重連補發 —— 語意 at-least-once,消費端需容忍重複)。
  緩衝滿了**丟最舊**並累計丟棄數(記 WARNING)。取樣(producer)與發佈
  (publish_loop)為兩個協程共用同一緩衝,故斷線不影響取樣。
- **尚未收到某遙測流**:對應欄位維持 proto3 預設值(0 / 空字串 / false)。
- **`unix_time_ms` = 取樣時間**(契約語意):取「最後一次任一流更新」的
  wall-clock 時間,而非發佈當下時間;完全沒收過任何流時退回當下系統時間
  (此時 `health_all_ok` 必為 false,雲端可辨識)。**離線補發保留原取樣時間**
  (快照在取樣當下即組好進緩衝),不會被補發當下的時間覆寫。
- **遙測斷流即停止取樣(與離線緩衝是兩件不同的事)**:飛控鏈路中斷後 MAVSDK
  **源**可能靜默(不結束、不拋錯),若照常取樣會變成「時間戳全新、內容凍結」
  的殭屍遙測。故全部流超過 `--stale-timeout`(預設 5 秒)無更新時 producer
  **跳過取樣(不進緩衝)**並記 WARNING(狀態轉換時各記一次);恢復更新後自動
  恢復。斷流=遙測**源**沒新資料(緩衝無意義);離線緩衝=遙測傳不出去(**源仍
  更新**,故要緩衝補發)—— 兩者不可混為一談。雲端據「訊息停止」判定失聯。
- **裝置憑證到期/輪換偵測(G22,僅 mTLS 模式)**:設了 `MQTT_TLS_CERT` 時每
  小時檢查裝置憑證,剩餘天數低於門檻(`--cert-warn-days`/env
  `CERT_EXPIRY_WARN_DAYS`,預設 30)即記 WARNING,並最佳努力發一筆**純 JSON**
  告警到 `fleet/{id}/alerts`(**契約外**的運維主題——events.proto 無憑證事件
  型別,故刻意不碰 proto)。憑證檔內容指紋(SHA-256)變化 → 記 INFO 提示已換
  憑證,實際套用交由既有斷線重連(重連即讀新檔)。憑證解析走標準庫 `ssl`,
  不新增依賴。明文模式(未設 `MQTT_TLS_CERT`)整個功能略過。
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

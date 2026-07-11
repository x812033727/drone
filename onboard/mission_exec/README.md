# mission_exec — 任務執行器(Phase 0 雛形)

> 對應規劃:[docs/20-software/companion-computer.md](../../docs/20-software/companion-computer.md)
> 的 mission_exec 模組(雲端任務 → MAVLink 任務轉譯、進度回報)。

接收 JSON 任務檔,經 MAVSDK 上傳 PX4 並執行,過程發布
[`drone.v1.MissionProgress`](../../interfaces/proto/drone/v1/mission.proto) 進度事件:

- **stdout 一定印**(每次狀態變化/航點推進一行)
- 有給 `--mqtt-host` 時同步發 MQTT 主題 `fleet/{drone_id}/mission/progress`(QoS 1,proto3 JSON)

## 任務檔格式

任務檔 = `drone.v1.MissionPlan` 的 **proto3 JSON mapping**,由
`google.protobuf.json_format.Parse` 解析,欄位天然受 proto 契約約束(未知欄位拒收)。
範例見 [missions/demo_square.json](missions/demo_square.json)(SITL 預設家點附近 ~100 m 方形
四航點,結束後 RTL):

```json
{
  "missionId": "demo-square-v1",
  "waypoints": [
    {"latDeg": 47.398642, "lonDeg": 8.545594, "relAltM": 20.0, "holdS": 0.0, "speedMs": 5.0}
  ],
  "rtlAfterLast": true
}
```

欄位映射(Waypoint → MAVSDK MissionItem):

| MissionPlan 欄位 | MissionItem | 備註 |
|---|---|---|
| `latDeg` / `lonDeg` | `latitude_deg` / `longitude_deg` | WGS84 |
| `relAltM` | `relative_altitude_m` | 相對起飛點 |
| `speedMs` | `speed_m_s` | 0 = 飛控預設(NaN) |
| `holdS` | `loiter_time_s` + `is_fly_through=False` | 0 = 直接通過(NaN / True) |
| `rtlAfterLast` | `set_return_to_launch_after_mission(True)` | **上傳前**設定(MAVSDK 僅對「下一次上傳」生效,上傳後才設完全無效) |

相機/雲台欄位 Phase 0 不使用(`CameraAction.NONE` / `VehicleAction.NONE` / NaN)。

## 跑法

```bash
# 安裝(S11 起為可安裝套件,依賴由 pyproject 帶入;drone-proto 為 repo 內
# 本地套件,需另行安裝)
pip install -e .
pip install -e ../../interfaces/proto/gen/python

# PX4 SITL(預設 udpin://0.0.0.0:14540)
python -m mission_exec.main --mission missions/demo_square.json --drone-id dev-1

# 指定連線與 MQTT 上報
python -m mission_exec.main --mission missions/demo_square.json \
    --url udpin://0.0.0.0:14540 --drone-id dev-1 \
    --mqtt-host localhost --mqtt-port 1883

# 連既有 mavsdk_server(不自行 spawn)
python -m mission_exec.main --mission missions/demo_square.json \
    --drone-id dev-1 --mavsdk-address localhost:50051
```

> 與 drone_agent 同機併跑時,用 `--mavsdk-address localhost:50051` 顯式共用同一個
> mavsdk_server,不要依賴隱性埠共用(兩個進程各自 spawn 會搶 MAVLink 埠)。

逾時參數(逾時皆發 `STATE_FAILED` 後以 exit code 1 結束):

- `--health-timeout`(預設 120 秒):上傳後等待 GPS/home 就緒的上限,逾時=「定位未就緒」。
- `--stall-timeout`(預設 300 秒):進度事件**停滯**上限——超過此時間**完全沒有任何**
  進度事件才判失敗(鏈路中斷/失效保護接管);航點間隔長不算停滯。

進度發布為 best-effort:MQTT broker 斷線只記 WARNING,不中斷任務(stdout 一定印)。

測試:`pytest tests -q`

## 狀態機

```mermaid
stateDiagram-v2
    [*] --> RECEIVED : 任務檔載入 + 驗證通過
    RECEIVED --> UPLOADED : RTL 設定 + MAVSDK 上傳任務
    UPLOADED --> IN_PROGRESS : 定位就緒 + arm + start_mission
    IN_PROGRESS --> IN_PROGRESS : current_item 遞增
    IN_PROGRESS --> COMPLETED : current == total(RTL 交飛控接手)
    RECEIVED --> FAILED : 上傳失敗 / 飛控拒絕
    UPLOADED --> FAILED : 定位逾時 / arm/start 失敗
    IN_PROGRESS --> FAILED : 例外 / 鏈路中斷 / 進度停滯逾時
    COMPLETED --> [*]
    FAILED --> [*]
```

任何例外都會先發出 `STATE_FAILED` 事件再拋出 `MissionExecError`(CLI exit code 1;
任務檔格式錯誤為 exit code 2)。

## 任務控制(契約預留,S12 實作)

契約 v0.2.0 起預留下行控制主題(定義見
[interfaces/README.md](../../interfaces/README.md) 與
[mission.proto](../../interfaces/proto/drone/v1/mission.proto)):

| 主題 | 訊息 | QoS / 編碼 | 狀態 |
|------|------|-----------|------|
| `fleet/{drone_id}/cmd/mission_ctrl` | `drone.v1.MissionCommand`(PAUSE / RESUME / ABORT) | QoS 1,proto3 JSON | **S12 實作**(v0.2.0 只定契約) |

對應的進度狀態 `STATE_PAUSED = 6` 亦於 v0.2.0 新增;本套件的狀態機接入
(`IN_PROGRESS ⇄ PAUSED`、`--resume` 斷點續飛)同屬 S12 範圍,Phase 0 現行
狀態機(上圖)不變。

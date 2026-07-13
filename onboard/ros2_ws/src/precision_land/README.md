# precision_land — 視覺標靶精準降落(降落狀態機庫)

> 對 [docs/20-software/companion-computer.md](../../../../docs/20-software/companion-computer.md)
> 的 precision_land(Phase 1)與 [docs/01-requirements.md](../../../../docs/01-requirements.md)
> REQ-LOG-03(視覺標靶引導,著陸誤差 < 30 cm)。比照 obstacle_guard 雙層模式。

## 現況(P0:純狀態機邏輯庫)

`precision_land/state_machine.py` — **零 ROS 依賴**的降落狀態機,進 `ci.yml` pytest
gate,降落決策每 PR 回歸(比照 `obstacle_guard/safety.py`):

- `PrecisionLandStateMachine.update(obs, now)`:每個控制週期推進狀態機,回傳
  `LandCommand`(水平對準速度 vx/vy + 下降速率 descent_rate_ms + 狀態)。
- `LandState`:`SEARCH → ACQUIRED → DESCEND → LANDED`;丟失走 `REACQUIRE`;
  逾時/超容差走 `ABORT`(見下轉移圖)。
- `alignment_velocity`:水平偏移 → 對準速度(P 控制,模長夾制,方向不變)。
- `LandParams`:對準/容差/中止偏移、下降速率、置信度門檻、著陸高度、搜尋/丟失逾時
  (建構時驗證,皆可調)。

### 狀態轉移

```
SEARCH    ──標靶可信────────────────► ACQUIRED
SEARCH    ──search_timeout_s 未見───► ABORT
ACQUIRED  ──偏移 <= acquire_offset──► DESCEND
ACQUIRED  ──標靶丟失───────────────► REACQUIRE
ACQUIRED  ──偏移 > abort_offset────► ABORT
DESCEND   ──高度 <= landed_alt─────► LANDED
DESCEND   ──偏移 > align_tolerance─► ACQUIRED   (停降重對準,遲滯)
DESCEND   ──偏移 > abort_offset────► ABORT
DESCEND   ──標靶丟失───────────────► REACQUIRE
REACQUIRE ──復得且對準─────────────► DESCEND
REACQUIRE ──復得未對準─────────────► ACQUIRED
REACQUIRE ──lost_timeout_s 未復得──► ABORT
ABORT / LANDED:吸收態(需 reset() 才重啟一次降落)
```

「標靶可信」= 可見 ∧ 置信度 >= `min_confidence` ∧ 偏移/高度為合法數值。

## 安全邊界鐵則

Jetson 只對 PX4 發**速度 setpoint(水平對準 + 下降速率)**,絕不發姿態級指令;
標靶丟失 / 置信度不足 / 逾時 → 狀態機**停止下降**(REACQUIRE 懸停,逾時 ABORT),
寧可中止不可盲降。ABORT 由上層(mission_exec / PX4 failsafe)接手(RTH / 保持高度)。

## P1:ROS node(已做)

`precision_land/node.py` + package.xml/setup.py(ament_python)——訂
`precision_land/target_offset`(std_msgs/Float32MultiArray,布局
`[offset_x_m, offset_y_m, altitude_m, confidence, visible]`,避 geometry_msgs 相依
不確定)→ 用**已測 P0 狀態機**算指令 → 發:

- `precision_land/velocity_cmd`(std_msgs/Float32MultiArray `[vx, vy, descent_rate_ms]`)
- `precision_land/state`(std_msgs/String,當前狀態名)

10 Hz timer;決策邏輯零 ROS、已單測(state_machine.py),node 為薄 ROS I/O 包裝。

**驗證**:`ros:humble` colcon build 通過(ros-build-ci.yml 守門)+ node 可載入
rclpy/std_msgs/state_machine。**運行行為(對準收斂、著陸誤差 < 30 cm)**由 SITL +
合成標靶驗(同專案其他 ROS node 的標準;需 SITL + 標靶模型)。

## 待做(後續 PR)

- 輸入 → 真實標靶偵測:視覺 ArUco/AprilTag 偵測 → `precision_land/target_offset`
  (需相機 + 標靶,SITL 合成先行)。
- 輸出 → PX4 橋接:`velocity_cmd` 轉 Offboard 速度 setpoint,或送 PX4 Precision
  Landing(`LANDING_TARGET` / PLD 模式)——需 SITL 調校驗證。

**誠實邊界**:缺實體相機/標靶,運行降落行為只能 SITL/合成驗證,非實機
(比照 obstacle_guard node 的 Phase 1 邊界)。

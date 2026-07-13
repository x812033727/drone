# obstacle_guard — 避障保守限速(安全邏輯庫)

> 對 [docs/20-software/companion-computer.md](../../../../docs/20-software/companion-computer.md)
> 的 obstacle_guard(Phase 1 感知安全節點)。

## 現況(P0:純安全邏輯庫)

`obstacle_guard/safety.py` — **零 ROS 依賴**的純決策函式,進 `ci.yml` pytest gate,
飛安決策每 PR 回歸(比照 `tools/sitl_scenarios/checks.py`):

- `speed_limit_from_distance(distance, params)`:前方最近障礙距離 → 水平速度上限
  (<= stop 逼停;>= slow 不限;之間線性)。
- `is_stale(age, params)` / `safe_speed_limit(distance, age, params)`:感知輸入
  **stale 優先於距離**——過期一律保守停,寧停不放行。
- `clamp_horizontal_speed(vx, vy, max)`:速度 setpoint 模長夾制(方向不變)。
- `GuardParams`:stop/slow 距離、max_speed、watchdog 逾時(建構時驗證)。

## 安全邊界鐵則

Jetson 只對 PX4 發**速度限制 / setpoint 修正**,絕不發姿態級指令;任一感知 node
崩潰或輸入 stale → obstacle_guard 進保守限速(停),不影響飛安
(guard 自身崩潰則落 PX4 failsafe)。

## 待做(後續 PR)

- **P1**:ROS node(`node.py` + package.xml/setup.py)——訂距離/合成 topic
  (`/fmu/out/*` 用 `PX4_QOS`),發 `ObstacleDistance` → `/fmu/in/obstacle_distance`
  (PX4 Collision-Prevention 韌體端限速);watchdog stale → 發保守值。
- **P2**:SITL 合成整合(Tier 1),接 nightly。

**誠實邊界**:缺實體雙目/ToF,只能到 SITL/合成驗證,非實機驗證。

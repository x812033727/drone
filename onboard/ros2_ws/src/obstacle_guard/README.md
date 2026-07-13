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

## P1:ROS node(已做)

`obstacle_guard/node.py` + package.xml/setup.py(ament_python)——訂
`perception/nearest_obstacle_m`(std_msgs/Float32,避 px4_msgs 相依不確定)→ 用**已測
P0 邏輯** `safe_speed_limit` 算水平速度上限 → 發 `obstacle_guard/speed_limit_ms`;
10 Hz timer + watchdog(感知 stale → 保守停 0)。決策邏輯零 ROS、已單測(safety.py);
node 為薄 ROS I/O 包裝。

**驗證**:`ros:humble` colcon build 通過(ros-build-ci.yml 守門)+ node 可載入
rclpy/std_msgs/safety + safe_speed_limit 計算正確。**運行行為(對障礙實際減速)**由
nightly SITL 驗(同專案其他 ROS node 的標準;需 SITL+感測器)。

## 待做(後續 PR)

- 輸出 → PX4 橋接:`speed_limit_ms` 轉 `ObstacleDistance`→`/fmu/in/obstacle_distance`
  (Collision-Prevention 韌體端限速)或 Offboard 速度 clamp——需 SITL 調校驗證。
- 實機感知源(stereo_depth/ToF → `perception/nearest_obstacle_m`);SITL 合成整合接 nightly。

**誠實邊界**:缺實體雙目/ToF,運行減速行為只能 SITL/合成驗證,非實機。

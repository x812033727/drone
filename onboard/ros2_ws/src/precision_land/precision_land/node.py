"""precision_land ROS 2 node(P1):訂標靶偏移 → 用已測 P0 狀態機 → 發速度/下降指令。

安全邊界(companion-computer.md):只發**速度 setpoint(水平對準 + 下降速率)**,
絕不發姿態級指令;標靶丟失/逾時 → 狀態機停止下降(REACQUIRE 懸停,逾時 ABORT),
不影響飛安。降落決策全在已單測的 precision_land.state_machine(零 ROS),本 node
只做 ROS I/O 包裝(colcon build + ros-build-ci 守門)。

輸入 `precision_land/target_offset`(std_msgs/Float32MultiArray,避 geometry_msgs
相依不確定)——布局 [offset_x_m, offset_y_m, altitude_m, confidence, visible]:
  offset_x/y = 標靶相對機體水平偏移(公尺,0=正下方對準);altitude_m = AGL 高度;
  confidence = 0..1;visible = 1.0/0.0(標靶偵測器本週期是否有輸出)。
實機由視覺標靶偵測(ArUco/AprilTag)提供(Phase 1)。

輸出:
  `precision_land/velocity_cmd`(std_msgs/Float32MultiArray [vx, vy, descent_rate_ms])
    ——水平對準速度 + 下降速率,供下游 setpoint 或(Phase 1)轉 PX4 Offboard /
      Precision Landing(LANDING_TARGET / PLD)。
  `precision_land/state`(std_msgs/String)——當前狀態名(SEARCH/ACQUIRED/DESCEND/
    REACQUIRE/ABORT/LANDED),供上層任務狀態機(mission_exec)與遙測。

**Phase 1 邊界**:未接真實標靶偵測源與 PX4 Offboard/PLD 執行;運行降落行為(對準
收斂、著陸誤差 < 30 cm)由 SITL + 合成標靶驗證,非實機。比照 obstacle_guard node。
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray, String

from precision_land.state_machine import (
    LandParams,
    Observation,
    PrecisionLandStateMachine,
)


class PrecisionLandNode(Node):
    def __init__(self) -> None:
        super().__init__("precision_land")
        self.declare_parameter("acquire_offset_m", 0.30)
        self.declare_parameter("align_tolerance_m", 0.60)
        self.declare_parameter("abort_offset_m", 3.0)
        self.declare_parameter("descend_speed_ms", 0.35)
        self.declare_parameter("horizontal_gain", 1.0)
        self.declare_parameter("max_horizontal_speed_ms", 1.0)
        self.declare_parameter("min_confidence", 0.5)
        self.declare_parameter("landed_altitude_m", 0.15)
        self.declare_parameter("search_timeout_s", 30.0)
        self.declare_parameter("lost_timeout_s", 3.0)
        self.declare_parameter("rate_hz", 10.0)

        params = LandParams(
            acquire_offset_m=self.get_parameter("acquire_offset_m").value,
            align_tolerance_m=self.get_parameter("align_tolerance_m").value,
            abort_offset_m=self.get_parameter("abort_offset_m").value,
            descend_speed_ms=self.get_parameter("descend_speed_ms").value,
            horizontal_gain=self.get_parameter("horizontal_gain").value,
            max_horizontal_speed_ms=self.get_parameter("max_horizontal_speed_ms").value,
            min_confidence=self.get_parameter("min_confidence").value,
            landed_altitude_m=self.get_parameter("landed_altitude_m").value,
            search_timeout_s=self.get_parameter("search_timeout_s").value,
            lost_timeout_s=self.get_parameter("lost_timeout_s").value,
        )
        self._sm = PrecisionLandStateMachine(params)
        # 未收到任何標靶前:視為不可見(狀態機留在 SEARCH)。
        self._obs = Observation(
            target_visible=False, offset_x=0.0, offset_y=0.0, altitude_m=0.0, confidence=0.0
        )

        self.create_subscription(
            Float32MultiArray, "precision_land/target_offset", self._on_target, 10
        )
        self._cmd_pub = self.create_publisher(
            Float32MultiArray, "precision_land/velocity_cmd", 10
        )
        self._state_pub = self.create_publisher(String, "precision_land/state", 10)
        self.create_timer(1.0 / self.get_parameter("rate_hz").value, self._tick)
        self.get_logger().info(
            "precision_land node 已啟動(標靶丟失→停降懸停/逾時→ABORT)"
        )

    def _on_target(self, msg: Float32MultiArray) -> None:
        d = list(msg.data)
        if len(d) < 5:
            self.get_logger().warn(
                f"target_offset 需 5 欄 [x,y,alt,conf,visible],收到 {len(d)};忽略本則"
            )
            return
        self._obs = Observation(
            target_visible=d[4] >= 0.5,
            offset_x=float(d[0]),
            offset_y=float(d[1]),
            altitude_m=float(d[2]),
            confidence=float(d[3]),
        )

    def _tick(self) -> None:
        now = self.get_clock().now().nanoseconds * 1e-9
        cmd = self._sm.update(self._obs, now)
        self._cmd_pub.publish(
            Float32MultiArray(data=[cmd.vx, cmd.vy, cmd.descent_rate_ms])
        )
        self._state_pub.publish(String(data=cmd.state.value))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = PrecisionLandNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()

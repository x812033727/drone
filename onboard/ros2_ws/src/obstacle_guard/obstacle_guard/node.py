"""obstacle_guard ROS 2 node(P1):訂感知距離 → 用已測 P0 邏輯算速度上限 → 發布。

安全邊界(companion-computer.md):只發**速度限制**,絕不發姿態級指令;感知
輸入 stale(watchdog 逾時)→ 保守停(0),不影響飛安。決策邏輯全在已單測的
obstacle_guard.safety(#59,零 ROS),本 node 只做 ROS I/O 包裝(build + nightly 驗)。

輸入 `perception/nearest_obstacle_m`(std_msgs/Float32,前方最近障礙距離公尺)——
用標準 msg 避 px4_msgs 相依不確定;實機由 stereo_depth/ToF 感知源提供(Phase 1)。
輸出 `obstacle_guard/speed_limit_ms`(std_msgs/Float32,水平速度上限)——供下游
setpoint clamp 或(Phase 1)轉 PX4 ObstacleDistance(Collision-Prevention)/Offboard。
"""

import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32

from obstacle_guard.safety import GuardParams, safe_speed_limit


class ObstacleGuardNode(Node):
    def __init__(self) -> None:
        super().__init__("obstacle_guard")
        self.declare_parameter("stop_distance_m", 3.0)
        self.declare_parameter("slow_distance_m", 10.0)
        self.declare_parameter("max_speed_ms", 12.0)
        self.declare_parameter("watchdog_timeout_s", 0.5)
        self.declare_parameter("rate_hz", 10.0)
        self._params = GuardParams(
            stop_distance_m=self.get_parameter("stop_distance_m").value,
            slow_distance_m=self.get_parameter("slow_distance_m").value,
            max_speed_ms=self.get_parameter("max_speed_ms").value,
            watchdog_timeout_s=self.get_parameter("watchdog_timeout_s").value,
        )
        self._distance: float | None = None
        self._last_update: float | None = None
        self.create_subscription(Float32, "perception/nearest_obstacle_m", self._on_distance, 10)
        self._pub = self.create_publisher(Float32, "obstacle_guard/speed_limit_ms", 10)
        self.create_timer(1.0 / self.get_parameter("rate_hz").value, self._tick)
        self.get_logger().info("obstacle_guard node 已啟動(watchdog stale→保守停)")

    def _on_distance(self, msg: Float32) -> None:
        self._distance = float(msg.data)
        self._last_update = time.monotonic()

    def _tick(self) -> None:
        if self._last_update is None:
            age = float("inf")
        else:
            age = time.monotonic() - self._last_update
        limit = safe_speed_limit(self._distance, age, self._params)
        self._pub.publish(Float32(data=float(limit)))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ObstacleGuardNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()

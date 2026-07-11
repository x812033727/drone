"""PX4 uXRCE-DDS bridge 最小煙霧驗證(Phase 0 第二批 S8)。

訂閱 /fmu/out/vehicle_status(px4_msgs/VehicleStatus)與
/fmu/out/vehicle_local_position(px4_msgs/VehicleLocalPosition),
收滿 N 筆 VehicleStatus(預設 10)即印摘要並 exit 0;逾時(預設 60s)exit 1。

QoS 依 PX4 官方建議:BestEffort / KeepLast / TransientLocal
(與 uxrce_dds_client 發佈端一致,Reliable 訂閱端會收不到)。
"""

import argparse
import sys

import rclpy
from px4_msgs.msg import VehicleLocalPosition, VehicleStatus
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=5,
)


class BridgeSmokeListener(Node):
    """收 target 筆 VehicleStatus 即成功;timeout_s 內沒收滿即失敗。"""

    def __init__(self, target: int, timeout_s: float) -> None:
        super().__init__("bridge_smoke_listener")
        self._target = target
        self.status_count = 0
        self.result: bool | None = None
        self._local_pos: VehicleLocalPosition | None = None
        self.create_subscription(
            VehicleStatus, "/fmu/out/vehicle_status", self._on_status, PX4_QOS
        )
        self.create_subscription(
            VehicleLocalPosition, "/fmu/out/vehicle_local_position", self._on_local_pos, PX4_QOS
        )
        self.create_timer(timeout_s, self._on_timeout)

    def _on_local_pos(self, msg: VehicleLocalPosition) -> None:
        self._local_pos = msg

    def _on_status(self, msg: VehicleStatus) -> None:
        if self.result is not None:
            return
        self.status_count += 1
        if self._local_pos is not None:
            xyz = (
                f"x={self._local_pos.x:+.2f} y={self._local_pos.y:+.2f} "
                f"z={self._local_pos.z:+.2f}"
            )
        else:
            xyz = "xyz=(尚未收到 local_position)"
        self.get_logger().info(
            f"[{self.status_count}/{self._target}] "
            f"arming_state={msg.arming_state} nav_state={msg.nav_state} {xyz}"
        )
        if self.status_count >= self._target:
            self.result = True

    def _on_timeout(self) -> None:
        if self.result is None:
            self.result = False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=10, help="要收的 VehicleStatus 筆數")
    parser.add_argument("--timeout", type=float, default=60.0, help="逾時秒數")
    args = parser.parse_args(argv)

    rclpy.init()
    node = BridgeSmokeListener(args.count, args.timeout)
    try:
        while rclpy.ok() and node.result is None:
            rclpy.spin_once(node, timeout_sec=1.0)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

    if node.result:
        print(f"PASS: 收到 {node.status_count} 筆 VehicleStatus,uXRCE-DDS 鏈路全通")
        return 0
    print(
        f"FAIL: {args.timeout}s 內僅收到 {node.status_count}/{args.count} 筆 VehicleStatus",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

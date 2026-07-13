"""DDS→MQTT 高頻感測器橋(Phase 0 S22)。

訂閱 PX4 uXRCE-DDS 的 /fmu/out/vehicle_attitude、/fmu/out/vehicle_gps_position
(型別 px4_msgs/SensorGps)、/fmu/out/vehicle_local_position,以 latest-sample
節流(預設 5 Hz)組 drone.v1 sensors proto,proto3 JSON 發布至
`fleet/{drone_id}/sensors/attitude|gps|local_position`(**QoS 0** 容失,
與 1 Hz 摘要 QoS 1 區隔)。契約見 interfaces/proto/drone/v1/sensors.proto。

設計要點:
- QoS 依 PX4 官方建議 BestEffort/TransientLocal(CLAUDE.md 鐵則 3,
  Reliable 訂閱端會一筆都收不到),照抄 bridge_smoke/listener.py 的 PX4_QOS。
- 回呼只存最新樣本;timer flush 時「自上次外發後有新樣本」的 key 才發——
  來源斷流時橋跟著沉默,不重複外發殭屍資料(殭屍防護哲學)。
- unix_time_ms = 收樣當下 wall clock;PX4 原始 timestamp(boot-time 微秒,
  非 epoch)原樣放 px4_timestamp_us 另欄保留,Phase 1 時鐘對齊前勿混算。
- 不做(Phase 1):全 topic 橋接、backpressure/斷線補傳、binary 編碼、
  PPS/PTP 時鐘對齊。
"""

import argparse
import sys
import time

import paho.mqtt.client as mqtt
import rclpy
from google.protobuf.json_format import MessageToJson
from px4_msgs.msg import SensorGps as Px4SensorGps
from px4_msgs.msg import VehicleAttitude as Px4VehicleAttitude
from px4_msgs.msg import VehicleLocalPosition as Px4VehicleLocalPosition
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from px4_mqtt_bridge import codec

# PX4 uxrce_dds_client 發佈端是 BestEffort/TransientLocal;
# 訂閱端不一致(rclpy 預設 Reliable)會靜默收不到(鐵則 3)。
PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=5,
)

# proto 建構子與 fix_type 映射已抽至 codec.py(純函式,單測不需 ROS 2)。

# key → (ROS 型別, ROS topic, MQTT 子主題, proto 組裝函式)
# topic 名與型別對 PX4 v1.15.4 dds_topics.yaml 查證
# (vehicle_gps_position 的型別是 px4_msgs/SensorGps,非 VehicleGpsPosition)
_STREAMS = {
    "attitude": (
        Px4VehicleAttitude,
        "/fmu/out/vehicle_attitude",
        "attitude",
        codec.attitude_proto,
    ),
    "gps": (Px4SensorGps, "/fmu/out/vehicle_gps_position", "gps", codec.gps_proto),
    "local_position": (
        Px4VehicleLocalPosition,
        "/fmu/out/vehicle_local_position",
        "local_position",
        codec.local_position_proto,
    ),
}


class Px4MqttBridge(Node):
    """訂 /fmu/out/* → latest-sample 節流 → MQTT fleet/{id}/sensors/*(QoS 0)。"""

    def __init__(self, drone_id: str, mqtt_client: mqtt.Client, rate_hz: float) -> None:
        super().__init__("px4_mqtt_bridge")
        self._drone_id = drone_id
        self._mqtt = mqtt_client
        # key → (msg, 收樣 wall clock ms);flush 後清 None,無新樣本不外發
        self._latest: dict[str, tuple | None] = {key: None for key in _STREAMS}
        self.published = dict.fromkeys(_STREAMS, 0)

        for key, (ros_type, ros_topic, _sub, _build) in _STREAMS.items():
            self.create_subscription(
                ros_type,
                ros_topic,
                lambda msg, key=key: self._on_sample(key, msg),
                PX4_QOS,
            )
        self.create_timer(1.0 / rate_hz, self._flush)
        self.get_logger().info(
            f"橋接啟動 drone_id={drone_id} rate={rate_hz}Hz "
            f"topics={[s[1] for s in _STREAMS.values()]}"
        )

    def _on_sample(self, key: str, msg) -> None:
        # 回呼只存最新樣本(高頻 topic 不在回呼內做編碼/IO)
        self._latest[key] = (msg, int(time.time() * 1000))

    def _flush(self) -> None:
        for key, entry in self._latest.items():
            if entry is None:
                continue  # 自上次外發後無新樣本 → 不發(殭屍防護)
            self._latest[key] = None
            msg, wall_ms = entry
            _ros_type, _topic, subtopic, build = _STREAMS[key]
            payload = MessageToJson(
                build(msg, self._drone_id, wall_ms),
                preserving_proto_field_name=True,
                always_print_fields_with_no_presence=True,
                indent=None,
            )
            self._mqtt.publish(f"fleet/{self._drone_id}/sensors/{subtopic}", payload, qos=0)
            self.published[key] += 1
            if self.published[key] == 1:
                self.get_logger().info(f"首筆已外發:sensors/{subtopic}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drone-id", default="dev-1", help="機身識別碼(MQTT 主題用)")
    parser.add_argument("--mqtt-host", default="localhost")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--rate", type=float, default=5.0, help="外發頻率上限(Hz,預設 5)")
    args = parser.parse_args(argv)

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=f"px4-bridge-{args.drone_id}"
    )
    # broker 不在 → 這裡直接 raise 退出(Phase 0:由外層重啟;斷線補傳不做)。
    # 連上後的斷線由 paho loop_start 的背景執行緒自動重連,QoS 0 期間訊息容失。
    client.connect(args.mqtt_host, args.mqtt_port)
    client.loop_start()

    rclpy.init()
    node = Px4MqttBridge(args.drone_id, client, args.rate)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        totals = dict(node.published)
        node.destroy_node()
        rclpy.shutdown()
        client.loop_stop()
        client.disconnect()
        print(f"外發統計:{totals}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

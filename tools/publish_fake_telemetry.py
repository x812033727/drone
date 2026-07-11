#!/usr/bin/env python3
"""不開 SITL 也能驗證雲端棧的假遙測產生器。

飛一個圓形軌跡(台北附近),以 proto3 JSON 發布 TelemetrySummary 到
fleet/{drone_id}/telemetry。契約見 interfaces/proto/drone/v1/telemetry.proto。

用法:
    pip install -r requirements.txt
    pip install -e ../interfaces/proto/gen/python   # 或依下方 fallback 直接跑
    python publish_fake_telemetry.py --drone-id dev-1 --rate 1 --count 30
"""

import argparse
import math
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from google.protobuf.json_format import MessageToJson

try:
    from drone.v1 import telemetry_pb2
except ImportError:  # 開發便利:未安裝 drone-proto 時直接用 repo 內生成碼
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "interfaces/proto/gen/python"))
    from drone.v1 import telemetry_pb2

CENTER_LAT, CENTER_LON = 25.0330, 121.5654  # 台北
RADIUS_DEG = 0.002  # 約 200 m


def make_summary(drone_id: str, tick: int) -> telemetry_pb2.TelemetrySummary:
    angle = tick * 0.1
    return telemetry_pb2.TelemetrySummary(
        drone_id=drone_id,
        unix_time_ms=int(time.time() * 1000),
        lat_deg=CENTER_LAT + RADIUS_DEG * math.sin(angle),
        lon_deg=CENTER_LON + RADIUS_DEG * math.cos(angle),
        rel_alt_m=30.0 + 5.0 * math.sin(angle / 3),
        heading_deg=(math.degrees(angle) + 90.0) % 360.0,
        ground_speed_ms=6.0,
        flight_mode="MISSION",
        armed=True,
        battery_v=16.4 - 0.01 * tick,
        battery_pct=max(0.0, 100.0 - 0.2 * tick),
        health_all_ok=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drone-id", default="dev-1")
    ap.add_argument("--mqtt-host", default="localhost")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--rate", type=float, default=1.0, help="每秒發布次數")
    ap.add_argument("--count", type=int, default=0, help="發布 N 筆後結束(0 = 不停)")
    args = ap.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"fake-{args.drone_id}")
    client.connect(args.mqtt_host, args.mqtt_port)
    client.loop_start()
    topic = f"fleet/{args.drone_id}/telemetry"

    tick = 0
    try:
        while args.count <= 0 or tick < args.count:
            payload = MessageToJson(make_summary(args.drone_id, tick))
            client.publish(topic, payload, qos=1).wait_for_publish(timeout=5)
            tick += 1
            time.sleep(1.0 / args.rate)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
    print(f"已發布 {tick} 筆至 {topic}")


if __name__ == "__main__":
    main()

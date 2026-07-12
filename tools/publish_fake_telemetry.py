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
    from drone.v1 import device_pb2, events_pb2, mission_pb2, sensors_pb2, telemetry_pb2
except ImportError:  # 開發便利:未安裝 drone-proto 時直接用 repo 內生成碼
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "interfaces/proto/gen/python"))
    from drone.v1 import device_pb2, events_pb2, mission_pb2, sensors_pb2, telemetry_pb2

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
        # v0.3.0 新欄:GPS 品質與垂直速度
        satellites=14,
        gps_fix_type="FIX_3D",
        hdop=0.8,
        vertical_speed_ms=1.5 * math.cos(angle / 3),  # 隨 rel_alt_m 起伏的小幅升降
    )


def publish_sensor_samples(client: mqtt.Client, drone_id: str) -> None:
    """v0.4.0 高頻感測器流(sensors.proto)各打一筆到 fleet/{id}/sensors/*(QoS 0)。

    線上編碼對齊 px4_mqtt_bridge:preserving_proto_field_name + 全欄位輸出。
    """
    now_ms = int(time.time() * 1000)
    samples = {
        "attitude": sensors_pb2.SensorAttitude(
            drone_id=drone_id,
            unix_time_ms=now_ms,
            px4_timestamp_us=12_345_678,
            q=[1.0, 0.0, 0.0, 0.0],
        ),
        "gps": sensors_pb2.SensorGps(
            drone_id=drone_id,
            unix_time_ms=now_ms,
            px4_timestamp_us=12_345_678,
            latitude_deg=CENTER_LAT,
            longitude_deg=CENTER_LON,
            altitude_msl_m=105.0,
            satellites_used=14,
            hdop=0.8,
            vdop=1.1,
            fix_type="FIX_TYPE_3D",
        ),
        "local_position": sensors_pb2.SensorLocalPosition(
            drone_id=drone_id,
            unix_time_ms=now_ms,
            px4_timestamp_us=12_345_678,
            x=1.0,
            y=2.0,
            z=-30.0,
            vx=0.1,
            vy=0.2,
            vz=-0.3,
            heading=1.57,
        ),
    }
    for subtopic, msg in samples.items():
        payload = MessageToJson(
            msg,
            preserving_proto_field_name=True,
            always_print_fields_with_no_presence=True,
            indent=None,
        )
        client.publish(f"fleet/{drone_id}/sensors/{subtopic}", payload, qos=0).wait_for_publish(
            timeout=5
        )
    print(f"已各發布 1 筆 sensors 樣本至 fleet/{drone_id}/sensors/{{{','.join(samples)}}}")


def publish_mission_events(client: mqtt.Client, drone_id: str) -> None:
    """發 1 筆 MissionProgress + 1 筆 FlightEvent(S25,QoS 1)。

    覆蓋 ingest 另兩條訂閱(fleet/{id}/mission/progress、fleet/{id}/events)
    的落庫路徑;線上編碼同機上端(proto3 JSON,Parse 端 camelCase/欄位名皆收)。
    """
    now_ms = int(time.time() * 1000)
    progress = mission_pb2.MissionProgress(
        mission_id="fake-mission-1",
        drone_id=drone_id,
        current_item=4,
        total_items=4,
        state=mission_pb2.MissionProgress.STATE_COMPLETED,
        unix_time_ms=now_ms,
    )
    event = events_pb2.FlightEvent(
        drone_id=drone_id,
        unix_time_ms=now_ms,
        event=events_pb2.FlightEvent.EVENT_ARMED,
    )
    for subtopic, msg in (("mission/progress", progress), ("events", event)):
        client.publish(
            f"fleet/{drone_id}/{subtopic}", MessageToJson(msg, indent=None), qos=1
        ).wait_for_publish(timeout=5)
    print(f"已各發布 1 筆至 fleet/{drone_id}/{{mission/progress,events}}")


def publish_heartbeat(client: mqtt.Client, drone_id: str) -> None:
    """發 1 筆 DeviceHeartbeat 到 fleet/{id}/heartbeat(v0.5.0,QoS 1)。

    覆蓋 ingest 的 heartbeat 訂閱落庫路徑(device_heartbeat 表)。
    """
    now_ms = int(time.time() * 1000)
    hb = device_pb2.DeviceHeartbeat(
        drone_id=drone_id,
        unix_time_ms=now_ms,
        agent_version="0.1.0",
        firmware_version="1.15.4",
        boot_unix_ms=now_ms - 60_000,
        uptime_s=60,
    )
    client.publish(
        f"fleet/{drone_id}/heartbeat", MessageToJson(hb, indent=None), qos=1
    ).wait_for_publish(timeout=5)
    print(f"已發布 1 筆心跳至 fleet/{drone_id}/heartbeat")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drone-id", default="dev-1")
    ap.add_argument("--mqtt-host", default="localhost")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--rate", type=float, default=1.0, help="每秒發布次數")
    ap.add_argument("--count", type=int, default=0, help="發布 N 筆後結束(0 = 不停)")
    ap.add_argument(
        "--with-sensors",
        action="store_true",
        help="額外對 fleet/{id}/sensors/attitude|gps|local_position 各發 1 筆(v0.4.0,QoS 0)",
    )
    ap.add_argument(
        "--with-mission-events",
        action="store_true",
        help="額外對 fleet/{id}/mission/progress 與 fleet/{id}/events 各發 1 筆假資料"
        "(S25,QoS 1;覆蓋 ingest 全部四條訂閱)",
    )
    ap.add_argument(
        "--with-heartbeat",
        action="store_true",
        help="額外對 fleet/{id}/heartbeat 發 1 筆 DeviceHeartbeat(v0.5.0,QoS 1)",
    )
    args = ap.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"fake-{args.drone_id}")
    client.connect(args.mqtt_host, args.mqtt_port)
    client.loop_start()
    topic = f"fleet/{args.drone_id}/telemetry"

    tick = 0
    try:
        if args.with_sensors:
            publish_sensor_samples(client, args.drone_id)
        if args.with_mission_events:
            publish_mission_events(client, args.drone_id)
        if args.with_heartbeat:
            publish_heartbeat(client, args.drone_id)
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

#!/usr/bin/env python3
"""酬載/電池遙測合成注入器(G7):不開 SITL 也能驗 payload 消費鏈下游。

以 proto3 JSON 發 PayloadStatus / SprayTelemetry / BatteryDetail 到
fleet/{drone_id}/payload/status|spray|battery(契約 = interfaces/proto
drone/v1/payload.proto;數值與 firmware payload_sim 同一組確定性假值)。

用法:
    python publish_fake_payload.py --drone-id dev-1 --rate 1 --count 30 --port 31883
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from google.protobuf.json_format import MessageToJson

try:
    from drone.v1 import payload_pb2
except ImportError:  # 開發便利:未安裝 drone-proto 時直接用 repo 內生成碼
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "interfaces/proto/gen/python"))
    from drone.v1 import payload_pb2

UINT16_MAX = 0xFFFF


def make_payload_status(drone_id: str, tick: int) -> payload_pb2.PayloadStatus:
    return payload_pb2.PayloadStatus(
        drone_id=drone_id,
        unix_time_ms=int(time.time() * 1000),
        time_boot_ms=tick * 1000,
        payload_type=3,  # SPRAYER
        payload_id=0,
        state=3,  # ACTIVE
        fault_flags=0,
        temperature_cdegc=3500 + (tick % 100),
        firmware_version=(1 << 24),
        vendor_status=0,
    )


def make_spray(drone_id: str, tick: int) -> payload_pb2.SprayTelemetry:
    return payload_pb2.SprayTelemetry(
        drone_id=drone_id,
        unix_time_ms=int(time.time() * 1000),
        time_boot_ms=tick * 1000,
        flow_rate_ml_s=120.0,
        flow_rate_setpoint_ml_s=120.0,
        volume_remaining_ml=max(0.0, 10000.0 - 120.0 * tick),
        volume_consumed_ml=120.0 * tick,
        application_rate_ml_m2=float("nan"),
        pump_pressure_bar=2.5,
        boom_width_m=4.0,
        spray_flags=0,
        pump_state=2,  # ACTIVE
        nozzles_active=8,
    )


def make_battery(drone_id: str, tick: int) -> payload_pb2.BatteryDetail:
    return payload_pb2.BatteryDetail(
        drone_id=drone_id,
        unix_time_ms=int(time.time() * 1000),
        time_boot_ms=tick * 1000,
        fault_flags=0,
        capacity_full_charge_mah=16000,
        capacity_remaining_mah=max(0, 12000 - 10 * tick),
        cell_voltages_mv=[3900] * 12 + [UINT16_MAX] * 2,
        cycle_count=42,
        temperature_cdegc=2800,
        current_ca=1500,
        id=0,
        cell_count=12,
        state_of_health=97,
        state_of_charge=75,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drone-id", default="dev-1")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--rate", type=float, default=1.0)
    parser.add_argument("--count", type=int, default=30)
    args = parser.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fake-payload")
    client.connect(args.host, args.port)
    client.loop_start()
    base = f"fleet/{args.drone_id}/payload"
    try:
        for tick in range(args.count):
            for suffix, msg in (
                ("status", make_payload_status(args.drone_id, tick)),
                ("spray", make_spray(args.drone_id, tick)),
                ("battery", make_battery(args.drone_id, tick)),
            ):
                client.publish(f"{base}/{suffix}", MessageToJson(msg), qos=0)
            time.sleep(1.0 / args.rate)
    finally:
        client.loop_stop()
        client.disconnect()
    print(f"[fake-payload] 已發 {args.count} 輪 × 3 主題 → {base}/*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

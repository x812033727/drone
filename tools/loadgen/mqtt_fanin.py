#!/usr/bin/env python3
"""多機遙測 fan-in 產生器(ingest 寫入路徑的負載源)。

N 台假機 × 每台 R Hz,重用 publish_fake_telemetry 的 TelemetrySummary 產生器,
發到 fleet/{drone_id}/telemetry(proto3 JSON,契約同 ingest 消費端)。

誠實邊界:預設單一 MQTT 連線輪發 N 個 drone_id——受測標的是 broker→ingest→DB
的訊息速率,不是 broker 的連線數(要壓連線數用 --connections 分片)。

用法(對隔離棧):
    python tools/loadgen/mqtt_fanin.py --drones 30 --rate 5 --seconds 45 --port 31883

結束時輸出實際發布速率;落庫率由 psql 端核對(腳本會印出對應查詢)。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from google.protobuf.json_format import MessageToJson

# 重用既有假遙測產生器(tools/ 目錄)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publish_fake_telemetry import make_summary  # noqa: E402


def run(
    host: str, port: int, drones: int, rate: float, seconds: float, connections: int = 1
) -> int:
    """回傳實際發布筆數。單連線輪發;軟即時(睡到下一格,趕不上就如實落後)。"""
    conns = [mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"loadgen-fanin-{i}")
             for i in range(max(1, connections))]
    for c in conns:
        c.connect(host, port)
        c.loop_start()

    ids = [f"loadgen-{i:03d}" for i in range(drones)]
    interval = 1.0 / (drones * rate)  # 全域訊息間隔
    deadline = time.monotonic() + seconds
    published = 0
    tick = 0
    next_at = time.monotonic()
    try:
        while time.monotonic() < deadline:
            drone_id = ids[published % drones]
            msg = make_summary(drone_id, tick)
            payload = MessageToJson(msg, preserving_proto_field_name=True)
            conns[published % len(conns)].publish(
                f"fleet/{drone_id}/telemetry", payload, qos=0
            )
            published += 1
            if published % drones == 0:
                tick += 1
            next_at += interval
            delay = next_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
    finally:
        for c in conns:
            c.loop_stop()
            c.disconnect()
    return published


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--drones", type=int, default=30)
    parser.add_argument("--rate", type=float, default=5.0, help="每台每秒訊息數")
    parser.add_argument("--seconds", type=float, default=45.0)
    parser.add_argument(
        "--connections", type=int, default=1,
        help="MQTT 連線數(>1 時輪發分片到多連線;壓連線數用)",
    )
    args = parser.parse_args()

    target_rate = args.drones * args.rate
    t0 = time.monotonic()
    published = run(args.host, args.port, args.drones, args.rate, args.seconds,
                    connections=args.connections)
    elapsed = time.monotonic() - t0
    actual = published / elapsed if elapsed > 0 else 0.0
    print(
        f"[fanin] drones={args.drones} 目標 {target_rate:.0f} msg/s,"
        f"實發 {published} 筆 / {elapsed:.1f}s = {actual:.1f} msg/s"
    )
    window_s = int(args.seconds + 30)
    print(
        "[fanin] 落庫率核對(psql 對受測 DB):\n"
        "  SELECT count(*) FROM telemetry WHERE drone_id LIKE 'loadgen-%' "
        f"AND time > now() - interval '{window_s} seconds';"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

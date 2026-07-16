#!/usr/bin/env python3
"""等 SITL 的 MAVLink heartbeat(取代固定 sleep,CLAUDE.md 鐵則 4 的精神)。

PX4 SITL 的 offboard MAVLink 通道主動送到 localhost:14540(rcS 預設),
本腳本以 udpin 被動收;收到 heartbeat 即回 0,逾時回 1。
"""

from __future__ import annotations

import argparse
import sys

from pymavlink import mavutil


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=14540)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    conn = mavutil.mavlink_connection(f"udpin:0.0.0.0:{args.port}")
    msg = conn.wait_heartbeat(timeout=args.timeout)
    if msg is None:
        print(f"[heartbeat] {args.timeout}s 內未收到 heartbeat(port {args.port})",
              file=sys.stderr)
        return 1
    print(
        f"[heartbeat] OK:sys={conn.target_system} autopilot={msg.autopilot} "
        f"type={msg.type} base_mode={msg.base_mode}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

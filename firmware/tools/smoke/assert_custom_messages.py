#!/usr/bin/env python3
"""SITL 實收自訂 dialect 訊息(F4 里程碑:契約在真 PX4 上走通的硬證)。

連 SITL offboard MAVLink(udpin),以 SET_MESSAGE_INTERVAL 要求三則自訂訊息,
逾時前各收 ≥1 則並做欄位 sanity(對 payload_sim 的確定性假值)。
需要 drone_sitl Python dialect(run_sitl_smoke.sh 以 mavgen 生成並安裝到
pymavlink dialects 目錄後以 --dialect 指定)。
"""

from __future__ import annotations

import argparse
import sys
import time

from pymavlink import mavutil

MAV_CMD_SET_MESSAGE_INTERVAL = 511

EXPECT = {
    "PAYLOAD_STATUS": 24150,
    "SPRAY_TELEMETRY": 24151,
    "BATTERY_DETAIL": 24152,
}


def sanity(name: str, msg) -> str | None:
    """對 payload_sim 假值的欄位斷言;回傳錯誤描述或 None。"""
    if name == "PAYLOAD_STATUS":
        if msg.payload_type != 3:  # DRONE_PAYLOAD_TYPE_SPRAYER
            return f"payload_type={msg.payload_type}(應 3)"
        if msg.state != 3:  # ACTIVE
            return f"state={msg.state}(應 3)"
    elif name == "SPRAY_TELEMETRY":
        if not (msg.flow_rate > 0):
            return f"flow_rate={msg.flow_rate}(應 >0)"
        if msg.pump_state != 2:  # ACTIVE
            return f"pump_state={msg.pump_state}(應 2)"
    elif name == "BATTERY_DETAIL":
        if msg.cell_count != 12:
            return f"cell_count={msg.cell_count}(應 12)"
        if msg.cell_voltages[0] != 3900 or msg.cell_voltages[13] != 65535:
            return f"cell_voltages 首/末={msg.cell_voltages[0]}/{msg.cell_voltages[13]}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=14540)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    # 不用 dialect= 參數:mavutil.set_dialect 會無條件以 pip 包內的 XML 重生
    # (pip 包無 message_definitions,實測 FileNotFoundError)。直接 import
    # run_sitl_smoke.sh 以 PX4 自帶 mavgen 預生成的模組。
    import pymavlink.dialects.v20.drone_sitl as drone_dialect

    mavutil.mavlink = drone_dialect
    mavutil.current_dialect = "drone_sitl"
    conn = mavutil.mavlink_connection(f"udpin:0.0.0.0:{args.port}")
    hb = conn.wait_heartbeat(timeout=30)
    if hb is None:
        print("[custom-msgs] 30s 內無 heartbeat", file=sys.stderr)
        return 1

    for msg_id in EXPECT.values():
        conn.mav.command_long_send(
            conn.target_system, conn.target_component,
            MAV_CMD_SET_MESSAGE_INTERVAL, 0,
            float(msg_id), 1_000_000.0, 0, 0, 0, 0, 0,  # 1 Hz
        )

    pending = dict(EXPECT)
    deadline = time.monotonic() + args.timeout
    while pending and time.monotonic() < deadline:
        msg = conn.recv_match(type=list(pending), blocking=True, timeout=2)
        if msg is None:
            continue
        name = msg.get_type()
        err = sanity(name, msg)
        if err:
            print(f"[custom-msgs] {name} 欄位異常:{err}", file=sys.stderr)
            return 1
        print(f"[custom-msgs] {name} OK(msgid {pending.pop(name)})")

    if pending:
        print(f"[custom-msgs] 逾時未收到:{sorted(pending)}", file=sys.stderr)
        return 1
    print("[custom-msgs] PASS:三則自訂訊息 SITL 實收 + 欄位 sanity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

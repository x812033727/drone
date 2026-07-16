#!/usr/bin/env python3
"""SITL 參數回讀核對:.params 檔逐項 PARAM_REQUEST_READ 比對(F5)。

用 tools/flight_ops 的既有解析器(單一事實來源的格式);浮點以相對容差比。
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from pymavlink import mavutil

# PX4 以 byte-cast 傳整數參數(PARAM_VALUE.param_value 承載 raw bits;
# MAV_PARAM_TYPE 1-8 為整數型別)——需重新詮釋,直接當 float 讀會得到 denormal。
_INT_TYPES = set(range(1, 9)) - {9, 10}


def _decode_value(msg) -> float:
    if msg.param_type in _INT_TYPES:
        return float(struct.unpack("<i", struct.pack("<f", msg.param_value))[0])
    return msg.param_value

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "tools"))
from flight_ops.apply_params import parse_params_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params-file", required=True)
    parser.add_argument("--port", type=int, default=14540)
    args = parser.parse_args()

    params = parse_params_file(Path(args.params_file))
    conn = mavutil.mavlink_connection(f"udpin:0.0.0.0:{args.port}")
    if conn.wait_heartbeat(timeout=30) is None:
        print("[params] 30s 內無 heartbeat", file=sys.stderr)
        return 1

    failures = []
    for p in params:
        conn.mav.param_request_read_send(
            conn.target_system, conn.target_component, p.name.encode(), -1
        )
        msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=5)
        # 可能收到別的參數廣播;重試撈到目標為止(上限數次)
        tries = 0
        while msg is not None and msg.param_id != p.name and tries < 20:
            msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=5)
            tries += 1
        if msg is None or msg.param_id != p.name:
            failures.append(f"{p.name}: 未收到 PARAM_VALUE")
            continue
        got = _decode_value(msg)
        if abs(got - p.value) > max(1e-4, abs(p.value) * 1e-4):
            failures.append(f"{p.name}: 期望 {p.value},實得 {got}")
        else:
            print(f"[params] {p.name} = {got} OK")

    if failures:
        for f in failures:
            print(f"[params] FAIL {f}", file=sys.stderr)
        return 1
    print(f"[params] PASS:{len(params)} 個參數逐項回讀一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

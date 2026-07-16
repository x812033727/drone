#!/usr/bin/env python3
"""失效保護行為矩陣的參數面 SITL 回歸(F6)。

對 docs/03-safety-analysis.md §4「矩陣列 → Phase 0 參數」表做資料驅動斷言:
起機後逐項 PARAM_REQUEST_READ 回讀,值不符即紅。這把安全矩陣的參數口徑
釘死在 SITL 上——任何 airframe/參數包漂移都會翻紅。

期望值硬編自 §4 表(單一事實來源;同 pa1-sitl-v1.params);行為級場景
(F09–F12)仍由 nightly gazebo 跑,本檢核專守「參數 = 矩陣口徑」。
"""

from __future__ import annotations

import argparse
import struct
import sys

from pymavlink import mavutil

# (param, 期望值, 對應矩陣列)——硬編自 docs/03-safety-analysis.md §4
FAILSAFE_MATRIX = [
    ("NAV_RCL_ACT", 2, "RC 失聯 → RTL"),
    ("COM_RC_LOSS_T", 0.5, "RC 失聯逾時"),
    ("NAV_DLL_ACT", 0, "數傳+4G 全失聯 → 警告(Phase 0)"),
    ("COM_LOW_BAT_ACT", 3, "低電量 Critical 返航/Emergency 降落(v1.15 勿用 2=Land)"),
    ("BAT_LOW_THR", 0.20, "低電量 Low 門檻"),
    ("BAT_CRIT_THR", 0.10, "低電量 Critical 門檻"),
    ("BAT_EMERGEN_THR", 0.05, "低電量 Emergency 門檻"),
    ("GF_ACTION", 3, "GeoFence 越界 → RTL"),
    ("GF_MAX_HOR_DIST", 500.0, "圍欄水平 500 m"),
    ("GF_MAX_VER_DIST", 100.0, "圍欄垂直 100 m"),
    ("COM_OBL_RC_ACT", 0, "Jetson/Offboard 失聯且 RC 在手 → 交還 Position"),
]

_INT_TYPES = set(range(1, 9)) - {9, 10}


def _decode(msg) -> float:
    if msg.param_type in _INT_TYPES:
        return float(struct.unpack("<i", struct.pack("<f", msg.param_value))[0])
    return msg.param_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=14540)
    args = parser.parse_args()

    conn = mavutil.mavlink_connection(f"udpin:0.0.0.0:{args.port}")
    if conn.wait_heartbeat(timeout=30) is None:
        print("[failsafe] 30s 內無 heartbeat", file=sys.stderr)
        return 1

    failures = []
    for name, expected, desc in FAILSAFE_MATRIX:
        conn.mav.param_request_read_send(
            conn.target_system, conn.target_component, name.encode(), -1
        )
        msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=5)
        tries = 0
        while msg is not None and msg.param_id != name and tries < 20:
            msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=5)
            tries += 1
        if msg is None or msg.param_id != name:
            failures.append(f"{name}({desc}): 未收到 PARAM_VALUE")
            continue
        got = _decode(msg)
        if abs(got - expected) > max(1e-4, abs(expected) * 1e-4):
            failures.append(f"{name}({desc}): 期望 {expected},實得 {got}")
        else:
            print(f"[failsafe] {name} = {got} OK — {desc}")

    if failures:
        for f in failures:
            print(f"[failsafe] FAIL {f}", file=sys.stderr)
        return 1
    print(f"[failsafe] PASS:{len(FAILSAFE_MATRIX)} 項失效保護參數 = §4 矩陣口徑")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

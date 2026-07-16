#!/usr/bin/env python3
"""圍欄上傳-回讀 SITL 容量實測(F8)。

用 tools/geofence 轉出的 fence items,以 MAVLink MISSION 協定
(MISSION_TYPE_FENCE)上傳到 SITL,再回讀比對。遞增找出 posix dataman
實際容量(代理量測——非 FC-H7 flash;firmware.md §2 口徑)。

⚠️ posix dataman 容量 ≠ 實機;本量測只作 SITL 代理,rev A 實測定容不變。

用法:python assert_geofence.py --port 14540 --polygons 1 --vertices 32
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from pymavlink import mavutil

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "tools" / "geofence"))
from geofence import Polygon, to_fence_items  # noqa: E402

MAV_MISSION_TYPE_FENCE = 1
MAV_MISSION_ACCEPTED = 0


def _synthetic_polygon(n_vertices: int) -> Polygon:
    """在台北附近生成 n 頂點的凸多邊形(圓周取樣)。"""
    import math

    cx, cy, r = 25.033, 121.5654, 0.003
    verts = [
        (cx + r * math.cos(2 * math.pi * i / n_vertices),
         cy + r * math.sin(2 * math.pi * i / n_vertices))
        for i in range(n_vertices)
    ]
    return Polygon(verts)


def upload_fence(conn, items: list[dict], timeout: float = 30.0) -> bool:
    """MISSION 協定上傳 fence items;回傳是否 ACCEPTED。"""
    conn.mav.mission_count_send(
        conn.target_system, conn.target_component, len(items), MAV_MISSION_TYPE_FENCE
    )
    deadline = time.monotonic() + timeout
    sent = set()
    while time.monotonic() < deadline:
        msg = conn.recv_match(
            type=["MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK"],
            blocking=True, timeout=5,
        )
        if msg is None:
            continue
        mtype = msg.get_type()
        if mtype == "MISSION_ACK":
            if getattr(msg, "mission_type", MAV_MISSION_TYPE_FENCE) != MAV_MISSION_TYPE_FENCE:
                continue
            return msg.type == MAV_MISSION_ACCEPTED
        seq = msg.seq
        it = items[seq]
        conn.mav.mission_item_int_send(
            conn.target_system, conn.target_component, seq,
            it["frame"], it["command"], 0, 1,
            it["param1"], it["param2"], it["param3"], it["param4"],
            it["x"], it["y"], it["z"], MAV_MISSION_TYPE_FENCE,
        )
        sent.add(seq)
    print(f"[geofence] 上傳逾時(已送 {len(sent)}/{len(items)})", file=sys.stderr)
    return False


def readback_count(conn, timeout: float = 15.0) -> int:
    """回讀 fence 項目數(MISSION_COUNT)。"""
    conn.mav.mission_request_list_send(
        conn.target_system, conn.target_component, MAV_MISSION_TYPE_FENCE
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = conn.recv_match(type="MISSION_COUNT", blocking=True, timeout=5)
        if msg is None:
            continue
        if getattr(msg, "mission_type", MAV_MISSION_TYPE_FENCE) == MAV_MISSION_TYPE_FENCE:
            return msg.count
    return -1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=14540)
    parser.add_argument("--polygons", type=int, default=1)
    parser.add_argument("--vertices", type=int, default=32)
    args = parser.parse_args()

    polys = [_synthetic_polygon(args.vertices) for _ in range(args.polygons)]
    items = to_fence_items(polys, [])
    total = len(items)

    conn = mavutil.mavlink_connection(f"udpin:0.0.0.0:{args.port}")
    if conn.wait_heartbeat(timeout=30) is None:
        print("[geofence] 30s 內無 heartbeat", file=sys.stderr)
        return 1

    print(f"[geofence] 上傳 {args.polygons} 多邊形 × {args.vertices} 頂點 = {total} items")
    if not upload_fence(conn, items):
        print("[geofence] FAIL:上傳未 ACCEPTED", file=sys.stderr)
        return 1

    count = readback_count(conn)
    if count != total:
        print(f"[geofence] FAIL:回讀 {count} ≠ 上傳 {total}", file=sys.stderr)
        return 1
    print(f"[geofence] PASS:上傳-回讀往返一致({total} items;SITL dataman 代理量測)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

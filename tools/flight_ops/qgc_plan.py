"""QGC `.plan` → 本專案任務契約轉換器(GCS 軌 G4)。

輸入:QGC Plan JSON(`gcs/qgc-profiles/plans/` 範本同格式)。
輸出兩種目標(同一份 waypoints 語意):
- ``to_mission_plan()``:機上 MissionPlan dict(proto3 JSON 慣例 camelCase,
  可直接餵 `tools/dispatch_mission.py`,契約 = interfaces/proto mission.proto)
- ``to_route_create()``:mission-svc `POST /api/v1/routes` body(snake_case)

轉換規則(誠實邊界:只支援本專案範本用到的 SimpleItem 子集):
- cmd 22(TAKEOFF):取其座標/高度為首航點(hold 0)
- cmd 16(WAYPOINT):params[0] = hold 秒
- cmd 19(LOITER_TIME):params[0] = hold 秒(等同停留航點)
- cmd 20(RTL):僅允許出現在末項 → rtl_after_last=True;其餘位置報錯
- 其他 command / ComplexItem(測繪網格等)→ ValueError 列明不支援,
  不做臆測性降級(QGC 端先「轉換為航點任務」再匯出)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAV_CMD_WAYPOINT = 16
MAV_CMD_LOITER_TIME = 19
MAV_CMD_RTL = 20
MAV_CMD_TAKEOFF = 22

_SUPPORTED = {MAV_CMD_WAYPOINT, MAV_CMD_LOITER_TIME, MAV_CMD_RTL, MAV_CMD_TAKEOFF}


def parse_plan(path: str | Path) -> tuple[list[dict[str, float]], bool]:
    """解析 .plan,回傳 (waypoints, rtl_after_last)。waypoint 鍵為 snake_case。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("fileType") != "Plan":
        raise ValueError(f"非 QGC Plan 檔(fileType={data.get('fileType')!r})")
    items: list[dict[str, Any]] = data.get("mission", {}).get("items", [])
    if not items:
        raise ValueError("mission.items 為空")

    waypoints: list[dict[str, float]] = []
    rtl_after_last = False
    for idx, item in enumerate(items):
        if item.get("type") != "SimpleItem":
            raise ValueError(
                f"item {idx}: 不支援 {item.get('type')}(ComplexItem 請先在 QGC"
                " 轉換為航點任務再匯出)"
            )
        cmd = item.get("command")
        if cmd not in _SUPPORTED:
            raise ValueError(f"item {idx}: 不支援 MAV_CMD {cmd}")
        if cmd == MAV_CMD_RTL:
            if idx != len(items) - 1:
                raise ValueError(f"item {idx}: RTL 僅允許為末項")
            rtl_after_last = True
            continue

        params = item.get("params", [])
        if len(params) < 7:
            raise ValueError(f"item {idx}: params 長度不足({len(params)})")
        lat, lon, alt = params[4], params[5], params[6]
        if lat is None or lon is None or alt is None:
            raise ValueError(f"item {idx}: 座標/高度缺失")
        hold_s = 0.0
        if cmd in (MAV_CMD_WAYPOINT, MAV_CMD_LOITER_TIME):
            hold_s = float(params[0] or 0.0)
        waypoints.append(
            {
                "lat_deg": float(lat),
                "lon_deg": float(lon),
                "rel_alt_m": float(alt),
                "hold_s": hold_s,
                "speed_ms": 0.0,  # .plan 無逐點速度;0 = 機上用預設
            }
        )

    if not waypoints:
        raise ValueError("轉換後無航點(只有 RTL?)")
    return waypoints, rtl_after_last


def to_mission_plan(path: str | Path, mission_id: str) -> dict[str, Any]:
    """轉為機上 MissionPlan dict(proto3 JSON camelCase,dispatch_mission 可用)。"""
    if not mission_id:
        raise ValueError("mission_id 不可為空")
    waypoints, rtl = parse_plan(path)
    return {
        "missionId": mission_id,
        "waypoints": [
            {
                "latDeg": w["lat_deg"],
                "lonDeg": w["lon_deg"],
                "relAltM": w["rel_alt_m"],
                "holdS": w["hold_s"],
                "speedMs": w["speed_ms"],
            }
            for w in waypoints
        ],
        "rtlAfterLast": rtl,
    }


def to_route_create(path: str | Path, name: str) -> dict[str, Any]:
    """轉為 mission-svc POST /api/v1/routes body(rtl_after_last 在 Route 層)。"""
    if not name:
        raise ValueError("name 不可為空")
    waypoints, rtl = parse_plan(path)
    return {"name": name, "waypoints": waypoints, "rtl_after_last": rtl}

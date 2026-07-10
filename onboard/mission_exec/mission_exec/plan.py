"""任務檔載入與驗證。

任務檔格式 = drone.v1.MissionPlan 的 proto3 JSON mapping,
由 google.protobuf.json_format.Parse 解析,天然受 proto 契約約束。
"""

from pathlib import Path

from drone.v1 import mission_pb2
from google.protobuf import json_format


def load_plan(path: str | Path) -> mission_pb2.MissionPlan:
    """載入並驗證任務檔,回傳 MissionPlan;任何問題 raise ValueError(中文訊息)。"""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"無法讀取任務檔 {path}:{e}") from e

    plan = mission_pb2.MissionPlan()
    try:
        json_format.Parse(text, plan)
    except json_format.ParseError as e:
        raise ValueError(f"任務檔 {path} 不是合法的 MissionPlan JSON:{e}") from e

    validate_plan(plan)
    return plan


def validate_plan(plan: mission_pb2.MissionPlan) -> None:
    """語意驗證:mission_id 非空、waypoints 非空、經緯度在合法範圍。"""
    if not plan.mission_id:
        raise ValueError("任務驗證失敗:mission_id 不可為空")
    if not plan.waypoints:
        raise ValueError("任務驗證失敗:waypoints 不可為空(至少需要一個航點)")
    for i, wp in enumerate(plan.waypoints):
        if not -90.0 <= wp.lat_deg <= 90.0:
            raise ValueError(f"任務驗證失敗:航點 {i} 緯度 {wp.lat_deg} 超出 [-90, 90]")
        if not -180.0 <= wp.lon_deg <= 180.0:
            raise ValueError(f"任務驗證失敗:航點 {i} 經度 {wp.lon_deg} 超出 [-180, 180]")

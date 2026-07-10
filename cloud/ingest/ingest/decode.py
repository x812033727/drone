"""MQTT payload(proto3 JSON)→ proto 物件 → DB row 的純函式,供 main 與測試共用。

注意:proto3 JSON mapping 中 int64 序列化為字串,json_format.Parse 會處理;
不要自己 json.loads 後取欄位。
"""

from datetime import datetime, timezone

from drone.v1 import mission_pb2, telemetry_pb2
from google.protobuf import json_format

TELEMETRY_COLUMNS = (
    "time",
    "drone_id",
    "lat_deg",
    "lon_deg",
    "rel_alt_m",
    "heading_deg",
    "ground_speed_ms",
    "flight_mode",
    "armed",
    "battery_v",
    "battery_pct",
    "health_all_ok",
)

MISSION_COLUMNS = (
    "time",
    "mission_id",
    "drone_id",
    "current_item",
    "total_items",
    "state",
)


def _ms_to_dt(unix_time_ms: int) -> datetime:
    return datetime.fromtimestamp(unix_time_ms / 1000.0, tz=timezone.utc)


def telemetry_row(payload: bytes | str) -> tuple:
    """fleet/{id}/telemetry 的 JSON payload → telemetry 表 row(依 TELEMETRY_COLUMNS 順序)。"""
    msg = json_format.Parse(payload, telemetry_pb2.TelemetrySummary())
    return (
        _ms_to_dt(msg.unix_time_ms),
        msg.drone_id,
        msg.lat_deg,
        msg.lon_deg,
        msg.rel_alt_m,
        msg.heading_deg,
        msg.ground_speed_ms,
        msg.flight_mode,
        msg.armed,
        msg.battery_v,
        msg.battery_pct,
        msg.health_all_ok,
    )


def mission_row(payload: bytes | str) -> tuple:
    """fleet/{id}/mission/progress 的 JSON payload → mission_progress 表 row。"""
    msg = json_format.Parse(payload, mission_pb2.MissionProgress())
    return (
        _ms_to_dt(msg.unix_time_ms),
        msg.mission_id,
        msg.drone_id,
        msg.current_item,
        msg.total_items,
        mission_pb2.MissionProgress.State.Name(msg.state),
    )

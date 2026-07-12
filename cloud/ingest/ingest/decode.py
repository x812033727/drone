"""MQTT payload(proto3 JSON)→ proto 物件 → DB row 的純函式,供 main 與測試共用。

注意:proto3 JSON mapping 中 int64 序列化為字串,json_format.Parse 會處理;
不要自己 json.loads 後取欄位。
"""

from datetime import datetime, timezone

from drone.v1 import device_pb2, events_pb2, mission_pb2, sensors_pb2, telemetry_pb2
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
    "satellites",
    "gps_fix_type",
    "hdop",
    "vertical_speed_ms",
)

EVENT_COLUMNS = (
    "time",
    "drone_id",
    "event",
)

DEVICE_HEARTBEAT_COLUMNS = (
    "time",
    "drone_id",
    "agent_version",
    "firmware_version",
    "boot_time",
    "uptime_s",
)

MISSION_COLUMNS = (
    "time",
    "mission_id",
    "drone_id",
    "current_item",
    "total_items",
    "state",
)

# v0.4.0 高頻感測器流(fleet/{id}/sensors/*,QoS 0)
SENSOR_ATTITUDE_COLUMNS = (
    "time",
    "drone_id",
    "px4_timestamp_us",
    "q_w",
    "q_x",
    "q_y",
    "q_z",
)

SENSOR_GPS_COLUMNS = (
    "time",
    "drone_id",
    "px4_timestamp_us",
    "latitude_deg",
    "longitude_deg",
    "altitude_msl_m",
    "satellites_used",
    "hdop",
    "vdop",
    "fix_type",
)

SENSOR_LOCAL_POSITION_COLUMNS = (
    "time",
    "drone_id",
    "px4_timestamp_us",
    "x",
    "y",
    "z",
    "vx",
    "vy",
    "vz",
    "heading",
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
        msg.satellites,
        msg.gps_fix_type,
        msg.hdop,
        msg.vertical_speed_ms,
    )


def event_row(payload: bytes | str) -> tuple:
    """fleet/{id}/events 的 JSON payload → flight_events 表 row(依 EVENT_COLUMNS 順序)。"""
    msg = json_format.Parse(payload, events_pb2.FlightEvent())
    return (
        _ms_to_dt(msg.unix_time_ms),
        msg.drone_id,
        events_pb2.FlightEvent.Event.Name(msg.event),
    )


def device_heartbeat_row(payload: bytes | str) -> tuple:
    """fleet/{id}/heartbeat 的 JSON payload → device_heartbeat 表 row。"""
    msg = json_format.Parse(payload, device_pb2.DeviceHeartbeat())
    return (
        _ms_to_dt(msg.unix_time_ms),
        msg.drone_id,
        msg.agent_version,
        msg.firmware_version,
        _ms_to_dt(msg.boot_unix_ms),
        msg.uptime_s,
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


def sensor_attitude_row(payload: bytes | str) -> tuple:
    """fleet/{id}/sensors/attitude 的 JSON payload → sensor_attitude 表 row。"""
    msg = json_format.Parse(payload, sensors_pb2.SensorAttitude())
    q = list(msg.q)
    if len(q) != 4:
        # 契約:q 為 Hamilton (w,x,y,z) 4 元素;缺元素視同壞 payload 丟棄
        raise ValueError(f"q 需為 4 元素四元數,收到 {len(q)} 元素")
    return (
        _ms_to_dt(msg.unix_time_ms),
        msg.drone_id,
        msg.px4_timestamp_us,
        q[0],
        q[1],
        q[2],
        q[3],
    )


def sensor_gps_row(payload: bytes | str) -> tuple:
    """fleet/{id}/sensors/gps 的 JSON payload → sensor_gps 表 row。"""
    msg = json_format.Parse(payload, sensors_pb2.SensorGps())
    return (
        _ms_to_dt(msg.unix_time_ms),
        msg.drone_id,
        msg.px4_timestamp_us,
        msg.latitude_deg,
        msg.longitude_deg,
        msg.altitude_msl_m,
        msg.satellites_used,
        msg.hdop,
        msg.vdop,
        msg.fix_type,
    )


def sensor_local_position_row(payload: bytes | str) -> tuple:
    """fleet/{id}/sensors/local_position 的 JSON payload → sensor_local_position 表 row。"""
    msg = json_format.Parse(payload, sensors_pb2.SensorLocalPosition())
    return (
        _ms_to_dt(msg.unix_time_ms),
        msg.drone_id,
        msg.px4_timestamp_us,
        msg.x,
        msg.y,
        msg.z,
        msg.vx,
        msg.vy,
        msg.vz,
        msg.heading,
    )

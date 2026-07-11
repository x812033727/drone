from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class TelemetrySummary(_message.Message):
    __slots__ = ("drone_id", "unix_time_ms", "lat_deg", "lon_deg", "rel_alt_m", "heading_deg", "ground_speed_ms", "flight_mode", "armed", "battery_v", "battery_pct", "health_all_ok", "satellites", "gps_fix_type", "hdop", "vertical_speed_ms")
    DRONE_ID_FIELD_NUMBER: _ClassVar[int]
    UNIX_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    LAT_DEG_FIELD_NUMBER: _ClassVar[int]
    LON_DEG_FIELD_NUMBER: _ClassVar[int]
    REL_ALT_M_FIELD_NUMBER: _ClassVar[int]
    HEADING_DEG_FIELD_NUMBER: _ClassVar[int]
    GROUND_SPEED_MS_FIELD_NUMBER: _ClassVar[int]
    FLIGHT_MODE_FIELD_NUMBER: _ClassVar[int]
    ARMED_FIELD_NUMBER: _ClassVar[int]
    BATTERY_V_FIELD_NUMBER: _ClassVar[int]
    BATTERY_PCT_FIELD_NUMBER: _ClassVar[int]
    HEALTH_ALL_OK_FIELD_NUMBER: _ClassVar[int]
    SATELLITES_FIELD_NUMBER: _ClassVar[int]
    GPS_FIX_TYPE_FIELD_NUMBER: _ClassVar[int]
    HDOP_FIELD_NUMBER: _ClassVar[int]
    VERTICAL_SPEED_MS_FIELD_NUMBER: _ClassVar[int]
    drone_id: str
    unix_time_ms: int
    lat_deg: float
    lon_deg: float
    rel_alt_m: float
    heading_deg: float
    ground_speed_ms: float
    flight_mode: str
    armed: bool
    battery_v: float
    battery_pct: float
    health_all_ok: bool
    satellites: int
    gps_fix_type: str
    hdop: float
    vertical_speed_ms: float
    def __init__(self, drone_id: _Optional[str] = ..., unix_time_ms: _Optional[int] = ..., lat_deg: _Optional[float] = ..., lon_deg: _Optional[float] = ..., rel_alt_m: _Optional[float] = ..., heading_deg: _Optional[float] = ..., ground_speed_ms: _Optional[float] = ..., flight_mode: _Optional[str] = ..., armed: _Optional[bool] = ..., battery_v: _Optional[float] = ..., battery_pct: _Optional[float] = ..., health_all_ok: _Optional[bool] = ..., satellites: _Optional[int] = ..., gps_fix_type: _Optional[str] = ..., hdop: _Optional[float] = ..., vertical_speed_ms: _Optional[float] = ...) -> None: ...

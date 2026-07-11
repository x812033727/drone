from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class SensorAttitude(_message.Message):
    __slots__ = ("drone_id", "unix_time_ms", "px4_timestamp_us", "q")
    DRONE_ID_FIELD_NUMBER: _ClassVar[int]
    UNIX_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    PX4_TIMESTAMP_US_FIELD_NUMBER: _ClassVar[int]
    Q_FIELD_NUMBER: _ClassVar[int]
    drone_id: str
    unix_time_ms: int
    px4_timestamp_us: int
    q: _containers.RepeatedScalarFieldContainer[float]
    def __init__(self, drone_id: _Optional[str] = ..., unix_time_ms: _Optional[int] = ..., px4_timestamp_us: _Optional[int] = ..., q: _Optional[_Iterable[float]] = ...) -> None: ...

class SensorGps(_message.Message):
    __slots__ = ("drone_id", "unix_time_ms", "px4_timestamp_us", "latitude_deg", "longitude_deg", "altitude_msl_m", "satellites_used", "hdop", "vdop", "fix_type")
    DRONE_ID_FIELD_NUMBER: _ClassVar[int]
    UNIX_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    PX4_TIMESTAMP_US_FIELD_NUMBER: _ClassVar[int]
    LATITUDE_DEG_FIELD_NUMBER: _ClassVar[int]
    LONGITUDE_DEG_FIELD_NUMBER: _ClassVar[int]
    ALTITUDE_MSL_M_FIELD_NUMBER: _ClassVar[int]
    SATELLITES_USED_FIELD_NUMBER: _ClassVar[int]
    HDOP_FIELD_NUMBER: _ClassVar[int]
    VDOP_FIELD_NUMBER: _ClassVar[int]
    FIX_TYPE_FIELD_NUMBER: _ClassVar[int]
    drone_id: str
    unix_time_ms: int
    px4_timestamp_us: int
    latitude_deg: float
    longitude_deg: float
    altitude_msl_m: float
    satellites_used: int
    hdop: float
    vdop: float
    fix_type: str
    def __init__(self, drone_id: _Optional[str] = ..., unix_time_ms: _Optional[int] = ..., px4_timestamp_us: _Optional[int] = ..., latitude_deg: _Optional[float] = ..., longitude_deg: _Optional[float] = ..., altitude_msl_m: _Optional[float] = ..., satellites_used: _Optional[int] = ..., hdop: _Optional[float] = ..., vdop: _Optional[float] = ..., fix_type: _Optional[str] = ...) -> None: ...

class SensorLocalPosition(_message.Message):
    __slots__ = ("drone_id", "unix_time_ms", "px4_timestamp_us", "x", "y", "z", "vx", "vy", "vz", "heading")
    DRONE_ID_FIELD_NUMBER: _ClassVar[int]
    UNIX_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    PX4_TIMESTAMP_US_FIELD_NUMBER: _ClassVar[int]
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    Z_FIELD_NUMBER: _ClassVar[int]
    VX_FIELD_NUMBER: _ClassVar[int]
    VY_FIELD_NUMBER: _ClassVar[int]
    VZ_FIELD_NUMBER: _ClassVar[int]
    HEADING_FIELD_NUMBER: _ClassVar[int]
    drone_id: str
    unix_time_ms: int
    px4_timestamp_us: int
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    heading: float
    def __init__(self, drone_id: _Optional[str] = ..., unix_time_ms: _Optional[int] = ..., px4_timestamp_us: _Optional[int] = ..., x: _Optional[float] = ..., y: _Optional[float] = ..., z: _Optional[float] = ..., vx: _Optional[float] = ..., vy: _Optional[float] = ..., vz: _Optional[float] = ..., heading: _Optional[float] = ...) -> None: ...

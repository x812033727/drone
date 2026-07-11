from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Waypoint(_message.Message):
    __slots__ = ("lat_deg", "lon_deg", "rel_alt_m", "hold_s", "speed_ms")
    LAT_DEG_FIELD_NUMBER: _ClassVar[int]
    LON_DEG_FIELD_NUMBER: _ClassVar[int]
    REL_ALT_M_FIELD_NUMBER: _ClassVar[int]
    HOLD_S_FIELD_NUMBER: _ClassVar[int]
    SPEED_MS_FIELD_NUMBER: _ClassVar[int]
    lat_deg: float
    lon_deg: float
    rel_alt_m: float
    hold_s: float
    speed_ms: float
    def __init__(self, lat_deg: _Optional[float] = ..., lon_deg: _Optional[float] = ..., rel_alt_m: _Optional[float] = ..., hold_s: _Optional[float] = ..., speed_ms: _Optional[float] = ...) -> None: ...

class MissionPlan(_message.Message):
    __slots__ = ("mission_id", "waypoints", "rtl_after_last")
    MISSION_ID_FIELD_NUMBER: _ClassVar[int]
    WAYPOINTS_FIELD_NUMBER: _ClassVar[int]
    RTL_AFTER_LAST_FIELD_NUMBER: _ClassVar[int]
    mission_id: str
    waypoints: _containers.RepeatedCompositeFieldContainer[Waypoint]
    rtl_after_last: bool
    def __init__(self, mission_id: _Optional[str] = ..., waypoints: _Optional[_Iterable[_Union[Waypoint, _Mapping]]] = ..., rtl_after_last: _Optional[bool] = ...) -> None: ...

class MissionProgress(_message.Message):
    __slots__ = ("mission_id", "drone_id", "current_item", "total_items", "state", "unix_time_ms")
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATE_UNSPECIFIED: _ClassVar[MissionProgress.State]
        STATE_RECEIVED: _ClassVar[MissionProgress.State]
        STATE_UPLOADED: _ClassVar[MissionProgress.State]
        STATE_IN_PROGRESS: _ClassVar[MissionProgress.State]
        STATE_COMPLETED: _ClassVar[MissionProgress.State]
        STATE_FAILED: _ClassVar[MissionProgress.State]
        STATE_PAUSED: _ClassVar[MissionProgress.State]
    STATE_UNSPECIFIED: MissionProgress.State
    STATE_RECEIVED: MissionProgress.State
    STATE_UPLOADED: MissionProgress.State
    STATE_IN_PROGRESS: MissionProgress.State
    STATE_COMPLETED: MissionProgress.State
    STATE_FAILED: MissionProgress.State
    STATE_PAUSED: MissionProgress.State
    MISSION_ID_FIELD_NUMBER: _ClassVar[int]
    DRONE_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_ITEM_FIELD_NUMBER: _ClassVar[int]
    TOTAL_ITEMS_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    UNIX_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    mission_id: str
    drone_id: str
    current_item: int
    total_items: int
    state: MissionProgress.State
    unix_time_ms: int
    def __init__(self, mission_id: _Optional[str] = ..., drone_id: _Optional[str] = ..., current_item: _Optional[int] = ..., total_items: _Optional[int] = ..., state: _Optional[_Union[MissionProgress.State, str]] = ..., unix_time_ms: _Optional[int] = ...) -> None: ...

class MissionCommand(_message.Message):
    __slots__ = ("mission_id", "command", "unix_time_ms")
    class Command(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        COMMAND_UNSPECIFIED: _ClassVar[MissionCommand.Command]
        COMMAND_PAUSE: _ClassVar[MissionCommand.Command]
        COMMAND_RESUME: _ClassVar[MissionCommand.Command]
        COMMAND_ABORT: _ClassVar[MissionCommand.Command]
    COMMAND_UNSPECIFIED: MissionCommand.Command
    COMMAND_PAUSE: MissionCommand.Command
    COMMAND_RESUME: MissionCommand.Command
    COMMAND_ABORT: MissionCommand.Command
    MISSION_ID_FIELD_NUMBER: _ClassVar[int]
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    UNIX_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    mission_id: str
    command: MissionCommand.Command
    unix_time_ms: int
    def __init__(self, mission_id: _Optional[str] = ..., command: _Optional[_Union[MissionCommand.Command, str]] = ..., unix_time_ms: _Optional[int] = ...) -> None: ...

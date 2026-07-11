from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FlightEvent(_message.Message):
    __slots__ = ("drone_id", "unix_time_ms", "event")
    class Event(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        EVENT_UNSPECIFIED: _ClassVar[FlightEvent.Event]
        EVENT_ARMED: _ClassVar[FlightEvent.Event]
        EVENT_DISARMED: _ClassVar[FlightEvent.Event]
    EVENT_UNSPECIFIED: FlightEvent.Event
    EVENT_ARMED: FlightEvent.Event
    EVENT_DISARMED: FlightEvent.Event
    DRONE_ID_FIELD_NUMBER: _ClassVar[int]
    UNIX_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    EVENT_FIELD_NUMBER: _ClassVar[int]
    drone_id: str
    unix_time_ms: int
    event: FlightEvent.Event
    def __init__(self, drone_id: _Optional[str] = ..., unix_time_ms: _Optional[int] = ..., event: _Optional[_Union[FlightEvent.Event, str]] = ...) -> None: ...

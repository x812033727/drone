from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class DeviceHeartbeat(_message.Message):
    __slots__ = ("drone_id", "unix_time_ms", "agent_version", "firmware_version", "boot_unix_ms", "uptime_s")
    DRONE_ID_FIELD_NUMBER: _ClassVar[int]
    UNIX_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    AGENT_VERSION_FIELD_NUMBER: _ClassVar[int]
    FIRMWARE_VERSION_FIELD_NUMBER: _ClassVar[int]
    BOOT_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    UPTIME_S_FIELD_NUMBER: _ClassVar[int]
    drone_id: str
    unix_time_ms: int
    agent_version: str
    firmware_version: str
    boot_unix_ms: int
    uptime_s: int
    def __init__(self, drone_id: _Optional[str] = ..., unix_time_ms: _Optional[int] = ..., agent_version: _Optional[str] = ..., firmware_version: _Optional[str] = ..., boot_unix_ms: _Optional[int] = ..., uptime_s: _Optional[int] = ...) -> None: ...

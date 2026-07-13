from drone.v1 import mission_pb2 as _mission_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FleetMission(_message.Message):
    __slots__ = ("mission_id", "plan", "status", "priority", "fleet_id", "required_capabilities", "window_start_unix_ms", "window_end_unix_ms", "assigned_drone_id", "parent_mission_id", "created_unix_ms", "updated_unix_ms")
    class Status(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATUS_UNSPECIFIED: _ClassVar[FleetMission.Status]
        STATUS_CREATED: _ClassVar[FleetMission.Status]
        STATUS_ASSIGNED: _ClassVar[FleetMission.Status]
        STATUS_EXECUTING: _ClassVar[FleetMission.Status]
        STATUS_COMPLETED: _ClassVar[FleetMission.Status]
        STATUS_CANCELLED: _ClassVar[FleetMission.Status]
    STATUS_UNSPECIFIED: FleetMission.Status
    STATUS_CREATED: FleetMission.Status
    STATUS_ASSIGNED: FleetMission.Status
    STATUS_EXECUTING: FleetMission.Status
    STATUS_COMPLETED: FleetMission.Status
    STATUS_CANCELLED: FleetMission.Status
    MISSION_ID_FIELD_NUMBER: _ClassVar[int]
    PLAN_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    FLEET_ID_FIELD_NUMBER: _ClassVar[int]
    REQUIRED_CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    WINDOW_START_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    WINDOW_END_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    ASSIGNED_DRONE_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_MISSION_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    UPDATED_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    mission_id: str
    plan: _mission_pb2.MissionPlan
    status: FleetMission.Status
    priority: int
    fleet_id: str
    required_capabilities: _containers.RepeatedScalarFieldContainer[str]
    window_start_unix_ms: int
    window_end_unix_ms: int
    assigned_drone_id: str
    parent_mission_id: str
    created_unix_ms: int
    updated_unix_ms: int
    def __init__(self, mission_id: _Optional[str] = ..., plan: _Optional[_Union[_mission_pb2.MissionPlan, _Mapping]] = ..., status: _Optional[_Union[FleetMission.Status, str]] = ..., priority: _Optional[int] = ..., fleet_id: _Optional[str] = ..., required_capabilities: _Optional[_Iterable[str]] = ..., window_start_unix_ms: _Optional[int] = ..., window_end_unix_ms: _Optional[int] = ..., assigned_drone_id: _Optional[str] = ..., parent_mission_id: _Optional[str] = ..., created_unix_ms: _Optional[int] = ..., updated_unix_ms: _Optional[int] = ...) -> None: ...

class MissionAssignment(_message.Message):
    __slots__ = ("assignment_id", "mission_id", "drone_id", "status", "preflight_checks", "reject_reason", "assigned_unix_ms")
    class Status(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STATUS_UNSPECIFIED: _ClassVar[MissionAssignment.Status]
        STATUS_PENDING: _ClassVar[MissionAssignment.Status]
        STATUS_ACCEPTED: _ClassVar[MissionAssignment.Status]
        STATUS_REJECTED: _ClassVar[MissionAssignment.Status]
        STATUS_SUPERSEDED: _ClassVar[MissionAssignment.Status]
    STATUS_UNSPECIFIED: MissionAssignment.Status
    STATUS_PENDING: MissionAssignment.Status
    STATUS_ACCEPTED: MissionAssignment.Status
    STATUS_REJECTED: MissionAssignment.Status
    STATUS_SUPERSEDED: MissionAssignment.Status
    class PreflightCheck(_message.Message):
        __slots__ = ("name", "passed", "detail")
        NAME_FIELD_NUMBER: _ClassVar[int]
        PASSED_FIELD_NUMBER: _ClassVar[int]
        DETAIL_FIELD_NUMBER: _ClassVar[int]
        name: str
        passed: bool
        detail: str
        def __init__(self, name: _Optional[str] = ..., passed: _Optional[bool] = ..., detail: _Optional[str] = ...) -> None: ...
    ASSIGNMENT_ID_FIELD_NUMBER: _ClassVar[int]
    MISSION_ID_FIELD_NUMBER: _ClassVar[int]
    DRONE_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    PREFLIGHT_CHECKS_FIELD_NUMBER: _ClassVar[int]
    REJECT_REASON_FIELD_NUMBER: _ClassVar[int]
    ASSIGNED_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    assignment_id: str
    mission_id: str
    drone_id: str
    status: MissionAssignment.Status
    preflight_checks: _containers.RepeatedCompositeFieldContainer[MissionAssignment.PreflightCheck]
    reject_reason: str
    assigned_unix_ms: int
    def __init__(self, assignment_id: _Optional[str] = ..., mission_id: _Optional[str] = ..., drone_id: _Optional[str] = ..., status: _Optional[_Union[MissionAssignment.Status, str]] = ..., preflight_checks: _Optional[_Iterable[_Union[MissionAssignment.PreflightCheck, _Mapping]]] = ..., reject_reason: _Optional[str] = ..., assigned_unix_ms: _Optional[int] = ...) -> None: ...

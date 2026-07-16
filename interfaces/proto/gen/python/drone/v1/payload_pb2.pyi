from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class PayloadStatus(_message.Message):
    __slots__ = ("drone_id", "unix_time_ms", "time_boot_ms", "payload_type", "payload_id", "state", "fault_flags", "temperature_cdegc", "firmware_version", "vendor_status")
    DRONE_ID_FIELD_NUMBER: _ClassVar[int]
    UNIX_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    TIME_BOOT_MS_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_TYPE_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    FAULT_FLAGS_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_CDEGC_FIELD_NUMBER: _ClassVar[int]
    FIRMWARE_VERSION_FIELD_NUMBER: _ClassVar[int]
    VENDOR_STATUS_FIELD_NUMBER: _ClassVar[int]
    drone_id: str
    unix_time_ms: int
    time_boot_ms: int
    payload_type: int
    payload_id: int
    state: int
    fault_flags: int
    temperature_cdegc: int
    firmware_version: int
    vendor_status: int
    def __init__(self, drone_id: _Optional[str] = ..., unix_time_ms: _Optional[int] = ..., time_boot_ms: _Optional[int] = ..., payload_type: _Optional[int] = ..., payload_id: _Optional[int] = ..., state: _Optional[int] = ..., fault_flags: _Optional[int] = ..., temperature_cdegc: _Optional[int] = ..., firmware_version: _Optional[int] = ..., vendor_status: _Optional[int] = ...) -> None: ...

class SprayTelemetry(_message.Message):
    __slots__ = ("drone_id", "unix_time_ms", "time_boot_ms", "flow_rate_ml_s", "flow_rate_setpoint_ml_s", "volume_remaining_ml", "volume_consumed_ml", "application_rate_ml_m2", "pump_pressure_bar", "boom_width_m", "spray_flags", "pump_state", "nozzles_active")
    DRONE_ID_FIELD_NUMBER: _ClassVar[int]
    UNIX_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    TIME_BOOT_MS_FIELD_NUMBER: _ClassVar[int]
    FLOW_RATE_ML_S_FIELD_NUMBER: _ClassVar[int]
    FLOW_RATE_SETPOINT_ML_S_FIELD_NUMBER: _ClassVar[int]
    VOLUME_REMAINING_ML_FIELD_NUMBER: _ClassVar[int]
    VOLUME_CONSUMED_ML_FIELD_NUMBER: _ClassVar[int]
    APPLICATION_RATE_ML_M2_FIELD_NUMBER: _ClassVar[int]
    PUMP_PRESSURE_BAR_FIELD_NUMBER: _ClassVar[int]
    BOOM_WIDTH_M_FIELD_NUMBER: _ClassVar[int]
    SPRAY_FLAGS_FIELD_NUMBER: _ClassVar[int]
    PUMP_STATE_FIELD_NUMBER: _ClassVar[int]
    NOZZLES_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    drone_id: str
    unix_time_ms: int
    time_boot_ms: int
    flow_rate_ml_s: float
    flow_rate_setpoint_ml_s: float
    volume_remaining_ml: float
    volume_consumed_ml: float
    application_rate_ml_m2: float
    pump_pressure_bar: float
    boom_width_m: float
    spray_flags: int
    pump_state: int
    nozzles_active: int
    def __init__(self, drone_id: _Optional[str] = ..., unix_time_ms: _Optional[int] = ..., time_boot_ms: _Optional[int] = ..., flow_rate_ml_s: _Optional[float] = ..., flow_rate_setpoint_ml_s: _Optional[float] = ..., volume_remaining_ml: _Optional[float] = ..., volume_consumed_ml: _Optional[float] = ..., application_rate_ml_m2: _Optional[float] = ..., pump_pressure_bar: _Optional[float] = ..., boom_width_m: _Optional[float] = ..., spray_flags: _Optional[int] = ..., pump_state: _Optional[int] = ..., nozzles_active: _Optional[int] = ...) -> None: ...

class BatteryDetail(_message.Message):
    __slots__ = ("drone_id", "unix_time_ms", "time_boot_ms", "fault_flags", "capacity_full_charge_mah", "capacity_remaining_mah", "cell_voltages_mv", "cycle_count", "temperature_cdegc", "current_ca", "id", "cell_count", "state_of_health", "state_of_charge")
    DRONE_ID_FIELD_NUMBER: _ClassVar[int]
    UNIX_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    TIME_BOOT_MS_FIELD_NUMBER: _ClassVar[int]
    FAULT_FLAGS_FIELD_NUMBER: _ClassVar[int]
    CAPACITY_FULL_CHARGE_MAH_FIELD_NUMBER: _ClassVar[int]
    CAPACITY_REMAINING_MAH_FIELD_NUMBER: _ClassVar[int]
    CELL_VOLTAGES_MV_FIELD_NUMBER: _ClassVar[int]
    CYCLE_COUNT_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_CDEGC_FIELD_NUMBER: _ClassVar[int]
    CURRENT_CA_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    CELL_COUNT_FIELD_NUMBER: _ClassVar[int]
    STATE_OF_HEALTH_FIELD_NUMBER: _ClassVar[int]
    STATE_OF_CHARGE_FIELD_NUMBER: _ClassVar[int]
    drone_id: str
    unix_time_ms: int
    time_boot_ms: int
    fault_flags: int
    capacity_full_charge_mah: int
    capacity_remaining_mah: int
    cell_voltages_mv: _containers.RepeatedScalarFieldContainer[int]
    cycle_count: int
    temperature_cdegc: int
    current_ca: int
    id: int
    cell_count: int
    state_of_health: int
    state_of_charge: int
    def __init__(self, drone_id: _Optional[str] = ..., unix_time_ms: _Optional[int] = ..., time_boot_ms: _Optional[int] = ..., fault_flags: _Optional[int] = ..., capacity_full_charge_mah: _Optional[int] = ..., capacity_remaining_mah: _Optional[int] = ..., cell_voltages_mv: _Optional[_Iterable[int]] = ..., cycle_count: _Optional[int] = ..., temperature_cdegc: _Optional[int] = ..., current_ca: _Optional[int] = ..., id: _Optional[int] = ..., cell_count: _Optional[int] = ..., state_of_health: _Optional[int] = ..., state_of_charge: _Optional[int] = ...) -> None: ...

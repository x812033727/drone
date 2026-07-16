"""payload_listener 轉換層:duck-typed MAVLink 假訊息 → proto → JSON 契約往返。"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "interfaces/proto/gen/python"))

listener = pytest.importorskip("drone_agent.payload_listener")
payload_pb2 = pytest.importorskip("drone.v1.payload_pb2")


class FakeMsg(SimpleNamespace):
    def __init__(self, type_name: str, **fields):
        super().__init__(**fields)
        self._type = type_name

    def get_type(self) -> str:
        return self._type


def _payload_status_msg() -> FakeMsg:
    return FakeMsg(
        "PAYLOAD_STATUS",
        time_boot_ms=12_000, payload_type=3, payload_id=0, state=3,
        fault_flags=0, temperature=3550, firmware_version=(1 << 24), vendor_status=0,
    )


def _spray_msg() -> FakeMsg:
    return FakeMsg(
        "SPRAY_TELEMETRY",
        time_boot_ms=12_000, flow_rate=120.0, flow_rate_setpoint=120.0,
        volume_remaining=8800.0, volume_consumed=1200.0,
        application_rate=float("nan"), pump_pressure=2.5, boom_width=4.0,
        spray_flags=0, pump_state=2, nozzles_active=8,
    )


def _battery_msg() -> FakeMsg:
    return FakeMsg(
        "BATTERY_DETAIL",
        time_boot_ms=12_000, fault_flags=0, capacity_full_charge=16000,
        capacity_remaining=12000, cell_voltages=[3900] * 12 + [0xFFFF] * 2,
        cycle_count=42, temperature=2800, current=1500, id=0,
        cell_count=12, state_of_health=97, state_of_charge=75,
    )


def test_convert_payload_status_topic_and_fields():
    suffix, payload = listener.convert(_payload_status_msg(), "dev-9")
    assert suffix == "status"
    obj = json.loads(payload)
    assert obj["droneId"] == "dev-9"
    assert obj["payloadType"] == 3
    assert obj["temperatureCdegc"] == 3550


def test_convert_spray_preserves_nan():
    suffix, payload = listener.convert(_spray_msg(), "dev-9")
    assert suffix == "spray"
    obj = json.loads(payload)
    # proto3 JSON 對 NaN 序列化為字串 "NaN"(原樣保留無效值語意)
    assert obj["applicationRateMlM2"] == "NaN"
    assert obj["flowRateMlS"] == 120.0
    # 契約往返:JSON 能 Parse 回 proto
    from google.protobuf.json_format import Parse

    msg = Parse(payload, payload_pb2.SprayTelemetry())
    assert math.isnan(msg.application_rate_ml_m2)


def test_convert_battery_cell_slots():
    suffix, payload = listener.convert(_battery_msg(), "dev-9")
    assert suffix == "battery"
    obj = json.loads(payload)
    assert len(obj["cellVoltagesMv"]) == 14
    assert obj["cellVoltagesMv"][0] == 3900
    assert obj["cellVoltagesMv"][13] == 0xFFFF
    assert obj["cellCount"] == 12


def test_convert_unknown_type_returns_none():
    assert listener.convert(FakeMsg("HEARTBEAT"), "dev-9") is None


def test_explicit_unix_time_ms():
    proto = listener.to_payload_status(_payload_status_msg(), "dev-9", unix_time_ms=1234)
    assert proto.unix_time_ms == 1234

from datetime import datetime, timezone

from drone.v1 import events_pb2, mission_pb2, telemetry_pb2
from google.protobuf.json_format import MessageToJson
from ingest import decode


def test_telemetry_roundtrip():
    msg = telemetry_pb2.TelemetrySummary(
        drone_id="dev-1",
        unix_time_ms=1783147200123,
        lat_deg=25.033,
        lon_deg=121.565,
        rel_alt_m=35.5,
        heading_deg=182.0,
        ground_speed_ms=6.8,
        flight_mode="MISSION",
        armed=True,
        battery_v=15.8,
        battery_pct=87.5,
        health_all_ok=True,
        satellites=14,
        gps_fix_type="FIX_3D",
        hdop=0.8,
        vertical_speed_ms=-1.2,
    )
    row = decode.telemetry_row(MessageToJson(msg))
    assert len(row) == len(decode.TELEMETRY_COLUMNS)
    assert row[0] == datetime.fromtimestamp(1783147200.123, tz=timezone.utc)
    assert row[1] == "dev-1"
    assert row[7] == "MISSION"
    assert row[8] is True
    assert abs(row[10] - 87.5) < 1e-6
    # v0.3.0 新欄:satellites / gps_fix_type / hdop / vertical_speed_ms
    assert row[12] == 14
    assert row[13] == "FIX_3D"
    assert abs(row[14] - 0.8) < 1e-6
    assert abs(row[15] - (-1.2)) < 1e-6


def test_telemetry_v01_payload_without_new_fields():
    """向後相容:v0.1 機上韌體(無 v0.3.0 新欄)payload 落庫為 proto3 預設值。"""
    payload = '{"droneId": "dev-1", "unixTimeMs": "1783147200000", "latDeg": 25.0}'
    row = decode.telemetry_row(payload)
    assert len(row) == len(decode.TELEMETRY_COLUMNS)
    assert row[12] == 0
    assert row[13] == ""
    assert row[14] == 0.0
    assert row[15] == 0.0


def test_mission_roundtrip():
    msg = mission_pb2.MissionProgress(
        mission_id="m-001",
        drone_id="dev-1",
        current_item=3,
        total_items=8,
        state=mission_pb2.MissionProgress.STATE_IN_PROGRESS,
        unix_time_ms=1783147201456,
    )
    row = decode.mission_row(MessageToJson(msg))
    assert row[1:] == ("m-001", "dev-1", 3, 8, "STATE_IN_PROGRESS")


def test_int64_as_string():
    # proto3 JSON mapping:int64 是字串——確認 Parse 正確處理
    payload = '{"droneId": "dev-2", "unixTimeMs": "1783147200000", "latDeg": 25.0, "lonDeg": 121.5}'
    row = decode.telemetry_row(payload)
    assert row[0].year == 2026
    assert row[1] == "dev-2"


def test_event_roundtrip():
    msg = events_pb2.FlightEvent(
        drone_id="dev-1",
        unix_time_ms=1783147202789,
        event=events_pb2.FlightEvent.EVENT_ARMED,
    )
    row = decode.event_row(MessageToJson(msg))
    assert len(row) == len(decode.EVENT_COLUMNS)
    assert row[0] == datetime.fromtimestamp(1783147202.789, tz=timezone.utc)
    assert row[1:] == ("dev-1", "EVENT_ARMED")


def test_event_disarmed_snake_case_payload():
    # 機上實際線上格式(preserving_proto_field_name):snake_case + enum 名
    payload = '{"drone_id": "dev-2", "unix_time_ms": "1783147203000", "event": "EVENT_DISARMED"}'
    row = decode.event_row(payload)
    assert row[1:] == ("dev-2", "EVENT_DISARMED")

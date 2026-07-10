from datetime import datetime, timezone

from drone.v1 import mission_pb2, telemetry_pb2
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
    )
    row = decode.telemetry_row(MessageToJson(msg))
    assert len(row) == len(decode.TELEMETRY_COLUMNS)
    assert row[0] == datetime.fromtimestamp(1783147200.123, tz=timezone.utc)
    assert row[1] == "dev-1"
    assert row[7] == "MISSION"
    assert row[8] is True
    assert abs(row[10] - 87.5) < 1e-6


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

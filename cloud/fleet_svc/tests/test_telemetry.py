"""遙測解析純函式測試(需 drone-proto,CI 已安裝 interfaces/proto/gen/python)。"""

import json

from fleet_svc.telemetry import parse_telemetry


def test_parse_telemetry_basic():
    payload = json.dumps(
        {
            "droneId": "PA1-0001",
            "unixTimeMs": "1720000000000",  # proto3 JSON:int64 為字串
            "latDeg": 25.03,
            "lonDeg": 121.5,
            "relAltM": 42.0,
            "batteryPct": 88.0,
            "flightMode": "MISSION",
            "armed": True,
        }
    )
    d = parse_telemetry(payload)
    assert d["drone_id"] == "PA1-0001"
    assert d["unix_time_ms"] == 1720000000000
    assert d["lat_deg"] == 25.03
    assert d["flight_mode"] == "MISSION"
    assert d["armed"] is True


def test_parse_telemetry_defaults_for_missing_fields():
    d = parse_telemetry(json.dumps({"droneId": "X"}))
    assert d["drone_id"] == "X"
    assert d["armed"] is False
    assert d["battery_pct"] == 0.0

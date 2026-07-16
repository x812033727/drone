"""payload 三 row 函式:合法 payload 轉換(欄位/arity/NaN/陣列)+ 壞欄位拒絕。"""

import json
import math

import pytest
from google.protobuf.json_format import ParseError
from ingest import decode


def _status_payload() -> str:
    return json.dumps({
        "droneId": "d1", "unixTimeMs": "1752650000000", "timeBootMs": 12000,
        "payloadType": 3, "state": 3, "temperatureCdegc": 3550,
        "firmwareVersion": 16777216,
    })


def test_payload_status_row():
    row = decode.payload_status_row(_status_payload())
    assert len(row) == len(decode.PAYLOAD_STATUS_COLUMNS)
    assert row[1] == "d1" and row[3] == 3 and row[7] == 3550


def test_spray_row_nan_passthrough():
    payload = json.dumps({
        "droneId": "d1", "unixTimeMs": "1752650000000", "timeBootMs": 12000,
        "flowRateMlS": 120.0, "applicationRateMlM2": "NaN", "pumpState": 2,
    })
    row = decode.spray_telemetry_row(payload)
    assert len(row) == len(decode.SPRAY_TELEMETRY_COLUMNS)
    assert math.isnan(row[7])  # application_rate_ml_m2 原樣 NaN


def test_battery_row_cell_array():
    payload = json.dumps({
        "droneId": "d1", "unixTimeMs": "1752650000000",
        "cellVoltagesMv": [3900] * 12 + [65535, 65535], "cellCount": 12,
    })
    row = decode.battery_detail_row(payload)
    assert len(row) == len(decode.BATTERY_DETAIL_COLUMNS)
    cells = row[6]
    assert isinstance(cells, list) and len(cells) == 14 and cells[13] == 65535


def test_unknown_field_rejected():
    with pytest.raises(ParseError):
        decode.payload_status_row(json.dumps({"droneId": "d1", "bogusField": 1}))

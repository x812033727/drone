"""qgc_plan 轉換器:真實範本轉換 + 契約 Parse 硬證 + 不支援輸入的拒絕。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "interfaces/proto/gen/python"))

from flight_ops.qgc_plan import parse_plan, to_mission_plan, to_route_create  # noqa: E402

PLANS = _ROOT / "gcs" / "qgc-profiles" / "plans"
SURVEY = PLANS / "survey-rect-demo.plan"
INSPECT = PLANS / "inspect-point-demo.plan"


def test_survey_template_parses():
    waypoints, rtl = parse_plan(SURVEY)
    # 範本:takeoff + 4 角點,RTL 末項
    assert len(waypoints) == 5
    assert rtl is True
    assert waypoints[0]["rel_alt_m"] == 40.0
    assert all(21.5 <= w["lat_deg"] <= 25.5 for w in waypoints)


def test_inspect_template_loiter_hold():
    waypoints, rtl = parse_plan(INSPECT)
    assert rtl is True
    # cmd 19(LOITER_TIME)的 params[0] 轉 hold_s
    assert any(w["hold_s"] == 10.0 for w in waypoints)


def test_to_mission_plan_passes_proto_contract():
    """轉換器輸出必須能過 MissionPlan proto3 JSON Parse(契約硬證)。"""
    mission_pb2 = pytest.importorskip("drone.v1.mission_pb2")
    from google.protobuf import json_format

    d = to_mission_plan(SURVEY, "survey-demo-1")
    plan = mission_pb2.MissionPlan()
    json_format.Parse(json.dumps(d), plan)
    assert plan.mission_id == "survey-demo-1"
    assert len(plan.waypoints) == 5
    assert plan.rtl_after_last is True
    assert plan.waypoints[0].rel_alt_m == 40.0


def test_to_route_create_shape():
    body = to_route_create(INSPECT, "inspect-1")
    assert body["name"] == "inspect-1"
    assert body["rtl_after_last"] is True
    assert {"lat_deg", "lon_deg", "rel_alt_m", "hold_s", "speed_ms"} <= set(
        body["waypoints"][0]
    )


def _write_plan(tmp_path: Path, items: list[dict]) -> Path:
    p = tmp_path / "t.plan"
    p.write_text(
        json.dumps(
            {
                "fileType": "Plan",
                "mission": {
                    "firmwareType": 12,
                    "vehicleType": 2,
                    "items": items,
                    "plannedHomePosition": [25.0, 121.5, 10],
                    "version": 2,
                },
                "version": 1,
            }
        ),
        encoding="utf-8",
    )
    return p


def _wp(cmd: int, do_jump: int, params: list) -> dict:
    return {
        "type": "SimpleItem",
        "command": cmd,
        "doJumpId": do_jump,
        "frame": 3,
        "params": params,
    }


def test_rtl_not_last_rejected(tmp_path):
    p = _write_plan(
        tmp_path,
        [
            _wp(22, 1, [15, 0, 0, None, 25.0, 121.5, 30]),
            _wp(20, 2, [0, 0, 0, 0, 0, 0, 0]),
            _wp(16, 3, [0, 0, 0, None, 25.0, 121.5, 30]),
        ],
    )
    with pytest.raises(ValueError, match="RTL 僅允許為末項"):
        parse_plan(p)


def test_complex_item_rejected(tmp_path):
    p = _write_plan(tmp_path, [{"type": "ComplexItem", "complexItemType": "survey"}])
    with pytest.raises(ValueError, match="ComplexItem"):
        parse_plan(p)


def test_unsupported_command_rejected(tmp_path):
    p = _write_plan(tmp_path, [_wp(178, 1, [0, 5, -1, 0, 0, 0, 0])])  # DO_CHANGE_SPEED
    with pytest.raises(ValueError, match="不支援 MAV_CMD 178"):
        parse_plan(p)


def test_missing_mission_id_rejected():
    with pytest.raises(ValueError, match="mission_id"):
        to_mission_plan(SURVEY, "")

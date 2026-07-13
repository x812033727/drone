"""派遣核心純函式測試(proto JSON 組裝、進度映射)。需 drone-proto(CI 已裝)。"""

import pytest
from drone.v1 import mission_pb2
from google.protobuf import json_format
from mission_svc.dispatch import (
    PROGRESS_TO_STATUS,
    TERMINAL_STATUSES,
    build_mission_command_json,
    build_mission_plan_json,
    progress_state_name,
)


def test_build_mission_plan_json_roundtrip():
    wps = [
        {"lat_deg": 25.0, "lon_deg": 121.5, "rel_alt_m": 30.0},
        {"lat_deg": 25.01, "lon_deg": 121.51, "hold_s": 2.0},
    ]
    js = build_mission_plan_json("m-abc", wps, rtl_after_last=True)
    plan = json_format.Parse(js, mission_pb2.MissionPlan())
    assert plan.mission_id == "m-abc"
    assert plan.rtl_after_last is True
    assert len(plan.waypoints) == 2
    assert plan.waypoints[0].lat_deg == 25.0
    assert plan.waypoints[1].hold_s == 2.0


def test_build_mission_command_json():
    js = build_mission_command_json("m-abc", "pause")
    cmd = json_format.Parse(js, mission_pb2.MissionCommand())
    assert cmd.mission_id == "m-abc"
    assert cmd.command == mission_pb2.MissionCommand.COMMAND_PAUSE


def test_build_mission_command_unknown():
    with pytest.raises(ValueError):
        build_mission_command_json("m-abc", "bogus")


def test_progress_state_name_and_mapping():
    name = progress_state_name(mission_pb2.MissionProgress.STATE_COMPLETED)
    assert name == "STATE_COMPLETED"
    assert PROGRESS_TO_STATUS[name] == "completed"
    assert "completed" in TERMINAL_STATUSES
    assert "failed" in TERMINAL_STATUSES
    assert "in_progress" not in TERMINAL_STATUSES


def test_progress_unspecified_not_mapped():
    name = progress_state_name(mission_pb2.MissionProgress.STATE_UNSPECIFIED)
    assert name not in PROGRESS_TO_STATUS

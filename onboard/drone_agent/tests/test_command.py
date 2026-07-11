"""command.py 純函式單元測試:互斥判定、payload 把關、指令組裝、FAILED 事件組包。

不需 SITL,也不需 MQTT broker。
"""

import sys

import pytest
from drone.v1 import mission_pb2
from drone_agent.command import (
    MISSION_EXEC_DIR,
    build_cmd,
    failed_progress_json,
    parse_plan,
    should_accept,
)
from google.protobuf import json_format

VALID_PLAN = """{
  "missionId": "m-1",
  "waypoints": [{"latDeg": 47.39, "lonDeg": 8.54, "relAltM": 20.0}],
  "rtlAfterLast": true
}"""


# ---- should_accept:單一任務互斥 ----


def test_should_accept_when_idle() -> None:
    assert should_accept(running=False) is True


def test_should_reject_when_mission_running() -> None:
    """任務子程序存活時拒絕新任務(Phase 0 不做佇列)。"""
    assert should_accept(running=True) is False


# ---- parse_plan:Parse 級把關 ----


def test_parse_plan_valid_bytes() -> None:
    plan = parse_plan(VALID_PLAN.encode("utf-8"))
    assert plan.mission_id == "m-1"
    assert len(plan.waypoints) == 1
    assert plan.rtl_after_last is True


def test_parse_plan_rejects_invalid_json() -> None:
    with pytest.raises(ValueError, match="MissionPlan JSON"):
        parse_plan(b"not json at all")


def test_parse_plan_rejects_unknown_fields() -> None:
    """proto3 JSON mapping 未知欄位拒收(契約把關)。"""
    with pytest.raises(ValueError, match="MissionPlan JSON"):
        parse_plan(b'{"missionId": "m-1", "hack": 1}')


def test_parse_plan_rejects_empty_mission_id() -> None:
    with pytest.raises(ValueError, match="mission_id"):
        parse_plan(b'{"waypoints": [{"latDeg": 1.0, "lonDeg": 2.0}]}')


def test_parse_plan_rejects_non_utf8() -> None:
    with pytest.raises(ValueError, match="UTF-8"):
        parse_plan(b"\xff\xfe\x00")


# ---- build_cmd:mission_exec 子程序指令組裝 ----


def test_build_cmd_shares_agent_mavsdk_server() -> None:
    """必以 --mavsdk-address 顯式共用 agent 的 mavsdk_server,不得自行 spawn。"""
    cmd = build_cmd("/tmp/m.json", ("localhost", 50051), "broker", 62883, "dev-1")

    assert cmd[0] == sys.executable
    assert cmd[1:3] == ["-m", "mission_exec.main"]
    pairs = dict(zip(cmd[3::2], cmd[4::2]))
    assert pairs["--mission"] == "/tmp/m.json"
    assert pairs["--mavsdk-address"] == "localhost:50051"
    assert pairs["--mqtt-host"] == "broker"
    assert pairs["--mqtt-port"] == "62883"
    assert pairs["--drone-id"] == "dev-1"


def test_mission_exec_dir_points_into_monorepo() -> None:
    """cwd 指向 monorepo 的 onboard/mission_exec(讓 -m mission_exec.main 可解析)。"""
    assert MISSION_EXEC_DIR.name == "mission_exec"
    assert (MISSION_EXEC_DIR / "mission_exec" / "main.py").is_file()


# ---- failed_progress_json:agent 端 FAILED 事件組包 ----


def test_failed_progress_json_round_trips() -> None:
    payload = failed_progress_json("m-1", "dev-1", 1_752_000_000_000)

    msg = mission_pb2.MissionProgress()
    json_format.Parse(payload, msg)
    assert msg.mission_id == "m-1"
    assert msg.drone_id == "dev-1"
    assert msg.state == mission_pb2.MissionProgress.STATE_FAILED
    assert msg.unix_time_ms == 1_752_000_000_000
    assert msg.current_item == 0
    assert msg.total_items == 0

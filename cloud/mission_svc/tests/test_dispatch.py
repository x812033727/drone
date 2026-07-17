"""派遣核心純函式測試(proto JSON 組裝、進度映射)。需 drone-proto(CI 已裝)。"""

import asyncio
from unittest.mock import patch

import pytest
from drone.v1 import mission_pb2
from google.protobuf import json_format
from mission_svc import dispatch as dispatch_mod
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


class _FakeClient:
    """記錄構造用的 identifier 與 publish 參數的假 aiomqtt.Client。"""

    seen_identifiers: list[str] = []
    published: list[tuple[str, str, int]] = []

    def __init__(self, host, port, identifier=None, tls_params=None):
        self._identifier = identifier

    async def __aenter__(self):
        type(self).seen_identifiers.append(self._identifier)
        return self

    async def __aexit__(self, *exc):
        return False

    async def publish(self, topic, payload, qos=0):
        type(self).published.append((topic, payload, qos))


def test_publish_uses_unique_identifier_per_call():
    """迴歸:並發派遣不得共用固定 client-id(同 id 在 broker 會互踢 → QoS1 逾時 500)。
    多次呼叫需取得相異但同前綴的 identifier;topic/qos 正確。"""
    _FakeClient.seen_identifiers = []
    _FakeClient.published = []
    with patch.object(dispatch_mod.aiomqtt, "Client", _FakeClient):

        async def _run():
            await asyncio.gather(
                *(
                    dispatch_mod.publish_mission_plan("h", 1883, f"d{i}", "{}")
                    for i in range(20)
                )
            )

        asyncio.run(_run())

    ids = _FakeClient.seen_identifiers
    assert len(ids) == 20
    assert len(set(ids)) == 20, "client-id 必須每次連線唯一(否則並發互踢)"
    assert all(i.startswith("mission-svc-pub-") for i in ids)
    for n, (topic, _, qos) in enumerate(_FakeClient.published):
        assert topic == f"fleet/d{n}/cmd/mission"
        assert qos == 1


def test_command_publish_unique_identifier_prefix():
    """任務命令派遣同樣需唯一 client-id、正確 topic/qos。"""
    _FakeClient.seen_identifiers = []
    _FakeClient.published = []
    with patch.object(dispatch_mod.aiomqtt, "Client", _FakeClient):
        asyncio.run(dispatch_mod.publish_mission_command("h", 1883, "dz", "{}"))
    assert len(_FakeClient.seen_identifiers) == 1
    assert _FakeClient.seen_identifiers[0].startswith("mission-svc-ctrl-")
    assert _FakeClient.published == [("fleet/dz/cmd/mission_ctrl", "{}", 1)]

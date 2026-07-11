"""main CLI 的 S23 測試:--resume 參數傳遞、mission_ctrl 監聽解析(不需 SITL/MQTT)。"""

import asyncio

import pytest
from drone.v1 import mission_pb2
from google.protobuf import json_format

import mission_exec.main as main_mod

C = mission_pb2.MissionCommand


def test_main_resume_arg_passthrough(monkeypatch):
    """--resume 經 argparse 進 args.resume,由 _run 透傳 executor(見 _execute)。"""
    captured = {}

    async def fake_run(args):
        captured["resume"] = args.resume

    monkeypatch.setattr(main_mod, "_run", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        ["mission_exec", "--mission", "m.json", "--drone-id", "d1", "--resume", "2"],
    )
    main_mod.main()
    assert captured["resume"] == 2


def test_main_resume_negative_rejected(monkeypatch):
    """--resume 負值在 argparse 層拒絕(SystemExit 2),不進執行流程。"""
    monkeypatch.setattr(
        "sys.argv",
        ["mission_exec", "--mission", "m.json", "--drone-id", "d1", "--resume", "-1"],
    )
    with pytest.raises(SystemExit):
        main_mod.main()


def test_ctrl_listener_parses_filters_and_skips_bad_payload():
    """mission_ctrl 監聽:壞 payload 略過、主題不符略過、合法 MissionCommand 入佇列。"""

    class _Topic:
        def __init__(self, value: str):
            self.value = value

        def matches(self, pattern: str) -> bool:
            return self.value == pattern

    class _Msg:
        def __init__(self, topic: str, payload: bytes):
            self.topic = _Topic(topic)
            self.payload = payload

    good = json_format.MessageToJson(
        C(mission_id="m1", command=C.COMMAND_PAUSE, unix_time_ms=1), indent=None
    ).encode()

    class _Client:
        @property
        def messages(self):
            async def gen():
                yield _Msg("fleet/d1/cmd/mission_ctrl", b"not-json")
                yield _Msg("fleet/d1/telemetry", good)  # 主題不符,不收
                yield _Msg("fleet/d1/cmd/mission_ctrl", good)

            return gen()

    queue: asyncio.Queue = asyncio.Queue()
    listen = main_mod._make_ctrl_listener(_Client(), "fleet/d1/cmd/mission_ctrl", queue)
    asyncio.run(listen())
    assert queue.qsize() == 1
    cmd = queue.get_nowait()
    assert cmd.mission_id == "m1"
    assert cmd.command == C.COMMAND_PAUSE

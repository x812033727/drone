"""command.py 單元測試:互斥/去重判定、payload 把關、指令組裝、FAILED 事件組包,
以及 MissionRunner / handle_command 行為測試(fake 子程序用 `sys.executable -c`)。

不需 SITL,也不需 MQTT broker。
"""

import asyncio
import sys
import tempfile

import pytest
from drone.v1 import mission_pb2
from drone_agent import command as command_mod
from drone_agent.command import (
    MISSION_EXEC_DIR,
    MissionRunner,
    build_cmd,
    classify_command,
    failed_progress_json,
    handle_command,
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


# ---- classify_command:去重 + 互斥分支判定 ----


def test_classify_dup_running() -> None:
    """與執行中任務同 id → 忽略(QoS 1 dup,不發 FAILED)。"""
    assert classify_command("m-1", True, "m-1", None) == "dup-running"


def test_classify_dup_running_during_reap() -> None:
    """子程序剛結束、回收未完(running=False 但 current 仍在)→ 仍視為 dup。"""
    assert classify_command("m-1", False, "m-1", None) == "dup-running"


def test_classify_dup_terminal() -> None:
    """與最近已終結任務同 id 的遲到 dup → 忽略,防已完成後重飛。"""
    assert classify_command("m-1", False, None, "m-1") == "dup-terminal"


def test_classify_reject_busy() -> None:
    """新 mission_id 且已有任務執行中 → 拒絕(發 FAILED,帶新 id)。"""
    assert classify_command("m-2", True, "m-1", None) == "reject-busy"


def test_classify_accept_when_idle() -> None:
    assert classify_command("m-2", False, None, "m-1") == "accept"


# ---- MissionRunner:子程序生命週期(fake 子程序,不需 SITL/MQTT)----


def _make_failed_recorder():
    """回傳 (calls, async 回呼):記錄補發 STATE_FAILED 的 mission_id。"""
    calls: list[str] = []

    async def cb(mission_id: str) -> None:
        calls.append(mission_id)

    return calls, cb


def test_runner_exit_1_publishes_failed(tmp_path) -> None:
    """F1:exit 1 不可信(未處理例外也 exit 1 且 FAILED 從未發出)→ 非零一律補發。"""
    calls, cb = _make_failed_recorder()

    async def scenario() -> None:
        runner = MissionRunner(timeout_s=10.0, on_failed=cb)
        mission_file = tmp_path / "m.json"
        mission_file.write_text("{}")
        await runner.start(
            [sys.executable, "-c", "import sys; sys.exit(1)"], "m-crash", mission_file
        )
        await runner._reaper
        assert calls == ["m-crash"]
        assert not mission_file.exists()
        assert runner.running is False
        assert runner.current_mission_id is None
        assert runner.last_terminal == "m-crash"

    asyncio.run(scenario())


def test_runner_exit_0_no_failed(tmp_path) -> None:
    """rc=0 正常完成 → 不補發;去重狀態仍收斂(last_terminal 記錄)。"""
    calls, cb = _make_failed_recorder()

    async def scenario() -> None:
        runner = MissionRunner(timeout_s=10.0, on_failed=cb)
        mission_file = tmp_path / "m.json"
        mission_file.write_text("{}")
        await runner.start([sys.executable, "-c", "pass"], "m-ok", mission_file)
        await runner._reaper
        assert calls == []
        assert not mission_file.exists()
        assert runner.running is False
        assert runner.current_mission_id is None
        assert runner.last_terminal == "m-ok"

    asyncio.run(scenario())


def test_runner_timeout_kills_and_publishes_failed(tmp_path) -> None:
    """逾時(0.2 秒 vs 子程序 sleep 5)→ kill + 補發 FAILED + 暫存檔清掉。"""
    calls, cb = _make_failed_recorder()

    async def scenario() -> None:
        runner = MissionRunner(timeout_s=0.2, on_failed=cb)
        mission_file = tmp_path / "m.json"
        mission_file.write_text("{}")
        await runner.start(
            [sys.executable, "-c", "import time; time.sleep(5)"], "m-slow", mission_file
        )
        await runner._reaper
        assert calls == ["m-slow"]
        assert not mission_file.exists()
        assert runner.running is False
        assert runner._proc.returncode not in (0, None)  # 被 kill,非正常結束
        assert runner.last_terminal == "m-slow"

    asyncio.run(scenario())


# ---- handle_command:去重三分支 + spawn 失敗防護(F2/F5)----

#: 長跑 fake 子程序(由測試自行 kill),模擬任務執行中
_SLEEP_CMD = [sys.executable, "-c", "import time; time.sleep(30)"]


def test_handle_command_dedup_branches(monkeypatch, tmp_path) -> None:
    """F2 三分支:執行中 dup 忽略、已終結 dup 忽略(皆不發 FAILED);新 id 在 running 拒絕。"""
    rejects, reject_cb = _make_failed_recorder()
    fails, failed_cb = _make_failed_recorder()

    async def scenario() -> None:
        monkeypatch.setattr(command_mod, "build_cmd", lambda *a, **k: _SLEEP_CMD)
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
        runner = MissionRunner(timeout_s=30.0, on_failed=failed_cb)
        args = (runner, "dev-1", ("localhost", 50051), "broker", 1883, reject_cb, failed_cb)

        # idle → 執行
        await handle_command(VALID_PLAN.encode(), *args)
        assert runner.running is True
        pid = runner._proc.pid

        # (a) 執行中 dup(同 id)→ 忽略:不發 FAILED、不動子程序
        await handle_command(VALID_PLAN.encode(), *args)
        assert rejects == [] and fails == []
        assert runner._proc.pid == pid

        # (c) 新 id 且 running → 拒絕 + FAILED(帶新 id),原任務不受影響
        await handle_command(VALID_PLAN.replace("m-1", "m-2").encode(), *args)
        assert rejects == ["m-2"] and fails == []
        assert runner._proc.pid == pid and runner.running is True

        # 終結任務(kill → 非零 → F1 補發)
        runner._proc.kill()
        await runner._reaper
        assert fails == ["m-1"]
        assert runner.last_terminal == "m-1"

        # (b) 已終結後遲到 dup(同 id)→ 忽略,不重飛、不發 FAILED
        await handle_command(VALID_PLAN.encode(), *args)
        assert runner.running is False
        assert rejects == ["m-2"] and fails == ["m-1"]
        assert list(tmp_path.glob("mission_*")) == []  # 暫存檔全清

    asyncio.run(scenario())


def test_handle_command_spawn_failure_survives(monkeypatch, tmp_path) -> None:
    """F5:spawn 失敗不上拋(command_loop 不死),FAILED 盡力發出,暫存檔清掉。"""
    rejects, reject_cb = _make_failed_recorder()
    fails, failed_cb = _make_failed_recorder()

    async def scenario() -> None:
        monkeypatch.setattr(command_mod, "MISSION_EXEC_DIR", tmp_path / "no-such-dir")
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
        runner = MissionRunner(timeout_s=10.0, on_failed=failed_cb)

        await handle_command(
            VALID_PLAN.encode(),
            runner,
            "dev-1",
            ("localhost", 50051),
            "broker",
            1883,
            reject_cb,
            failed_cb,
        )  # 不應拋出

        assert fails == ["m-1"]  # FAILED 盡力發出(帶該 mission_id)
        assert rejects == []
        assert runner.running is False  # 狀態未污染,可續收下一筆
        assert runner.current_mission_id is None
        assert list(tmp_path.glob("mission_*")) == []  # spawn 失敗路徑也清暫存檔

    asyncio.run(scenario())

"""executor.run_mission 的呼叫順序/逾時/發布容錯測試(mock drone,不需 SITL)。"""

import asyncio

import aiomqtt
import pytest
from drone.v1 import mission_pb2

from mission_exec.executor import MissionExecError, run_mission
from mission_exec.main import _make_progress_cb

S = mission_pb2.MissionProgress


def _plan(n: int = 2, rtl: bool = True) -> mission_pb2.MissionPlan:
    return mission_pb2.MissionPlan(
        mission_id="t-exec",
        waypoints=[
            mission_pb2.Waypoint(lat_deg=1.0 + i, lon_deg=2.0 + i, rel_alt_m=10.0)
            for i in range(n)
        ],
        rtl_after_last=rtl,
    )


class _Health:
    def __init__(self, ok: bool):
        self.is_global_position_ok = ok
        self.is_home_position_ok = ok


class _Progress:
    def __init__(self, current: int, total: int):
        self.current = current
        self.total = total


async def _healthy_forever():
    while True:
        yield _Health(True)
        await asyncio.sleep(0)


async def _never_ready():
    while True:
        yield _Health(False)
        await asyncio.sleep(0.01)


def _complete_after(n_items: int):
    async def gen():
        for i in range(n_items):
            yield _Progress(i, n_items)
        yield _Progress(n_items, n_items)

    return gen


class _FakeMission:
    def __init__(self, drone):
        self._drone = drone

    async def set_return_to_launch_after_mission(self, enable):
        self._drone.calls.append(("set_rtl", enable))

    async def upload_mission(self, mav_plan):
        self._drone.calls.append(("upload", mav_plan))

    async def start_mission(self):
        self._drone.calls.append(("start", None))

    async def pause_mission(self):
        self._drone.calls.append(("pause", None))

    async def set_current_mission_item(self, index):
        self._drone.calls.append(("set_current", index))

    def mission_progress(self):
        return self._drone.progress_gen()


class _FakeTelemetry:
    def __init__(self, drone):
        self._drone = drone

    def health(self):
        return self._drone.health_gen()


class _FakeAction:
    def __init__(self, drone):
        self._drone = drone

    async def arm(self):
        self._drone.calls.append(("arm", None))

    async def return_to_launch(self):
        self._drone.calls.append(("rtl", None))


class FakeDrone:
    """長得像 mavsdk.System 的 mock:記錄呼叫序,串流由測試注入。"""

    def __init__(self, progress_gen, health_gen=_healthy_forever):
        self.calls: list[tuple] = []
        self.progress_gen = progress_gen
        self.health_gen = health_gen
        self.mission = _FakeMission(self)
        self.telemetry = _FakeTelemetry(self)
        self.action = _FakeAction(self)


def _collect_cb(states: list):
    async def cb(progress: mission_pb2.MissionProgress) -> None:
        states.append(progress.state)

    return cb


def test_rtl_set_before_upload():
    """Bug 1:RTL 設定僅對「下一次上傳」生效,必須在 upload_mission 之前呼叫。"""
    drone = FakeDrone(progress_gen=_complete_after(2))
    states: list = []
    asyncio.run(run_mission(drone, _plan(2, rtl=True), "d1", _collect_cb(states)))
    names = [name for name, _ in drone.calls]
    assert "set_rtl" in names and "upload" in names
    assert names.index("set_rtl") < names.index("upload"), "RTL 設定必須先於任務上傳"
    assert ("set_rtl", True) in drone.calls
    assert names == ["set_rtl", "upload", "arm", "start"]
    assert states[-1] == S.STATE_COMPLETED


def test_progress_stall_times_out():
    """Bug 2:進度串流靜默(斷線/失效保護)不得永久阻塞,停滯逾時 → FAILED。"""

    async def stall_gen():
        yield _Progress(0, 2)
        await asyncio.Event().wait()  # 第一筆後永久掛起
        yield _Progress(2, 2)  # pragma: no cover

    drone = FakeDrone(progress_gen=stall_gen)
    states: list = []
    with pytest.raises(MissionExecError, match="進度停滯逾時"):
        asyncio.run(
            run_mission(drone, _plan(2), "d1", _collect_cb(states), progress_stall_s=0.2)
        )
    assert states[-1] == S.STATE_FAILED
    assert S.STATE_IN_PROGRESS in states  # 第一筆事件有收到,逾時針對「之後無事件」


def test_health_never_ready_times_out():
    """Bug 3:GPS/home 遲遲未就緒不得永久阻塞,逾時 → FAILED。"""
    drone = FakeDrone(progress_gen=_complete_after(2), health_gen=_never_ready)
    states: list = []
    with pytest.raises(MissionExecError, match="定位未就緒"):
        asyncio.run(
            run_mission(drone, _plan(2), "d1", _collect_cb(states), health_timeout_s=0.2)
        )
    assert states[-1] == S.STATE_FAILED
    names = [name for name, _ in drone.calls]
    assert "arm" not in names  # 未就緒不可 arm


def test_progress_cb_errors_do_not_abort_mission():
    """Bug 4:progress_cb 拋例外(如 MQTT broker 斷線)不得中斷任務流程。"""
    drone = FakeDrone(progress_gen=_complete_after(2))
    seen: list = []

    async def flaky_cb(progress: mission_pb2.MissionProgress) -> None:
        seen.append(progress.state)
        raise aiomqtt.MqttError("broker 斷線")

    asyncio.run(run_mission(drone, _plan(2), "d1", flaky_cb))  # 不應拋出
    assert seen[-1] == S.STATE_COMPLETED
    names = [name for name, _ in drone.calls]
    assert names == ["set_rtl", "upload", "arm", "start"]


def test_mqtt_progress_cb_swallows_publish_errors(capsys):
    """Bug 4(main 側):MQTT publish 失敗只記 WARNING,stdout 仍必印,不往外拋。"""

    class BadClient:
        async def publish(self, *args, **kwargs):
            raise aiomqtt.MqttError("broker gone")

    cb = _make_progress_cb(BadClient(), "d1")
    progress = mission_pb2.MissionProgress(
        mission_id="m-1", drone_id="d1", current_item=0, total_items=2, state=S.STATE_FAILED
    )
    asyncio.run(cb(progress))  # 不應拋出
    assert "[進度]" in capsys.readouterr().out


def test_arm_with_retry_succeeds_after_denials():
    import types

    from mavsdk.action import ActionError

    from mission_exec import executor

    calls = {"n": 0}

    class FakeAction:
        async def arm(self):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise ActionError(
                    types.SimpleNamespace(result=None, result_str="COMMAND_DENIED"), "arm()"
                )

    drone = types.SimpleNamespace(action=FakeAction())
    executor.ARM_RETRY_DELAY_S = 0.01
    asyncio.run(executor._arm_with_retry(drone))
    assert calls["n"] == 3


def test_arm_with_retry_exhausted_reraises_action_error():
    import types

    import pytest
    from mavsdk.action import ActionError

    from mission_exec import executor

    class FakeAction:
        async def arm(self):
            raise ActionError(
                types.SimpleNamespace(result=None, result_str="COMMAND_DENIED"), "arm()"
            )

    executor.ARM_RETRY_DELAY_S = 0.01
    with pytest.raises(ActionError):
        asyncio.run(executor._arm_with_retry(types.SimpleNamespace(action=FakeAction())))


# ---------------------------------------------------------------------------
# S23:MissionCommand PAUSE/RESUME/ABORT 機上執行
# ---------------------------------------------------------------------------

C = mission_pb2.MissionCommand


def _cmd(command, mission_id: str = "t-exec") -> mission_pb2.MissionCommand:
    return C(mission_id=mission_id, command=command, unix_time_ms=1)


def test_pause_resume_cycle():
    """S23:PAUSE → pause_mission + STATE_PAUSED;RESUME → start_mission 續飛;
    暫停中重複 PAUSE 忽略(QoS 1 dup)。"""

    async def scenario():
        resumed = asyncio.Event()

        async def gen():
            yield _Progress(0, 2)
            await resumed.wait()
            yield _Progress(1, 2)
            yield _Progress(2, 2)

        drone = FakeDrone(progress_gen=gen)
        orig_start = drone.mission.start_mission

        async def start_mission():
            await orig_start()
            if drone.calls.count(("start", None)) >= 2:  # 第 2 次 start = RESUME
                resumed.set()

        drone.mission.start_mission = start_mission
        queue: asyncio.Queue = asyncio.Queue()
        states: list = []

        async def cb(progress: mission_pb2.MissionProgress) -> None:
            states.append(progress.state)
            if progress.state == S.STATE_PAUSED:
                await queue.put(_cmd(C.COMMAND_RESUME))

        await queue.put(_cmd(C.COMMAND_PAUSE))
        await queue.put(_cmd(C.COMMAND_PAUSE))  # dup:暫停中第二個 PAUSE 應忽略
        await run_mission(drone, _plan(2), "d1", cb, ctrl_queue=queue)
        return drone, states

    drone, states = asyncio.run(scenario())
    assert drone.calls.count(("pause", None)) == 1  # dup PAUSE 被忽略
    assert drone.calls.count(("start", None)) == 2  # 首次 start + RESUME
    assert S.STATE_PAUSED in states
    idx = states.index(S.STATE_PAUSED)
    assert S.STATE_IN_PROGRESS in states[idx:]  # RESUME 後回 IN_PROGRESS
    assert states[-1] == S.STATE_COMPLETED


def test_abort_sends_rtl_then_failed():
    """S23:ABORT → action.return_to_launch() → STATE_FAILED(契約無 ABORTED,
    以 FAILED 承載,訊息註明 abort)→ MissionExecError。"""

    async def gen():
        yield _Progress(0, 2)
        await asyncio.Event().wait()  # 永不推進,等 ABORT
        yield _Progress(2, 2)  # pragma: no cover

    drone = FakeDrone(progress_gen=gen)
    queue: asyncio.Queue = asyncio.Queue()
    states: list = []

    async def scenario():
        await queue.put(_cmd(C.COMMAND_ABORT))
        await run_mission(drone, _plan(2), "d1", _collect_cb(states), ctrl_queue=queue)

    with pytest.raises(MissionExecError, match="ABORT"):
        asyncio.run(scenario())
    assert ("rtl", None) in drone.calls
    assert states[-1] == S.STATE_FAILED


def test_stall_timeout_suspended_while_paused():
    """S23 重點:PAUSED 期間停滯逾時暫停計時(暫停是合法靜止,不可被當停滯誤殺);
    RESUME 後計時重新起算、任務照常完成。"""

    async def scenario():
        resumed = asyncio.Event()

        async def gen():
            yield _Progress(0, 2)
            await resumed.wait()
            yield _Progress(2, 2)

        drone = FakeDrone(progress_gen=gen)
        orig_start = drone.mission.start_mission

        async def start_mission():
            await orig_start()
            if drone.calls.count(("start", None)) >= 2:
                resumed.set()

        drone.mission.start_mission = start_mission
        queue: asyncio.Queue = asyncio.Queue()
        states: list = []
        task = asyncio.create_task(
            run_mission(
                drone,
                _plan(2),
                "d1",
                _collect_cb(states),
                ctrl_queue=queue,
                progress_stall_s=0.2,
            )
        )
        await queue.put(_cmd(C.COMMAND_PAUSE))
        while S.STATE_PAUSED not in states:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.6)  # 遠超 stall 0.2:暫停中不可觸發停滯逾時
        await queue.put(_cmd(C.COMMAND_RESUME))
        await task
        return states

    states = asyncio.run(scenario())
    assert S.STATE_FAILED not in states
    assert states[-1] == S.STATE_COMPLETED


def test_ctrl_mismatched_mission_id_ignored():
    """S23:mission_id 不符當前任務的控制命令 log 後忽略,任務照常完成。"""

    queue: asyncio.Queue = asyncio.Queue()

    async def gen():
        yield _Progress(0, 2)
        while not queue.empty():  # 等 ctrl 命令被消化,確保走到忽略分支
            await asyncio.sleep(0)
        await asyncio.sleep(0.05)
        yield _Progress(2, 2)

    drone = FakeDrone(progress_gen=gen)
    states: list = []

    async def scenario():
        await queue.put(_cmd(C.COMMAND_PAUSE, mission_id="other-mission"))
        await run_mission(drone, _plan(2), "d1", _collect_cb(states), ctrl_queue=queue)

    asyncio.run(scenario())
    assert ("pause", None) not in drone.calls
    assert S.STATE_PAUSED not in states
    assert states[-1] == S.STATE_COMPLETED


def test_ctrl_unknown_command_ignored():
    """S23:未知/未指定命令 log 後忽略(不 pause、不 RTL),任務照常完成。"""

    queue: asyncio.Queue = asyncio.Queue()

    async def gen():
        yield _Progress(0, 2)
        while not queue.empty():
            await asyncio.sleep(0)
        await asyncio.sleep(0.05)
        yield _Progress(2, 2)

    drone = FakeDrone(progress_gen=gen)
    states: list = []

    async def scenario():
        await queue.put(_cmd(C.COMMAND_UNSPECIFIED))
        # proto3 開放 enum:未知數字 99 能通過 json_format.Parse,
        # Command.Name(99) 會炸 ValueError——不可讓它炸掉任務
        unknown = _cmd(C.COMMAND_PAUSE)
        unknown.command = 99
        await queue.put(unknown)
        await run_mission(drone, _plan(2), "d1", _collect_cb(states), ctrl_queue=queue)

    asyncio.run(scenario())
    assert ("pause", None) not in drone.calls
    assert ("rtl", None) not in drone.calls
    assert S.STATE_FAILED not in states
    assert states[-1] == S.STATE_COMPLETED


def test_resume_from_sets_current_item_before_start():
    """S23:--resume N 斷點續飛——上傳後、start 前 set_current_mission_item(N)。"""
    drone = FakeDrone(progress_gen=_complete_after(3))
    states: list = []
    asyncio.run(run_mission(drone, _plan(3), "d1", _collect_cb(states), resume_from=1))
    assert ("set_current", 1) in drone.calls
    names = [name for name, _ in drone.calls]
    assert names.index("upload") < names.index("set_current") < names.index("start")
    assert states[-1] == S.STATE_COMPLETED


def test_resume_from_out_of_range_fails():
    """S23:resume_from 超出航點範圍 → FAILED(不 set、不 arm)。"""
    drone = FakeDrone(progress_gen=_complete_after(2))
    states: list = []
    with pytest.raises(MissionExecError, match="resume_from"):
        asyncio.run(run_mission(drone, _plan(2), "d1", _collect_cb(states), resume_from=5))
    assert states[-1] == S.STATE_FAILED
    names = [name for name, _ in drone.calls]
    assert "set_current" not in names
    assert "arm" not in names

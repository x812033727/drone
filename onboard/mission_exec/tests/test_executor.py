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

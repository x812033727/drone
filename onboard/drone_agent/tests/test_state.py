"""watch_* 訂閱協程單元測試(以假 telemetry 流驅動):不需 SITL,也不需 MQTT。

重點是 armed 邊緣偵測(FlightEvent 的觸發來源):
- 啟動後第一筆 armed 值只是初始狀態,不算邊緣、不產生事件;
- True→False / False→True 邊緣各產生一筆 pending_events;
- 值未變化(dup)不產生事件。
"""

import asyncio
from types import SimpleNamespace

import pytest
from drone_agent.state import (
    TelemetryState,
    watch_armed,
    watch_gps_info,
    watch_raw_gps,
    watch_velocity,
)


class _FakeDrone:
    """最小 System 替身:watch_* 只用 drone.telemetry.<stream>() async 迭代器。"""

    def __init__(self, stream_name: str, values: list) -> None:
        async def stream():
            for value in values:
                yield value

        self.telemetry = SimpleNamespace(**{stream_name: stream})


def _run(coro) -> None:
    asyncio.run(coro)


def test_watch_armed_first_value_is_not_an_edge() -> None:
    state = TelemetryState()
    _run(watch_armed(_FakeDrone("armed", [True]), state))

    assert state.armed is True
    assert len(state.pending_events) == 0


def test_watch_armed_edges_enqueue_events() -> None:
    state = TelemetryState()
    _run(watch_armed(_FakeDrone("armed", [False, True, False]), state))

    assert state.armed is False
    # False→True 與 True→False 各一筆(第一筆 False 不算邊緣)
    assert [armed for armed, _ in state.pending_events] == [True, False]
    for _, unix_time_ms in state.pending_events:
        assert unix_time_ms > 0


def test_watch_armed_duplicate_values_do_not_enqueue() -> None:
    state = TelemetryState()
    _run(watch_armed(_FakeDrone("armed", [True, True, True, False]), state))

    assert [armed for armed, _ in state.pending_events] == [False]


def test_watch_gps_info_maps_satellites_and_fix_type_name() -> None:
    state = TelemetryState()
    fix_type = SimpleNamespace(name="FIX_3D")  # MAVSDK FixType enum 替身
    gps = SimpleNamespace(num_satellites=14, fix_type=fix_type)
    _run(watch_gps_info(_FakeDrone("gps_info", [gps]), state))

    assert state.satellites == 14
    assert state.gps_fix_type == "FIX_3D"
    assert state.last_update_monotonic is not None


def test_watch_raw_gps_maps_hdop() -> None:
    state = TelemetryState()
    _run(watch_raw_gps(_FakeDrone("raw_gps", [SimpleNamespace(hdop=0.8)]), state))

    assert state.hdop == pytest.approx(0.8)


def test_watch_velocity_vertical_speed_is_negated_down() -> None:
    state = TelemetryState()
    vel = SimpleNamespace(north_m_s=3.0, east_m_s=4.0, down_m_s=-1.5)  # 上升 1.5 m/s
    _run(watch_velocity(_FakeDrone("velocity_ned", [vel]), state))

    assert state.ground_speed_ms == pytest.approx(5.0)
    assert state.vertical_speed_ms == pytest.approx(1.5)  # 向上為正

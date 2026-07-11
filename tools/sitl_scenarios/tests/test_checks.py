"""checks.py 純函式單元測試:模式序列判定、延遲、圍欄門檻、低電量三級序列。"""

from sitl_scenarios.checks import (
    crossed_boundary,
    evaluate_battery_ladder,
    first_mode_time,
    latency_to_mode,
    mode_at,
    modes_in_order,
    reached_within,
)

# ---- modes_in_order ----------------------------------------------------------


def test_modes_in_order_subsequence():
    observed = ["AUTO_TAKEOFF", "AUTO_MISSION", "AUTO_LOITER", "AUTO_RTL"]
    assert modes_in_order(observed, ["AUTO_MISSION", "AUTO_RTL"])
    assert modes_in_order(observed, ["AUTO_MISSION", "AUTO_LOITER", "AUTO_RTL"])


def test_modes_in_order_wrong_order():
    observed = ["AUTO_MISSION", "AUTO_RTL", "AUTO_LOITER"]
    assert not modes_in_order(observed, ["AUTO_RTL", "AUTO_MISSION"])
    assert not modes_in_order(observed, ["AUTO_MISSION", "AUTO_LAND"])


def test_modes_in_order_empty_expected_is_true():
    assert modes_in_order(["A"], [])


def test_modes_in_order_repeated_target():
    # 相同模式重複出現時,需依序各自消耗一個
    assert modes_in_order(["A", "B", "A"], ["A", "A"])
    assert not modes_in_order(["A", "B"], ["A", "A"])


# ---- first_mode_time / latency / reached_within ------------------------------

_EVENTS = [(0.0, "AUTO_TAKEOFF"), (12.0, "AUTO_MISSION"), (45.3, "AUTO_LOITER"), (50.4, "AUTO_RTL")]


def test_first_mode_time_basic():
    assert first_mode_time(_EVENTS, "AUTO_MISSION") == 12.0
    assert first_mode_time(_EVENTS, "AUTO_LAND") is None


def test_first_mode_time_respects_t_min():
    events = [(1.0, "X"), (5.0, "X")]
    assert first_mode_time(events, "X", t_min=2.0) == 5.0
    assert first_mode_time(events, "X", t_min=5.0) == 5.0  # 含邊界


def test_latency_to_mode():
    # F09 run4 實測:注入 t=40.0 → +10.4s AUTO_RTL
    lat = latency_to_mode(_EVENTS, "AUTO_RTL", 40.0)
    assert lat is not None and abs(lat - 10.4) < 1e-9
    assert latency_to_mode(_EVENTS, "AUTO_LAND", 40.0) is None


def test_reached_within_boundary():
    assert reached_within(_EVENTS, "AUTO_RTL", 40.0, 30.0)
    assert reached_within(_EVENTS, "AUTO_RTL", 40.0, 10.4)  # 剛好等於逾時 → 通過
    assert not reached_within(_EVENTS, "AUTO_RTL", 40.0, 10.3)
    assert not reached_within(_EVENTS, "AUTO_LAND", 40.0, 999.0)


# ---- mode_at ------------------------------------------------------------------


def test_mode_at():
    assert mode_at(_EVENTS, 0.0) == "AUTO_TAKEOFF"
    assert mode_at(_EVENTS, 12.0) == "AUTO_MISSION"  # 轉換當下即生效
    assert mode_at(_EVENTS, 44.0) == "AUTO_MISSION"
    assert mode_at(_EVENTS, 100.0) == "AUTO_RTL"
    assert mode_at(_EVENTS, -1.0) is None


# ---- crossed_boundary(F11 不穿越 >10 m)-------------------------------------


def test_crossed_boundary_thresholds():
    assert not crossed_boundary(128.8, 150.0)  # run5 實測 max,遠在邊界內
    assert not crossed_boundary(160.0, 150.0)  # 剛好 +10 m → 未超過容許
    assert crossed_boundary(160.1, 150.0)
    assert not crossed_boundary(155.0, 150.0, margin_m=5.0)
    assert crossed_boundary(155.1, 150.0, margin_m=5.0)


# ---- evaluate_battery_ladder(F10)--------------------------------------------


def _flight_d_events():
    """實測 Flight D(act=3)節錄:LOW 警告留 MISSION → CRIT Hold→RTL → EMERG→LAND。"""
    warn = [(75.0, "LOW"), (213.5, "CRITICAL"), (223.4, "EMERGENCY")]
    nav = [
        (10.0, "AUTO_TAKEOFF"),
        (20.0, "AUTO_MISSION"),
        (213.6, "AUTO_LOITER"),  # COM_FAIL_ACT_T=5s Hold
        (218.5, "AUTO_RTL"),
        (223.5, "AUTO_LAND"),
    ]
    return warn, nav


def test_battery_ladder_flight_d_passes():
    warn, nav = _flight_d_events()
    checks = evaluate_battery_ladder(warn, nav)
    assert len(checks) == 4
    assert all(ok for _, ok, _ in checks), checks


def test_battery_ladder_rtl_swallowed_fails():
    # 實測 Flight B:Crit→Emerg 間隔 < 5s Hold,RTL 被吞,LOITER 直接 → LAND
    warn = [(75.0, "LOW"), (84.5, "CRITICAL"), (88.8, "EMERGENCY")]
    nav = [(20.0, "AUTO_MISSION"), (84.6, "AUTO_LOITER"), (89.5, "AUTO_LAND")]
    checks = dict((label, ok) for label, ok, _ in evaluate_battery_ladder(warn, nav))
    assert not checks["CRITICAL 後切 AUTO_RTL(允許 AUTO_LOITER 5s Hold 過渡)"]
    assert not checks["EMERGENCY 後 AUTO_LAND 且 RTL 在 LAND 之前"]


def test_battery_ladder_low_interrupts_mission_fails():
    # LOW 就切出 MISSION(違反「Low 僅警告」)
    warn, nav = _flight_d_events()
    nav = [(20.0, "AUTO_MISSION"), (80.0, "AUTO_LOITER"), (218.5, "AUTO_RTL"), (224.0, "AUTO_LAND")]
    checks = evaluate_battery_ladder(warn, nav)
    labels_ok = {label: ok for label, ok, _ in checks}
    assert not labels_ok["LOW 僅警告(在 AUTO_MISSION 且到 CRITICAL 前不離開)"]


def test_battery_ladder_missing_emergency_short_circuits():
    warn = [(75.0, "LOW"), (213.5, "CRITICAL")]
    _, nav = _flight_d_events()
    checks = evaluate_battery_ladder(warn, nav)
    assert len(checks) == 1  # 順序檢查失敗即短路
    assert not checks[0][1]


def test_battery_ladder_out_of_order_fails():
    warn = [(75.0, "CRITICAL"), (80.0, "LOW"), (90.0, "EMERGENCY")]
    _, nav = _flight_d_events()
    checks = evaluate_battery_ladder(warn, nav)
    assert not checks[0][1]


def test_battery_ladder_land_before_emergency_fails():
    # act=2(Land mode)行為:CRITICAL 即入 LAND、無 RTL → 兩項失敗
    warn = [(75.0, "LOW"), (84.5, "CRITICAL"), (95.0, "EMERGENCY")]
    nav = [(20.0, "AUTO_MISSION"), (84.6, "AUTO_LOITER"), (89.8, "AUTO_LAND")]
    checks = {label: ok for label, ok, _ in evaluate_battery_ladder(warn, nav)}
    assert not checks["CRITICAL 後切 AUTO_RTL(允許 AUTO_LOITER 5s Hold 過渡)"]
    assert not checks["EMERGENCY 後 AUTO_LAND 且 RTL 在 LAND 之前"]


# --- arm_with_retry(2026-07-11 nightly f10/f11 事故回歸)---


def test_arm_with_retry_succeeds_after_denials():
    import asyncio
    import types

    from mavsdk.action import ActionError
    from sitl_scenarios.runner import arm_with_retry

    def _err():
        return ActionError(
            types.SimpleNamespace(result=None, result_str="COMMAND_DENIED"), "arm()"
        )

    class FakeAction:
        def __init__(self, deny_times):
            self.deny_times = deny_times
            self.calls = 0

        async def arm(self):
            self.calls += 1
            if self.calls <= self.deny_times:
                raise _err()

    class FakeDrone:
        def __init__(self, deny_times):
            self.action = FakeAction(deny_times)

    drone = FakeDrone(deny_times=2)
    asyncio.run(arm_with_retry(drone, attempts=4, delay_s=0.01))
    assert drone.action.calls == 3


def test_arm_with_retry_exhausted_raises_scenario_error():
    import asyncio
    import types

    import pytest
    from mavsdk.action import ActionError
    from sitl_scenarios.runner import ScenarioError, arm_with_retry

    class FakeAction:
        async def arm(self):
            raise ActionError(
                types.SimpleNamespace(result=None, result_str="COMMAND_DENIED"), "arm()"
            )

    class FakeDrone:
        action = FakeAction()

    with pytest.raises(ScenarioError):
        asyncio.run(arm_with_retry(FakeDrone(), attempts=3, delay_s=0.01))

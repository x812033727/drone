"""precision_land 降落狀態機純邏輯測試(降落決策每 PR 回歸;零 ROS)。

覆蓋:狀態轉移全鏈(搜尋→鎖定→下降→著陸)、信號丟失重試、搜尋/丟失逾時 abort、
超容差 abort、遲滯退回、終止吸收態、置信度/NaN 邊界、對準速度夾制、參數驗證。
"""

import math

import pytest
from precision_land.state_machine import (
    LandCommand,
    LandParams,
    LandState,
    Observation,
    PrecisionLandStateMachine,
    alignment_velocity,
    horizontal_offset,
)

P = LandParams(
    acquire_offset_m=0.30,
    align_tolerance_m=0.60,
    abort_offset_m=3.0,
    descend_speed_ms=0.35,
    horizontal_gain=1.0,
    max_horizontal_speed_ms=1.0,
    min_confidence=0.5,
    landed_altitude_m=0.15,
    search_timeout_s=30.0,
    lost_timeout_s=3.0,
)


def obs(
    *, visible=True, x=0.0, y=0.0, alt=5.0, conf=0.9
) -> Observation:
    return Observation(
        target_visible=visible, offset_x=x, offset_y=y, altitude_m=alt, confidence=conf
    )


def sm() -> PrecisionLandStateMachine:
    return PrecisionLandStateMachine(P)


# ---- 初始 / SEARCH ----
def test_starts_in_search():
    assert sm().state is LandState.SEARCH


def test_search_holds_when_no_target():
    m = sm()
    cmd = m.update(obs(visible=False), now=0.0)
    assert cmd.state is LandState.SEARCH
    assert (cmd.vx, cmd.vy, cmd.descent_rate_ms) == (0.0, 0.0, 0.0)


def test_search_to_acquired_on_valid_target():
    m = sm()
    cmd = m.update(obs(x=1.0, y=0.0, conf=0.9), now=0.0)
    assert m.state is LandState.ACQUIRED
    assert cmd.state is LandState.ACQUIRED
    assert cmd.descent_rate_ms == 0.0  # 剛鎖定不下降


def test_search_timeout_aborts():
    m = sm()
    m.update(obs(visible=False), now=0.0)  # 進入計時
    cmd = m.update(obs(visible=False), now=30.01)
    assert m.state is LandState.ABORT
    assert cmd.abort is True
    assert cmd.descent_rate_ms == 0.0


def test_search_just_under_timeout_still_searching():
    m = sm()
    m.update(obs(visible=False), now=0.0)
    cmd = m.update(obs(visible=False), now=29.9)
    assert m.state is LandState.SEARCH
    assert cmd.abort is False


# ---- ACQUIRED ----
def _to_acquired(m: PrecisionLandStateMachine, t=0.0):
    # 用偏移超過 acquire 但在 abort 內,避免第一拍就直接續降轉態的混淆
    m.update(obs(x=0.5, y=0.0), now=t)
    assert m.state is LandState.ACQUIRED


def test_acquired_corrects_without_descending_when_not_aligned():
    m = sm()
    _to_acquired(m)
    cmd = m.update(obs(x=0.5, y=0.0), now=0.1)  # 0.5 > acquire 0.3
    assert m.state is LandState.ACQUIRED
    assert cmd.descent_rate_ms == 0.0
    assert cmd.vx > 0.0  # 朝標靶對準


def test_acquired_to_descend_when_aligned():
    m = sm()
    _to_acquired(m)
    cmd = m.update(obs(x=0.1, y=0.0), now=0.1)  # 0.1 <= acquire 0.3
    assert m.state is LandState.DESCEND
    assert cmd.descent_rate_ms == pytest.approx(0.35)


def test_acquired_to_reacquire_on_lost():
    m = sm()
    _to_acquired(m)
    cmd = m.update(obs(visible=False), now=0.1)
    assert m.state is LandState.REACQUIRE
    assert cmd.descent_rate_ms == 0.0


def test_acquired_to_reacquire_on_low_confidence():
    m = sm()
    _to_acquired(m)
    cmd = m.update(obs(x=0.1, conf=0.4), now=0.1)  # conf < min 0.5
    assert m.state is LandState.REACQUIRE
    assert cmd.descent_rate_ms == 0.0


def test_acquired_to_abort_on_gross_offset():
    m = sm()
    _to_acquired(m)
    cmd = m.update(obs(x=4.0, y=0.0), now=0.1)  # 4 > abort 3
    assert m.state is LandState.ABORT
    assert cmd.abort is True


# ---- DESCEND ----
def _to_descend(m: PrecisionLandStateMachine, t=0.0):
    m.update(obs(x=0.5), now=t)  # ACQUIRED
    m.update(obs(x=0.1), now=t + 0.1)  # DESCEND
    assert m.state is LandState.DESCEND


def test_descend_continues_within_tolerance():
    m = sm()
    _to_descend(m)
    cmd = m.update(obs(x=0.4, alt=3.0), now=0.3)  # 0.4 <= align_tol 0.6
    assert m.state is LandState.DESCEND
    assert cmd.descent_rate_ms == pytest.approx(0.35)


def test_descend_to_landed():
    m = sm()
    _to_descend(m)
    cmd = m.update(obs(x=0.05, alt=0.10), now=0.3)  # alt <= landed 0.15
    assert m.state is LandState.LANDED
    assert cmd.landed is True
    assert (cmd.vx, cmd.vy, cmd.descent_rate_ms) == (0.0, 0.0, 0.0)


def test_descend_to_acquired_when_drifts_past_tolerance():
    m = sm()
    _to_descend(m)
    cmd = m.update(obs(x=0.8, alt=3.0), now=0.3)  # 0.8 > align_tol 0.6, < abort 3
    assert m.state is LandState.ACQUIRED  # 停降重對準
    assert cmd.descent_rate_ms == 0.0


def test_descend_to_reacquire_on_lost():
    m = sm()
    _to_descend(m)
    cmd = m.update(obs(visible=False), now=0.3)
    assert m.state is LandState.REACQUIRE
    assert cmd.descent_rate_ms == 0.0


def test_descend_to_abort_on_gross_offset():
    m = sm()
    _to_descend(m)
    cmd = m.update(obs(x=5.0, alt=3.0), now=0.3)
    assert m.state is LandState.ABORT
    assert cmd.abort is True


def test_descend_landed_takes_priority_over_drift():
    # 低於著陸高度即使略漂,判著陸(高度優先於容差退回)
    m = sm()
    _to_descend(m)
    cmd = m.update(obs(x=0.5, alt=0.1), now=0.3)  # 0.5 within align_tol 0.6
    assert m.state is LandState.LANDED
    assert cmd.landed is True


# ---- REACQUIRE ----
def _to_reacquire(m: PrecisionLandStateMachine, t=0.0):
    m.update(obs(x=0.1), now=t)  # SEARCH→ACQUIRED
    m.update(obs(x=0.1), now=t + 0.1)  # ACQUIRED→DESCEND
    m.update(obs(visible=False), now=t + 0.2)  # DESCEND→REACQUIRE
    assert m.state is LandState.REACQUIRE


def test_reacquire_holds_within_timeout():
    m = sm()
    _to_reacquire(m, t=0.0)
    cmd = m.update(obs(visible=False), now=2.0)  # < lost_timeout 3
    assert m.state is LandState.REACQUIRE
    assert cmd.descent_rate_ms == 0.0


def test_reacquire_timeout_aborts():
    m = sm()
    _to_reacquire(m, t=0.0)  # 進入 REACQUIRE @ t=0.2
    cmd = m.update(obs(visible=False), now=0.2 + 3.01)
    assert m.state is LandState.ABORT
    assert cmd.abort is True


def test_reacquire_resumes_descend_when_aligned():
    m = sm()
    _to_reacquire(m, t=0.0)
    cmd = m.update(obs(x=0.1, alt=3.0), now=1.0)  # 復得且對準
    assert m.state is LandState.DESCEND
    assert cmd.descent_rate_ms == pytest.approx(0.35)


def test_reacquire_resumes_acquired_when_not_aligned():
    m = sm()
    _to_reacquire(m, t=0.0)
    cmd = m.update(obs(x=0.5, alt=3.0), now=1.0)  # 復得但未對準
    assert m.state is LandState.ACQUIRED
    assert cmd.descent_rate_ms == 0.0


# ---- 終止吸收態 ----
def test_landed_is_absorbing():
    m = sm()
    _to_descend(m)
    m.update(obs(x=0.05, alt=0.10), now=0.3)
    assert m.state is LandState.LANDED
    # 即使之後標靶又出現、飛高,仍維持 LANDED
    cmd = m.update(obs(x=0.05, alt=5.0), now=0.4)
    assert m.state is LandState.LANDED
    assert cmd.landed is True


def test_abort_is_absorbing():
    m = sm()
    _to_acquired(m)
    m.update(obs(x=4.0), now=0.1)  # ABORT
    assert m.state is LandState.ABORT
    cmd = m.update(obs(x=0.0, alt=5.0), now=0.2)  # 完美標靶也不復飛
    assert m.state is LandState.ABORT
    assert cmd.abort is True


def test_reset_restarts_search():
    m = sm()
    _to_acquired(m)
    m.update(obs(x=4.0), now=0.1)  # ABORT
    m.reset()
    assert m.state is LandState.SEARCH
    cmd = m.update(obs(visible=False), now=1.0)
    assert cmd.state is LandState.SEARCH


# ---- 完整快樂路徑整合 ----
def test_full_happy_path():
    m = sm()
    seq = [
        (obs(visible=False), 0.0, LandState.SEARCH),
        (obs(x=1.0, y=0.5, alt=8.0), 1.0, LandState.ACQUIRED),
        (obs(x=0.2, y=0.1, alt=8.0), 1.1, LandState.DESCEND),
        (obs(x=0.1, y=0.05, alt=4.0), 1.2, LandState.DESCEND),
        (obs(x=0.05, y=0.0, alt=0.1), 1.3, LandState.LANDED),
    ]
    for o, t, expected in seq:
        m.update(o, now=t)
        assert m.state is expected


# ---- NaN / 非法輸入(保守:不下降) ----
def test_nan_offset_treated_as_invalid_in_acquired():
    m = sm()
    _to_acquired(m)
    cmd = m.update(obs(x=float("nan"), y=0.0), now=0.1)
    assert m.state is LandState.REACQUIRE
    assert cmd.descent_rate_ms == 0.0


def test_nan_confidence_invalid():
    m = sm()
    _to_acquired(m)
    m.update(obs(x=0.1, conf=float("nan")), now=0.1)
    assert m.state is LandState.REACQUIRE


# ---- 純幾何 helper ----
def test_horizontal_offset():
    assert horizontal_offset(obs(x=3.0, y=4.0)) == pytest.approx(5.0)


def test_horizontal_offset_nan_is_inf():
    assert horizontal_offset(obs(x=float("nan"), y=0.0)) == float("inf")


def test_alignment_velocity_direction_preserved():
    vx, vy = alignment_velocity(obs(x=0.3, y=0.4), P)  # 模長 0.5 < max 1.0
    assert (vx, vy) == pytest.approx((0.3, 0.4))


def test_alignment_velocity_clamped():
    vx, vy = alignment_velocity(obs(x=3.0, y=4.0), P)  # 模長 5 → 夾到 1.0
    assert math.hypot(vx, vy) == pytest.approx(1.0)
    assert vy / vx == pytest.approx(4.0 / 3.0)  # 方向不變


def test_command_is_dataclass():
    m = sm()
    cmd = m.update(obs(visible=False), now=0.0)
    assert isinstance(cmd, LandCommand)


# ---- 參數驗證 ----
def test_bad_params_rejected():
    with pytest.raises(ValueError):
        LandParams(acquire_offset_m=0.6, align_tolerance_m=0.3)  # acquire > align
    with pytest.raises(ValueError):
        LandParams(align_tolerance_m=3.0, abort_offset_m=3.0)  # align 不 < abort
    with pytest.raises(ValueError):
        LandParams(descend_speed_ms=0.0)
    with pytest.raises(ValueError):
        LandParams(min_confidence=1.5)
    with pytest.raises(ValueError):
        LandParams(lost_timeout_s=0.0)

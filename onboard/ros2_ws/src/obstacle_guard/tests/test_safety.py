"""obstacle_guard 安全決策純邏輯測試(飛安每 PR 回歸;零 ROS)。"""

import math

import pytest
from obstacle_guard.safety import (
    GuardParams,
    clamp_horizontal_speed,
    is_stale,
    safe_speed_limit,
    speed_limit_from_distance,
)

P = GuardParams(
    stop_distance_m=3.0, slow_distance_m=10.0, max_speed_ms=12.0, watchdog_timeout_s=0.5
)


# ---- speed_limit_from_distance ----
def test_far_gives_max_speed():
    assert speed_limit_from_distance(20.0, P) == 12.0
    assert speed_limit_from_distance(10.0, P) == 12.0


def test_within_stop_gives_zero():
    assert speed_limit_from_distance(3.0, P) == 0.0
    assert speed_limit_from_distance(1.0, P) == 0.0


def test_linear_midpoint():
    # 距離 6.5 = stop(3)~slow(10) 的中點 → 一半速度
    assert speed_limit_from_distance(6.5, P) == pytest.approx(6.0)


def test_monotonic_increasing():
    prev = -1.0
    for d in [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]:
        v = speed_limit_from_distance(d, P)
        assert v >= prev
        prev = v


def test_invalid_distance_is_conservative():
    assert speed_limit_from_distance(float("nan"), P) == 0.0
    assert speed_limit_from_distance(0.0, P) == 0.0  # < min_valid
    assert speed_limit_from_distance(None, P) == 0.0  # type: ignore[arg-type]


# ---- staleness / watchdog ----
def test_stale_detection():
    assert is_stale(0.1, P) is False
    assert is_stale(0.6, P) is True
    assert is_stale(-1.0, P) is True
    assert is_stale(float("nan"), P) is True
    assert is_stale(None, P) is True  # type: ignore[arg-type]


def test_safe_speed_limit_stale_overrides_distance():
    # 即使距離很遠(該放行),stale 一律逼停
    assert safe_speed_limit(50.0, age_s=1.0, params=P) == 0.0
    # 新鮮 + 遠 → 放行
    assert safe_speed_limit(50.0, age_s=0.1, params=P) == 12.0
    # 新鮮 + 近 → 停
    assert safe_speed_limit(2.0, age_s=0.1, params=P) == 0.0


# ---- clamp ----
def test_clamp_within_limit_unchanged():
    assert clamp_horizontal_speed(3.0, 4.0, 10.0) == (3.0, 4.0)  # 模長 5 < 10


def test_clamp_scales_direction_preserved():
    vx, vy = clamp_horizontal_speed(6.0, 8.0, 5.0)  # 模長 10 → 夾到 5
    assert math.hypot(vx, vy) == pytest.approx(5.0)
    assert vy / vx == pytest.approx(8.0 / 6.0)  # 方向不變


def test_clamp_zero_limit_stops():
    assert clamp_horizontal_speed(3.0, 4.0, 0.0) == (0.0, 0.0)


def test_clamp_zero_velocity():
    assert clamp_horizontal_speed(0.0, 0.0, 5.0) == (0.0, 0.0)


# ---- params 驗證 ----
def test_bad_params_rejected():
    with pytest.raises(ValueError):
        GuardParams(stop_distance_m=10.0, slow_distance_m=5.0)  # stop >= slow
    with pytest.raises(ValueError):
        GuardParams(max_speed_ms=0)

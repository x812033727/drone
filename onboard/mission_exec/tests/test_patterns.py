"""patterns 航線產生器單元測試:航點數/行距/蛇行交替/走廊高度序列/參數驗證。"""

import math

import pytest
from mission_exec.patterns import corridor, survey_grid

_LAT, _LON = 47.397742, 8.545594  # SITL 預設家點(Zurich)
_R = 6371000.0
_K = math.pi / 180.0


def _north_m(lat_from: float, lat_to: float) -> float:
    return (lat_to - lat_from) * _K * _R


def _east_m(lat_ref: float, lon_from: float, lon_to: float) -> float:
    return (lon_to - lon_from) * _K * _R * math.cos(lat_ref * _K)


def _dist_m(a, b) -> float:
    return math.hypot(
        _north_m(a.lat_deg, b.lat_deg), _east_m(a.lat_deg, a.lon_deg, b.lon_deg)
    )


# ---- survey_grid --------------------------------------------------------------


def test_grid_waypoint_count_and_id():
    plan = survey_grid(_LAT, _LON, 160.0, 120.0, 40.0, 30.0, 8.0)
    # 120 / 40 → 4 行,每行 2 航點
    assert len(plan.waypoints) == 8
    assert plan.mission_id == "survey-grid-160x120-s40"
    assert all(wp.rel_alt_m == 30.0 and wp.speed_ms == 8.0 for wp in plan.waypoints)


def test_grid_line_spacing_equals_spacing():
    plan = survey_grid(_LAT, _LON, 160.0, 120.0, 40.0, 30.0, 8.0)
    wps = plan.waypoints
    # 同一行兩航點緯度相同;相鄰行緯差 = 行距 40 m
    for i in range(0, 8, 2):
        assert wps[i].lat_deg == wps[i + 1].lat_deg
    for i in range(0, 6, 2):
        assert _north_m(wps[i].lat_deg, wps[i + 2].lat_deg) == pytest.approx(40.0, abs=0.05)


def test_grid_serpentine_direction_alternates():
    plan = survey_grid(_LAT, _LON, 160.0, 120.0, 40.0, 30.0, 8.0)
    wps = plan.waypoints
    for i in range(0, 8, 2):
        d_east = _east_m(wps[i].lat_deg, wps[i].lon_deg, wps[i + 1].lon_deg)
        assert abs(d_east) == pytest.approx(160.0, abs=0.1)  # 行長 = width
        expect_east = i % 4 == 0  # 偶數行向東、奇數行向西
        assert (d_east > 0) is expect_east
    # 蛇行:行尾與下一行行首同一側(經度相同)
    for i in (1, 3, 5):
        assert wps[i].lon_deg == pytest.approx(wps[i + 1].lon_deg, abs=1e-12)


def test_grid_centered_on_center():
    plan = survey_grid(_LAT, _LON, 160.0, 120.0, 40.0, 30.0, 8.0)
    lats = [wp.lat_deg for wp in plan.waypoints]
    # 首行 -60 m、末行 +60 m(置中)
    assert _north_m(_LAT, min(lats)) == pytest.approx(-60.0, abs=0.05)
    assert _north_m(_LAT, max(lats)) == pytest.approx(60.0, abs=0.05)


def test_grid_height_not_multiple_of_spacing_shrinks_span():
    plan = survey_grid(_LAT, _LON, 100.0, 100.0, 40.0, 30.0, 5.0)
    # 100 // 40 + 1 = 3 行,實際跨距 80 m
    assert len(plan.waypoints) == 6
    lats = [wp.lat_deg for wp in plan.waypoints]
    assert _north_m(min(lats), max(lats)) == pytest.approx(80.0, abs=0.05)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"width_m": 0.0},
        {"height_m": -1.0},
        {"spacing_m": 0.0},
        {"alt_m": 0.0},
        {"speed_ms": -1.0},
    ],
)
def test_grid_rejects_bad_params(kwargs):
    base = dict(
        center_lat=_LAT, center_lon=_LON, width_m=160.0, height_m=120.0,
        spacing_m=40.0, alt_m=30.0, speed_ms=8.0,
    )
    with pytest.raises(ValueError):
        survey_grid(**{**base, **kwargs})


# ---- corridor -----------------------------------------------------------------


def test_corridor_altitude_sequence():
    plan = corridor(_LAT, _LON, 90.0, 500.0, [20.0, 35.0, 25.0], 8.0)
    # 每段 2 航點(段首/段尾同高度)→ 高度序列成對
    assert [wp.rel_alt_m for wp in plan.waypoints] == [20.0, 20.0, 35.0, 35.0, 25.0, 25.0]
    assert plan.mission_id == "corridor-500m-3leg"


def test_corridor_length_and_heading_east():
    plan = corridor(_LAT, _LON, 90.0, 500.0, [20.0, 35.0, 25.0], 8.0)
    wps = plan.waypoints
    assert _dist_m(wps[0], wps[-1]) == pytest.approx(500.0, abs=0.5)
    # 正東:緯度不變、經度遞增;段界處同點垂直轉換
    assert all(wp.lat_deg == pytest.approx(_LAT, abs=1e-9) for wp in wps)
    assert _east_m(_LAT, wps[0].lon_deg, wps[1].lon_deg) == pytest.approx(500 / 3, abs=0.2)
    for i in (1, 3):
        assert wps[i].lon_deg == pytest.approx(wps[i + 1].lon_deg, abs=1e-12)


def test_corridor_heading_north():
    plan = corridor(_LAT, _LON, 0.0, 300.0, [15.0], 5.0)
    wps = plan.waypoints
    assert len(wps) == 2
    assert _north_m(wps[0].lat_deg, wps[1].lat_deg) == pytest.approx(300.0, abs=0.3)
    assert wps[0].lon_deg == pytest.approx(wps[1].lon_deg, abs=1e-9)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"length_m": 0.0},
        {"leg_alts": []},
        {"leg_alts": [20.0, 0.0]},
        {"speed_ms": -0.1},
    ],
)
def test_corridor_rejects_bad_params(kwargs):
    base = dict(
        start_lat=_LAT, start_lon=_LON, heading_deg=90.0, length_m=500.0,
        leg_alts=[20.0, 35.0, 25.0], speed_ms=8.0,
    )
    with pytest.raises(ValueError):
        corridor(**{**base, **kwargs})


def test_mission_id_override():
    plan = survey_grid(_LAT, _LON, 80.0, 40.0, 40.0, 25.0, 5.0, mission_id="f07-mini")
    assert plan.mission_id == "f07-mini"

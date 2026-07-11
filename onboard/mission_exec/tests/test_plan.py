"""plan.load_plan 的解析與驗證測試。"""

import pytest

from mission_exec.plan import load_plan

VALID = """
{
  "missionId": "t-1",
  "waypoints": [
    {"latDeg": 47.397742, "lonDeg": 8.545594, "relAltM": 20.0, "holdS": 2.0, "speedMs": 5.0}
  ],
  "rtlAfterLast": true
}
"""


def _write(tmp_path, text):
    p = tmp_path / "mission.json"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_valid_plan(tmp_path):
    plan = load_plan(_write(tmp_path, VALID))
    assert plan.mission_id == "t-1"
    assert len(plan.waypoints) == 1
    wp = plan.waypoints[0]
    assert wp.lat_deg == pytest.approx(47.397742)
    assert wp.lon_deg == pytest.approx(8.545594)
    assert wp.rel_alt_m == pytest.approx(20.0)
    assert wp.hold_s == pytest.approx(2.0)
    assert wp.speed_ms == pytest.approx(5.0)
    assert plan.rtl_after_last is True


def test_reject_empty_waypoints(tmp_path):
    text = '{"missionId": "t-2", "waypoints": [], "rtlAfterLast": false}'
    with pytest.raises(ValueError, match="waypoints 不可為空"):
        load_plan(_write(tmp_path, text))


def test_reject_out_of_range_latitude(tmp_path):
    text = '{"missionId": "t-3", "waypoints": [{"latDeg": 91.0, "lonDeg": 8.5}]}'
    with pytest.raises(ValueError, match="緯度"):
        load_plan(_write(tmp_path, text))


def test_reject_out_of_range_longitude(tmp_path):
    text = '{"missionId": "t-3b", "waypoints": [{"latDeg": 47.0, "lonDeg": -180.5}]}'
    with pytest.raises(ValueError, match="經度"):
        load_plan(_write(tmp_path, text))


def test_reject_empty_mission_id(tmp_path):
    text = '{"waypoints": [{"latDeg": 47.0, "lonDeg": 8.5}]}'
    with pytest.raises(ValueError, match="mission_id"):
        load_plan(_write(tmp_path, text))


def test_reject_non_json(tmp_path):
    with pytest.raises(ValueError, match="不是合法的 MissionPlan JSON"):
        load_plan(_write(tmp_path, "這不是 JSON{{{"))


def test_reject_unknown_field(tmp_path):
    text = '{"missionId": "t-4", "waypoints": [], "notAField": 1}'
    with pytest.raises(ValueError, match="不是合法的 MissionPlan JSON"):
        load_plan(_write(tmp_path, text))


def test_reject_missing_file(tmp_path):
    with pytest.raises(ValueError, match="無法讀取任務檔"):
        load_plan(tmp_path / "nope.json")

"""translate.to_mission_items 的欄位映射測試。"""

import math

from drone.v1 import mission_pb2
from mavsdk.mission import MissionItem

from mission_exec.translate import to_mission_items


def _plan(*waypoints):
    return mission_pb2.MissionPlan(mission_id="t", waypoints=list(waypoints))


def test_basic_field_mapping():
    plan = _plan(
        mission_pb2.Waypoint(
            lat_deg=47.398642, lon_deg=8.546920, rel_alt_m=20.0, hold_s=2.0, speed_ms=5.0
        )
    )
    (item,) = to_mission_items(plan)
    assert item.latitude_deg == 47.398642
    assert item.longitude_deg == 8.546920
    assert item.relative_altitude_m == 20.0
    assert item.speed_m_s == 5.0
    assert item.loiter_time_s == 2.0
    assert item.is_fly_through is False  # 有停留 → 停點


def test_zero_speed_uses_default_nan():
    plan = _plan(mission_pb2.Waypoint(lat_deg=1.0, lon_deg=2.0, rel_alt_m=10.0, speed_ms=0.0))
    (item,) = to_mission_items(plan)
    assert math.isnan(item.speed_m_s)


def test_zero_hold_is_fly_through_with_nan_loiter():
    plan = _plan(mission_pb2.Waypoint(lat_deg=1.0, lon_deg=2.0, rel_alt_m=10.0, hold_s=0.0))
    (item,) = to_mission_items(plan)
    assert item.is_fly_through is True
    assert math.isnan(item.loiter_time_s)


def test_camera_and_gimbal_fields_use_defaults():
    plan = _plan(mission_pb2.Waypoint(lat_deg=1.0, lon_deg=2.0, rel_alt_m=10.0))
    (item,) = to_mission_items(plan)
    assert item.camera_action is MissionItem.CameraAction.NONE
    assert item.vehicle_action is MissionItem.VehicleAction.NONE
    assert math.isnan(item.gimbal_pitch_deg)
    assert math.isnan(item.gimbal_yaw_deg)
    assert math.isnan(item.acceptance_radius_m)
    assert math.isnan(item.yaw_deg)
    assert math.isnan(item.camera_photo_interval_s)
    assert math.isnan(item.camera_photo_distance_m)


def test_order_preserved():
    plan = _plan(
        mission_pb2.Waypoint(lat_deg=1.0, lon_deg=1.0, rel_alt_m=10.0),
        mission_pb2.Waypoint(lat_deg=2.0, lon_deg=2.0, rel_alt_m=11.0),
        mission_pb2.Waypoint(lat_deg=3.0, lon_deg=3.0, rel_alt_m=12.0),
    )
    items = to_mission_items(plan)
    assert [it.latitude_deg for it in items] == [1.0, 2.0, 3.0]
    assert [it.relative_altitude_m for it in items] == [10.0, 11.0, 12.0]

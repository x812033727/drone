"""Waypoint(drone.v1)→ MAVSDK MissionItem 轉譯(純函式,可單元測試)。"""

from drone.v1 import mission_pb2
from mavsdk.mission import MissionItem

_NAN = float("nan")


def to_mission_item(wp: mission_pb2.Waypoint) -> MissionItem:
    """單一航點轉譯。

    - speed_ms > 0 → speed_m_s;0 = 使用飛控預設(NaN)
    - hold_s > 0 → loiter_time_s 並停點(is_fly_through=False);0 = 直接通過
    - 相機/雲台欄位不適用,依 MAVSDK 慣例填 NaN 或 NONE
    """
    hold = wp.hold_s > 0.0
    return MissionItem(
        latitude_deg=wp.lat_deg,
        longitude_deg=wp.lon_deg,
        relative_altitude_m=wp.rel_alt_m,
        speed_m_s=wp.speed_ms if wp.speed_ms > 0.0 else _NAN,
        is_fly_through=not hold,
        gimbal_pitch_deg=_NAN,
        gimbal_yaw_deg=_NAN,
        camera_action=MissionItem.CameraAction.NONE,
        loiter_time_s=wp.hold_s if hold else _NAN,
        camera_photo_interval_s=_NAN,
        acceptance_radius_m=_NAN,
        yaw_deg=_NAN,
        camera_photo_distance_m=_NAN,
        vehicle_action=MissionItem.VehicleAction.NONE,
    )


def to_mission_items(plan: mission_pb2.MissionPlan) -> list[MissionItem]:
    """整份 MissionPlan 轉譯為 MAVSDK MissionItem 清單(順序不變)。"""
    return [to_mission_item(wp) for wp in plan.waypoints]

"""航線產生器(純函式):測繪蛇行網格與巡邏走廊 → drone.v1.MissionPlan。

對應架次:flight-test-plan F05(測繪網格)/ F06(巡邏走廊)的任務檔來源;
SITL 預跑(tools/sitl_scenarios f05–f08)與實機任務檔共用同一產生器。

經緯度平移用平面近似(tools/sitl_scenarios/runner.dist_m 同款公式的反函數:
北向 dlat = m / R、東向 dlon = m / (R·cos(lat))),百公尺級網格誤差可忽略;
產出一律過 plan.validate_plan(語意驗證單一事實來源)。
"""

import math

from drone.v1 import mission_pb2

from mission_exec.plan import validate_plan

#: 平面近似地球半徑(公尺;與 tools/sitl_scenarios/runner.dist_m 同值)
_EARTH_R_M = 6371000.0


def _offset(lat_deg: float, lon_deg: float, north_m: float, east_m: float) -> tuple[float, float]:
    """自 (lat, lon) 平移 north_m / east_m 公尺後的經緯度(平面近似)。"""
    k = math.pi / 180.0
    lat = lat_deg + north_m / _EARTH_R_M / k
    lon = lon_deg + east_m / (_EARTH_R_M * math.cos(lat_deg * k)) / k
    return lat, lon


def survey_grid(
    center_lat: float,
    center_lon: float,
    width_m: float,
    height_m: float,
    spacing_m: float,
    alt_m: float,
    speed_ms: float,
    *,
    mission_id: str | None = None,
) -> mission_pb2.MissionPlan:
    """蛇行測繪網格(F05):東西向航線、南→北堆疊,行距 = spacing_m。

    航線數 = floor(height_m / spacing_m) + 1,置中於 (center_lat, center_lon);
    每行兩個航點(西/東端 ±width_m/2),偶數行向東、奇數行向西(蛇行)。
    speed_ms = 0 表示使用飛控預設;rtl_after_last 由呼叫端自行設定。
    """
    if width_m <= 0 or height_m <= 0:
        raise ValueError(f"網格尺寸需為正:width_m={width_m} height_m={height_m}")
    if spacing_m <= 0:
        raise ValueError(f"行距需為正:spacing_m={spacing_m}")
    if alt_m <= 0:
        raise ValueError(f"航線高度需為正:alt_m={alt_m}")
    if speed_ms < 0:
        raise ValueError(f"速度不可為負:speed_ms={speed_ms}")

    n_lines = int(height_m // spacing_m) + 1
    span_m = (n_lines - 1) * spacing_m  # 實際南北跨距(height 非行距整數倍時內縮)
    half_w = width_m / 2.0

    waypoints = []
    for i in range(n_lines):
        north = -span_m / 2.0 + i * spacing_m
        ends = (-half_w, half_w) if i % 2 == 0 else (half_w, -half_w)  # 蛇行交替
        for east in ends:
            lat, lon = _offset(center_lat, center_lon, north, east)
            waypoints.append(
                mission_pb2.Waypoint(
                    lat_deg=lat, lon_deg=lon, rel_alt_m=alt_m, hold_s=0.0, speed_ms=speed_ms
                )
            )

    plan = mission_pb2.MissionPlan(
        mission_id=mission_id
        or f"survey-grid-{width_m:g}x{height_m:g}-s{spacing_m:g}",
        waypoints=waypoints,
    )
    validate_plan(plan)
    return plan


def corridor(
    start_lat: float,
    start_lon: float,
    heading_deg: float,
    length_m: float,
    leg_alts: list[float],
    speed_ms: float,
    *,
    mission_id: str | None = None,
) -> mission_pb2.MissionPlan:
    """直線走廊分段(F06):自起點沿 heading 直飛 length_m,均分為 len(leg_alts) 段。

    每段一個高度(平飛),段界處垂直轉換:每段產生「段首 + 段尾」兩個航點
    (同高度),故航點數 = 2 × len(leg_alts);heading_deg 0 = 正北、90 = 正東。
    """
    if length_m <= 0:
        raise ValueError(f"走廊長度需為正:length_m={length_m}")
    if not leg_alts:
        raise ValueError("leg_alts 不可為空(至少一段高度)")
    if any(alt <= 0 for alt in leg_alts):
        raise ValueError(f"各段高度需為正:leg_alts={leg_alts}")
    if speed_ms < 0:
        raise ValueError(f"速度不可為負:speed_ms={speed_ms}")

    k = math.pi / 180.0
    north_unit = math.cos(heading_deg * k)
    east_unit = math.sin(heading_deg * k)
    seg_m = length_m / len(leg_alts)

    waypoints = []
    for i, alt in enumerate(leg_alts):
        for d in (i * seg_m, (i + 1) * seg_m):  # 段首、段尾(同高度 → 平飛段)
            lat, lon = _offset(start_lat, start_lon, north_unit * d, east_unit * d)
            waypoints.append(
                mission_pb2.Waypoint(
                    lat_deg=lat, lon_deg=lon, rel_alt_m=alt, hold_s=0.0, speed_ms=speed_ms
                )
            )

    plan = mission_pb2.MissionPlan(
        mission_id=mission_id
        or f"corridor-{length_m:g}m-{len(leg_alts)}leg",
        waypoints=waypoints,
    )
    validate_plan(plan)
    return plan

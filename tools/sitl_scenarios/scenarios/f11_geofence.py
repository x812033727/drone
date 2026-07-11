"""F11 GeoFence(150 m circle inclusion 圍欄 + GF_ACTION=3 → RTL)SITL 回歸場景。

對應架次:flight-test-plan F11「GeoFence 觸發」/ 03-safety-analysis §4 GeoFence 列。

與試飛計畫寫法的差異(誠實註記,以探測實測為準):
  F11 計畫寫「任務航點刻意放界外」,但在 PX4 1.15 上這引不出物理越界——三層預防
  全擋:界外任務 start_mission 回 DENIED、界外 goto/reposition 靜默不動作、空中補
  上傳圍欄會讓現行任務被重驗直接 HOLD。這三層是矩陣「拒絕解鎖/預防」格的佐證,
  但空中 RTL 觸發驗證必須用 offboard 速度 setpoint(不受 feasibility check,等同
  飄移/飛逸)逼近邊界;實機則可用 RC 手動逼近。
  GF_PREDICT 本映像預設 0(PX4 上游預設 1):本場景顯式設 1(預測煞停,在邊界內
  即觸發);若 0 則越界後才觸發,8–12 m/s 下煞車距離可能吃掉 10 m 門檻——實機
  參數表應明確納入 GF_PREDICT=1。

注入法(探測實證 run1/4/5):
  1. 前置 param(INT32):GF_ACTION=3(RTL)、GF_PREDICT=1。geofence 非 failure
     注入,不需 SYS_FAILURE_EN。
  2. clear_geofence(圍欄存 dataman,跨 MAVSDK session 殘留)後上傳
     150 m circle inclusion 圍欄(圓心 = home)。地面與空中上傳皆接受。
  3. 起飛至 30 m 懸停,offboard set_velocity_ned 北向 8 m/s 直逼邊界。

通過準則(實測 run5:113.6 m → 117.9 m 預測煞停 HOLD → 128.8 m RETURN_TO_LAUNCH,
max 128.8 m,離邊界 -21.2 m 零穿越):
  1. RETURN_TO_LAUNCH 觸發(offboard 開始後 120 s 內)
  2. 觸發點離 home > 90 m(0.6×半徑;確認是貼近邊界觸發,非其他原因返航)
  3. 全程 max 離 home 距離 ≤ 150+10 m(F11 通過準則「不穿越圍欄 > 10 m」)

量測註記:RTL 觸發距離取自模式事件當下的位置遙測(約 1 Hz 粒度),
非飛控內部觸發瞬間。
"""

import asyncio

from mavsdk.geofence import Circle, FenceType, GeofenceData, Point
from mavsdk.offboard import OffboardError, VelocityNedYaw

from sitl_scenarios.checks import crossed_boundary
from sitl_scenarios.runner import (
    Recorder,
    ScenarioConfig,
    ScenarioError,
    ScenarioResult,
    connect,
    logline,
    make_clock,
    wait_position_ready,
)

NAME = "f11"
TITLE = "F11 GeoFence(150 m circle inclusion + GF_ACTION=3 → RTL)"

FENCE_RADIUS_M = 150.0
BREACH_MARGIN_M = 10.0  # F11 通過準則:不穿越 > 10 m
NEAR_BOUNDARY_MIN_M = FENCE_RADIUS_M * 0.6
SPEED_MS = 8.0
TAKEOFF_ALT_M = 30.0


async def run(cfg: ScenarioConfig) -> ScenarioResult:
    clock = make_clock()
    result = ScenarioResult(NAME)
    drone = await connect(cfg)

    await drone.param.set_param_int("GF_ACTION", 3)
    await drone.param.set_param_int("GF_PREDICT", 1)
    ga = await drone.param.get_param_int("GF_ACTION")
    gp = await drone.param.get_param_int("GF_PREDICT")
    if ga != 3 or gp != 1:
        raise ScenarioError(f"參數驗證失敗:GF_ACTION={ga} GF_PREDICT={gp}")
    result.notes.append(f"param 驗證:GF_ACTION={ga} GF_PREDICT={gp}(映像預設 GF_PREDICT=0)")

    await asyncio.wait_for(wait_position_ready(drone), timeout=120)
    home = await anext(aiter(drone.telemetry.home()))
    hlat, hlon = home.latitude_deg, home.longitude_deg
    logline(clock(), f"home={hlat:.7f},{hlon:.7f}")

    await drone.geofence.clear_geofence()  # dataman 殘留清除(run1 教訓)
    await drone.geofence.upload_geofence(
        GeofenceData(
            polygons=[],
            circles=[Circle(Point(hlat, hlon), FENCE_RADIUS_M, FenceType.INCLUSION)],
        )
    )
    logline(clock(), f"已上傳 circle inclusion 圍欄 r={FENCE_RADIUS_M} m @ home")

    rec = Recorder(drone, clock, home=(hlat, hlon))
    rec.start()
    try:
        await drone.action.set_takeoff_altitude(TAKEOFF_ALT_M)
        await drone.action.arm()
        await drone.action.takeoff()
        deadline = clock() + 90
        while clock() < deadline:
            if rec.rel_alt > TAKEOFF_ALT_M - 5.0:
                break
            await asyncio.sleep(0.5)
        else:
            raise ScenarioError(f"起飛未達 {TAKEOFF_ALT_M - 5.0:.0f} m(alt={rec.rel_alt:.1f})")
        await asyncio.sleep(5)  # 讓 takeoff 收斂進 HOLD

        await drone.offboard.set_velocity_ned(VelocityNedYaw(SPEED_MS, 0.0, 0.0, 0.0))
        try:
            await drone.offboard.start()
        except OffboardError as e:
            raise ScenarioError(f"offboard start 被拒:{e._result.result}") from e
        offb_t = clock()
        logline(offb_t, f"OFFBOARD 北向 {SPEED_MS} m/s(朝界外;等同飄移/飛逸)")

        rtl_mark: tuple[float, str, float] | None = None
        last_print = 0.0
        while clock() - offb_t < 120:
            rtl_mark = next(
                (mk for mk in rec.mode_marks if mk[1] == "RETURN_TO_LAUNCH" and mk[0] > offb_t),
                None,
            )
            if rtl_mark:
                break
            if clock() - last_print >= 5:
                last_print = clock()
                logline(clock(), f"dist={rec.dist_home:.1f} m max={rec.max_dist_home:.1f} m")
            await asyncio.sleep(0.5)

        if rtl_mark:
            # 觸發後續觀察(邊界零穿越要涵蓋煞停/回轉段的 max 距離)
            t_end = clock() + 45
            while clock() < t_end:
                if rec.dist_home < 20.0:
                    break
                await asyncio.sleep(0.5)
        # 不呼叫 offboard.stop():stop 會另切模式,干擾 RTL 斷言;RTL 已接管。
    finally:
        await rec.stop()

    trig_dist = rtl_mark[2] if rtl_mark else None
    result.add(
        "GeoFence 觸發 RETURN_TO_LAUNCH",
        rtl_mark is not None,
        f"t={rtl_mark[0]:.1f}s dist={trig_dist:.1f} m" if rtl_mark else "120 s 內未觸發",
    )
    result.add(
        f"觸發點貼近邊界(> {NEAR_BOUNDARY_MIN_M:.0f} m)",
        trig_dist is not None and trig_dist > NEAR_BOUNDARY_MIN_M,
        f"觸發距離 {trig_dist:.1f} m(實測基準 ~128.8 m,GF_PREDICT 預測煞停在邊界內)"
        if trig_dist is not None
        else "無觸發距離",
    )
    result.add(
        f"不穿越圍欄 > {BREACH_MARGIN_M:.0f} m",
        not crossed_boundary(rec.max_dist_home, FENCE_RADIUS_M, BREACH_MARGIN_M),
        f"max dist_home={rec.max_dist_home:.1f} m,邊界 {FENCE_RADIUS_M:.0f} m"
        f"(越界 {rec.max_dist_home - FENCE_RADIUS_M:+.1f} m)",
    )
    result.mode_events = rec.mode_events
    return result

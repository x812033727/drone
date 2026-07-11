"""F08 RTH 全流程(任務中段觸發 RTL → 爬升返航降落)SITL 回歸場景。

對應架次:flight-test-plan F08「RTH 全流程」的 SITL 預跑。

與試飛計畫寫法的差異(誠實註記):
  計畫寫「任務中段以 RC 開關觸發 RTL」——SITL 無實體 RC,以
  `drone.action.return_to_launch()`(MAV_CMD_NAV_RETURN_TO_LAUNCH)作代理:
  進的是同一個 RTL 模式與同一套 RTL_* 參數行為,僅觸發來源不同。
  「降落偏差 ≤ 1 m」屬實機 RTK 量測項,SITL 斷言放寬為落點離 home ≤ 5 m
  (SITL GPS 模型粒度)。
  RTL_RETURN_ALT 顯式設 50 m(映像預設值不依賴),觸發點離 home 60–72 m、
  RTL cone(45°)允許高度 > 50 m,故必爬升至 50 m 再返航。

剖面:
  120×80 m 蛇行網格(3 行 6 航點、30 m 高、8 m/s、無 rtl_after_last),
  mission_progress current_item ≥ 2 時(任務中段,已過首行)下發 RTL。

通過準則:
  1. 觸發當下 current_item ≥ 1(任務中段,非起飛段)
  2. 觸發後 20 s 內 flight_mode → RETURN_TO_LAUNCH
  3. 先爬升:觸發後最大 rel_alt ≥ RTL_RETURN_ALT − 5 m,且高於觸發當下 ≥ 5 m
  4. 180 s 內落地且自動 disarm
  5. 落點離 home ≤ 5 m(SITL 粗驗;實機準則 ≤ 1 m)
"""

import asyncio

from mavsdk.mission import MissionPlan as MavMissionPlan
from mission_exec.patterns import survey_grid
from mission_exec.translate import to_mission_items

from sitl_scenarios.checks import latency_to_mode
from sitl_scenarios.runner import (
    Recorder,
    ScenarioConfig,
    ScenarioError,
    ScenarioResult,
    arm_with_retry,
    connect,
    logline,
    make_clock,
    wait_position_ready,
)

NAME = "f08"
TITLE = "F08 RTH 全流程(任務中段觸發 RTL → 爬升 50 m 返航 → 降落 disarm)"

GRID_W_M, GRID_H_M, SPACING_M = 120.0, 80.0, 40.0  # 3 行 6 航點
ALT_M, SPEED_MS = 30.0, 8.0
RTL_RETURN_ALT_M = 50.0
TRIGGER_ITEM = 2  # current ≥ 2:已過首行,任務中段
RTL_MODE_TIMEOUT_S = 20.0
LAND_TIMEOUT_S = 180.0
CLIMB_SHORTFALL_TOL_M = 5.0
LAND_OFFSET_MAX_M = 5.0
SAMPLE_PERIOD_S = 0.5


async def run(cfg: ScenarioConfig) -> ScenarioResult:
    clock = make_clock()
    result = ScenarioResult(NAME)
    drone = await connect(cfg)

    await drone.param.set_param_float("RTL_RETURN_ALT", RTL_RETURN_ALT_M)
    ra = await drone.param.get_param_float("RTL_RETURN_ALT")
    if abs(ra - RTL_RETURN_ALT_M) > 0.1:
        raise ScenarioError(f"參數驗證失敗:RTL_RETURN_ALT={ra}")
    result.notes.append(f"param 驗證:RTL_RETURN_ALT={ra:g} m(顯式設定,不依賴映像預設)")

    await asyncio.wait_for(wait_position_ready(drone), timeout=120)
    home = await anext(aiter(drone.telemetry.home()))
    hlat, hlon = home.latitude_deg, home.longitude_deg
    logline(clock(), f"home={hlat:.7f},{hlon:.7f}")

    plan = survey_grid(
        hlat, hlon, GRID_W_M, GRID_H_M, SPACING_M, ALT_M, SPEED_MS, mission_id="f08-rth"
    )
    # RTL 由中途手動觸發,不掛任務尾端 RTL(設定必在 upload 之前)
    await drone.mission.set_return_to_launch_after_mission(False)
    await drone.mission.upload_mission(MavMissionPlan(to_mission_items(plan)))
    logline(clock(), f"已上傳 {len(plan.waypoints)} 航點網格({ALT_M:g} m / {SPEED_MS:g} m/s)")

    rec = Recorder(drone, clock, home=(hlat, hlon))
    rec.start()
    alt_samples: list[tuple[float, float]] = []

    async def sample_alt() -> None:
        while True:
            alt_samples.append((clock(), rec.rel_alt))
            await asyncio.sleep(SAMPLE_PERIOD_S)

    sampler = asyncio.create_task(sample_alt())
    try:
        await arm_with_retry(drone)
        await drone.mission.start_mission()
        logline(clock(), "已 arm + start_mission")

        async def wait_mid_mission() -> int:
            async for p in drone.mission.mission_progress():
                if p.current >= TRIGGER_ITEM:
                    return p.current
            raise ScenarioError("mission_progress 串流在觸發點前結束(鏈路中斷?)")

        try:
            trigger_item = await asyncio.wait_for(wait_mid_mission(), timeout=180)
        except (asyncio.TimeoutError, TimeoutError):
            raise ScenarioError(
                f"180 s 內未達觸發點 current≥{TRIGGER_ITEM}(任務未推進)"
            ) from None

        t_trigger = clock()
        alt_at_trigger = rec.rel_alt
        dist_at_trigger = rec.dist_home
        logline(
            t_trigger,
            f"任務中段 item={trigger_item}(alt={alt_at_trigger:.1f} m,"
            f"dist={dist_at_trigger:.1f} m)→ 觸發 return_to_launch(模擬 RC 開關)",
        )
        await drone.action.return_to_launch()

        result.add(
            "觸發當下任務中段(current_item ≥ 1)",
            trigger_item >= 1,
            f"item={trigger_item},dist={dist_at_trigger:.1f} m",
        )

        landed_disarmed = False
        deadline = t_trigger + LAND_TIMEOUT_S
        while clock() < deadline:
            if rec.in_air is False and rec.armed is False:
                landed_disarmed = True
                break
            await asyncio.sleep(0.5)
    finally:
        sampler.cancel()
        await asyncio.gather(sampler, return_exceptions=True)
        await rec.stop()

    rtl_lat = latency_to_mode(rec.mode_events, "RETURN_TO_LAUNCH", t_trigger)
    result.add(
        f"觸發後 {RTL_MODE_TIMEOUT_S:g} s 內 flight_mode → RETURN_TO_LAUNCH",
        rtl_lat is not None and rtl_lat <= RTL_MODE_TIMEOUT_S,
        f"延遲 {rtl_lat:.1f} s" if rtl_lat is not None else "未觀測到 RETURN_TO_LAUNCH",
    )

    max_alt_after = max((a for t, a in alt_samples if t >= t_trigger), default=0.0)
    climb_ok = (
        max_alt_after >= RTL_RETURN_ALT_M - CLIMB_SHORTFALL_TOL_M
        and max_alt_after >= alt_at_trigger + 5.0
    )
    result.add(
        f"先爬升至 RTL_RETURN_ALT({RTL_RETURN_ALT_M:g} m)方向再返航",
        climb_ok,
        f"觸發時 {alt_at_trigger:.1f} m → 觸發後 max {max_alt_after:.1f} m",
    )

    result.add(
        f"{LAND_TIMEOUT_S:g} s 內落地並自動 disarm",
        landed_disarmed,
        f"in_air={rec.in_air} armed={rec.armed}",
    )
    result.add(
        f"落點離 home ≤ {LAND_OFFSET_MAX_M:g} m(SITL 粗驗;實機準則 ≤ 1 m)",
        landed_disarmed and rec.dist_home <= LAND_OFFSET_MAX_M,
        f"落點 dist_home={rec.dist_home:.1f} m",
    )

    result.mode_events = rec.mode_events
    return result

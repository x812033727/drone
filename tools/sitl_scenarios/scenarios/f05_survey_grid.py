"""F05 測繪網格航線(蛇行網格全航點完成 + 軌跡覆蓋)SITL 回歸場景。

對應架次:flight-test-plan F05「測繪網格航線」的 SITL 預跑。

與試飛計畫寫法的差異(誠實註記):
  計畫寫「QGC Survey 產生 200×200 m 網格、70% 旁向重疊、50 m 高」——SITL 預跑
  改用 mission_exec.patterns.survey_grid 自產 160×120 m、行距 40 m、30 m 高的
  等價蛇行網格(驗的是「多行網格任務可完整執行」,不驗 QGC 產生器本身);
  「速度誤差 ≤ 1 m/s、轉彎不掉高 > 2 m」屬實機 ULog 量測項,SITL 不斷言。
  任務經 mission_exec.executor.run_mission 執行(與機上同一條路徑,
  含 RECEIVED→…→COMPLETED 狀態機),非裸 MAVSDK。

剖面:
  home 為中心 160×120 m 網格、行距 40 m(4 行 8 航點)、30 m 高、8 m/s,
  rtl_after_last=True(對齊 demo_square 已驗證的完成判定路徑)。

通過準則:
  1. STATE_COMPLETED(全航點完成;run_mission 正常返回)
  2. current_item 走滿 1..7(0-based 進行中索引,觀測到 k 即 0..k-1 已完成;
     搭配 COMPLETED = 8 航點全數走完、無跳點)
  3. 遙測北/東極值覆蓋網格範圍 ±60/±80 m(容差 15 m:fly-through 切角
     NAV_ACC_RAD=10 m + 取樣粒度)
"""

import asyncio

from drone.v1 import mission_pb2
from mission_exec.executor import MissionExecError, run_mission
from mission_exec.patterns import survey_grid

from sitl_scenarios.checks import items_all_visited, span_covered
from sitl_scenarios.runner import (
    Recorder,
    ScenarioConfig,
    ScenarioResult,
    connect,
    logline,
    make_clock,
    wait_position_ready,
)

NAME = "f05"
TITLE = "F05 測繪網格航線(160×120 m 蛇行網格、行距 40 m → 全航點完成 + 覆蓋)"

GRID_W_M = 160.0
GRID_H_M = 120.0
SPACING_M = 40.0
ALT_M = 30.0
SPEED_MS = 8.0
COVER_TOL_M = 15.0  # fly-through 切角(NAV_ACC_RAD=10 m)+ 遙測取樣粒度


async def run(cfg: ScenarioConfig) -> ScenarioResult:
    clock = make_clock()
    result = ScenarioResult(NAME)
    drone = await connect(cfg)

    await asyncio.wait_for(wait_position_ready(drone), timeout=120)
    home = await anext(aiter(drone.telemetry.home()))
    hlat, hlon = home.latitude_deg, home.longitude_deg
    logline(clock(), f"home={hlat:.7f},{hlon:.7f}")

    plan = survey_grid(
        hlat, hlon, GRID_W_M, GRID_H_M, SPACING_M, ALT_M, SPEED_MS, mission_id="f05-survey-grid"
    )
    plan.rtl_after_last = True
    n_wp = len(plan.waypoints)
    logline(clock(), f"survey_grid:{n_wp} 航點(4 行蛇行),{ALT_M:g} m / {SPEED_MS:g} m/s")

    events: list[tuple[float, str, int]] = []  # (t, state 名, current_item)

    async def progress_cb(p: mission_pb2.MissionProgress) -> None:
        state = mission_pb2.MissionProgress.State.Name(p.state)
        events.append((clock(), state, p.current_item))
        logline(clock(), f"進度 {state} item={p.current_item}/{p.total_items}")

    rec = Recorder(drone, clock, home=(hlat, hlon))
    rec.start()
    exec_error: str | None = None
    try:
        # 與機上同一條執行路徑(上傳/arm 重試/start/進度訂閱皆由 executor 收斂)
        await run_mission(drone, plan, "f05-sitl", progress_cb)
    except MissionExecError as e:
        exec_error = str(e)
        logline(clock(), f"run_mission 失敗:{e}")
    finally:
        await rec.stop()

    states = [s for _, s, _ in events]
    result.add(
        "任務 STATE_COMPLETED(全航點完成)",
        "STATE_COMPLETED" in states,
        exec_error or f"狀態序列:{[s for s in states if s != 'STATE_IN_PROGRESS']}",
    )

    in_prog_items = [i for _, s, i in events if s == "STATE_IN_PROGRESS"]
    result.add(
        f"current_item 走滿 1..{n_wp - 1}(逐點推進無跳點)",
        items_all_visited(in_prog_items, n_wp - 1),
        f"觀測 items={sorted(set(in_prog_items))}",
    )

    half_h, half_w = GRID_H_M / 2.0, GRID_W_M / 2.0
    ns_ok = span_covered(rec.north_min, rec.north_max, -half_h, half_h, COVER_TOL_M)
    ew_ok = span_covered(rec.east_min, rec.east_max, -half_w, half_w, COVER_TOL_M)
    result.add(
        f"軌跡覆蓋網格範圍(北 ±{half_h:g} m / 東 ±{half_w:g} m,容差 {COVER_TOL_M:g} m)",
        ns_ok and ew_ok,
        f"北 [{rec.north_min:.1f}, {rec.north_max:.1f}] m,"
        f"東 [{rec.east_min:.1f}, {rec.east_max:.1f}] m",
    )

    result.mode_events = rec.mode_events
    return result

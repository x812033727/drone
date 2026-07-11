"""F06 巡邏走廊航線(直線走廊分段變高)SITL 回歸場景。

對應架次:flight-test-plan F06「巡邏走廊航線」的 SITL 預跑。

與試飛計畫寫法的差異(誠實註記):
  計畫寫「Corridor ≥ 800 m、含 2 個高度變化」——SITL 預跑縮為 500 m 三段
  (20/35/25 m,同樣 2 次高度轉換;驗的是「分段變高走廊可完整執行且高度
  依序轉換」,航程長短不改變行為語義);「高度轉換平順無超調 > 3 m」的
  超調量測屬實機 ULog 項,SITL 斷言為「各段高度依序達到 ±3 m」。
  任務經 mission_exec.executor.run_mission 執行(與機上同一條路徑)。

剖面:
  home 起點、正東 500 m 直線,均分三段各 166.7 m,高度 20/35/25 m
  (每段段首+段尾同高度 → 平飛段、段界垂直轉換,共 6 航點)、8 m/s,
  rtl_after_last=True。

通過準則:
  1. STATE_COMPLETED(全航點完成)
  2. 遙測 rel_alt 依序達到 20 → 35 → 25 m(各 ±3 m;0.5 s 取樣,
     子序列語意允許段間爬升/下降過渡值)
"""

import asyncio

from drone.v1 import mission_pb2
from mission_exec.executor import MissionExecError, run_mission
from mission_exec.patterns import corridor

from sitl_scenarios.checks import alts_reached_in_order
from sitl_scenarios.runner import (
    Recorder,
    ScenarioConfig,
    ScenarioResult,
    connect,
    logline,
    make_clock,
    wait_position_ready,
)

NAME = "f06"
TITLE = "F06 巡邏走廊航線(500 m 三段 20/35/25 m → 全航點完成 + 高度依序轉換)"

HEADING_DEG = 90.0  # 正東
LENGTH_M = 500.0
LEG_ALTS_M = [20.0, 35.0, 25.0]
SPEED_MS = 8.0
ALT_TOL_M = 3.0  # F06 通過準則:高度轉換 ±3 m
SAMPLE_PERIOD_S = 0.5


async def run(cfg: ScenarioConfig) -> ScenarioResult:
    clock = make_clock()
    result = ScenarioResult(NAME)
    drone = await connect(cfg)

    await asyncio.wait_for(wait_position_ready(drone), timeout=120)
    home = await anext(aiter(drone.telemetry.home()))
    hlat, hlon = home.latitude_deg, home.longitude_deg
    logline(clock(), f"home={hlat:.7f},{hlon:.7f}")

    plan = corridor(
        hlat, hlon, HEADING_DEG, LENGTH_M, LEG_ALTS_M, SPEED_MS, mission_id="f06-corridor"
    )
    plan.rtl_after_last = True
    logline(
        clock(),
        f"corridor:{len(plan.waypoints)} 航點,正東 {LENGTH_M:g} m,"
        f"三段高度 {'/'.join(f'{a:g}' for a in LEG_ALTS_M)} m,{SPEED_MS:g} m/s",
    )

    events: list[tuple[float, str, int]] = []

    async def progress_cb(p: mission_pb2.MissionProgress) -> None:
        state = mission_pb2.MissionProgress.State.Name(p.state)
        events.append((clock(), state, p.current_item))
        logline(clock(), f"進度 {state} item={p.current_item}/{p.total_items}")

    rec = Recorder(drone, clock, home=(hlat, hlon))
    rec.start()
    alt_samples: list[tuple[float, float]] = []

    async def sample_alt() -> None:
        while True:
            alt_samples.append((clock(), rec.rel_alt))
            await asyncio.sleep(SAMPLE_PERIOD_S)

    sampler = asyncio.create_task(sample_alt())
    exec_error: str | None = None
    try:
        await run_mission(drone, plan, "f06-sitl", progress_cb)
    except MissionExecError as e:
        exec_error = str(e)
        logline(clock(), f"run_mission 失敗:{e}")
    finally:
        sampler.cancel()
        await asyncio.gather(sampler, return_exceptions=True)
        await rec.stop()

    states = [s for _, s, _ in events]
    result.add(
        "任務 STATE_COMPLETED(全航點完成)",
        "STATE_COMPLETED" in states,
        exec_error or f"狀態序列:{[s for s in states if s != 'STATE_IN_PROGRESS']}",
    )

    targets = "→".join(f"{a:g}" for a in LEG_ALTS_M)
    result.add(
        f"高度依序轉換 {targets} m(各 ±{ALT_TOL_M:g} m)",
        alts_reached_in_order(alt_samples, LEG_ALTS_M, ALT_TOL_M),
        f"取樣 {len(alt_samples)} 筆,max alt={max((a for _, a in alt_samples), default=0.0):.1f} m",
    )

    result.mode_events = rec.mode_events
    return result

"""任務執行狀態機:RTL 設定 → 上傳 → arm → start → 進度訂閱 → 完成判定。

狀態機(對應 drone.v1.MissionProgress.State):
    RECEIVED → UPLOADED → IN_PROGRESS(current_item 遞增)→ COMPLETED
    任何例外(上傳失敗、飛控拒絕、鏈路中斷、定位/進度逾時)→ FAILED 後 raise MissionExecError

`drone` 只需長得像 mavsdk.System(duck typing),單元測試可用 mock 物件替換。
進度發布為 best-effort:progress_cb 拋例外只記 WARNING,永不中斷任務。
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from drone.v1 import mission_pb2
from mavsdk.mission import MissionPlan as MavMissionPlan

from mission_exec.translate import to_mission_items

ProgressCallback = Callable[[mission_pb2.MissionProgress], Awaitable[None]]

_LOG = logging.getLogger(__name__)

#: 等待 GPS/home 就緒的預設逾時(秒)
DEFAULT_HEALTH_TIMEOUT_S = 120.0
#: 進度事件停滯的預設逾時(秒)。航點間隔可能很長,
#: 逾時針對「完全無任何進度事件」而非「任務未完成」。
DEFAULT_PROGRESS_STALL_S = 300.0


class MissionExecError(RuntimeError):
    """任務執行失敗(已發出 STATE_FAILED 事件後拋出)。"""


def _now_ms() -> int:
    return int(time.time() * 1000)


async def _wait_position_ready(drone) -> None:
    """等待全球定位 + home 點就緒(可被 asyncio.wait_for 包逾時)。"""
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            return
    raise RuntimeError("健康狀態串流在定位就緒前結束(鏈路中斷?)")


async def run_mission(
    drone,
    plan: mission_pb2.MissionPlan,
    drone_id: str,
    progress_cb: ProgressCallback,
    *,
    health_timeout_s: float = DEFAULT_HEALTH_TIMEOUT_S,
    progress_stall_s: float = DEFAULT_PROGRESS_STALL_S,
) -> None:
    """執行整趟任務;progress_cb 於每次狀態變化/航點推進時被 await。

    前置條件:drone 已連線(connection_state 已 is_connected)。
    progress_cb 例外一律吞下並記 WARNING(進度發布永不致命)。
    """
    total = len(plan.waypoints)
    current = 0

    async def emit(state: mission_pb2.MissionProgress.State) -> None:
        try:
            await progress_cb(
                mission_pb2.MissionProgress(
                    mission_id=plan.mission_id,
                    drone_id=drone_id,
                    current_item=current,
                    total_items=total,
                    state=state,
                    unix_time_ms=_now_ms(),
                )
            )
        except Exception:
            _LOG.warning(
                "進度發布失敗(state=%s),任務照常繼續",
                mission_pb2.MissionProgress.State.Name(state),
                exc_info=True,
            )

    await emit(mission_pb2.MissionProgress.STATE_RECEIVED)
    try:
        # RTL 設定必須在 upload_mission「之前」:MAVSDK 明載該設定
        # 「will only take effect for the next mission upload」,上傳後才設完全無效。
        await drone.mission.set_return_to_launch_after_mission(plan.rtl_after_last)
        await drone.mission.upload_mission(MavMissionPlan(to_mission_items(plan)))
        await emit(mission_pb2.MissionProgress.STATE_UPLOADED)

        # 等待可起飛(全球定位 + home 點就緒);加逾時避免串流靜默時永久阻塞
        try:
            await asyncio.wait_for(_wait_position_ready(drone), timeout=health_timeout_s)
        except (asyncio.TimeoutError, TimeoutError):
            raise TimeoutError(
                f"定位未就緒:等待 GPS/home 超過 {health_timeout_s:g} 秒"
            ) from None

        await drone.action.arm()
        await drone.mission.start_mission()

        # 進度訂閱:current 每推進一個航點發一次 IN_PROGRESS;
        # current == total 即全部航點完成(RTL 由飛控接手,不屬任務進度)。
        # 每筆事件間加停滯逾時:飛控斷線/失效保護接管時串流會靜默,不可永久等待。
        last_reported = -1
        progress_iter = aiter(drone.mission.mission_progress())
        while True:
            try:
                progress = await asyncio.wait_for(anext(progress_iter), timeout=progress_stall_s)
            except StopAsyncIteration:
                raise RuntimeError("進度串流在任務完成前結束(鏈路中斷?)") from None
            except (asyncio.TimeoutError, TimeoutError):
                raise TimeoutError(
                    f"進度停滯逾時:{progress_stall_s:g} 秒內無任何進度事件"
                    "(鏈路中斷或失效保護接管?)"
                ) from None
            if progress.total <= 0:
                continue
            if progress.current >= progress.total:
                current = total
                await emit(mission_pb2.MissionProgress.STATE_COMPLETED)
                return
            if progress.current != last_reported:
                last_reported = progress.current
                current = progress.current
                await emit(mission_pb2.MissionProgress.STATE_IN_PROGRESS)
    except Exception as e:
        await emit(mission_pb2.MissionProgress.STATE_FAILED)
        raise MissionExecError(f"任務 {plan.mission_id} 執行失敗:{e}") from e

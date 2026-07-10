"""任務執行狀態機:上傳 → arm → start → 進度訂閱 → 完成判定。

狀態機(對應 drone.v1.MissionProgress.State):
    RECEIVED → UPLOADED → IN_PROGRESS(current_item 遞增)→ COMPLETED
    任何例外(上傳失敗、飛控拒絕、鏈路中斷)→ FAILED 後 raise MissionExecError

`drone` 只需長得像 mavsdk.System(duck typing),單元測試可用 mock 物件替換。
"""

import time
from collections.abc import Awaitable, Callable

from drone.v1 import mission_pb2
from mavsdk.mission import MissionPlan as MavMissionPlan

from mission_exec.translate import to_mission_items

ProgressCallback = Callable[[mission_pb2.MissionProgress], Awaitable[None]]


class MissionExecError(RuntimeError):
    """任務執行失敗(已發出 STATE_FAILED 事件後拋出)。"""


def _now_ms() -> int:
    return int(time.time() * 1000)


async def run_mission(
    drone,
    plan: mission_pb2.MissionPlan,
    drone_id: str,
    progress_cb: ProgressCallback,
) -> None:
    """執行整趟任務;progress_cb 於每次狀態變化/航點推進時被 await。

    前置條件:drone 已連線(connection_state 已 is_connected)。
    """
    total = len(plan.waypoints)
    current = 0

    async def emit(state: mission_pb2.MissionProgress.State) -> None:
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

    await emit(mission_pb2.MissionProgress.STATE_RECEIVED)
    try:
        # 上傳任務與返航設定
        await drone.mission.upload_mission(MavMissionPlan(to_mission_items(plan)))
        await drone.mission.set_return_to_launch_after_mission(plan.rtl_after_last)
        await emit(mission_pb2.MissionProgress.STATE_UPLOADED)

        # 等待可起飛(全球定位 + home 點就緒)
        async for health in drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok:
                break

        await drone.action.arm()
        await drone.mission.start_mission()

        # 進度訂閱:current 每推進一個航點發一次 IN_PROGRESS;
        # current == total 即全部航點完成(RTL 由飛控接手,不屬任務進度)。
        last_reported = -1
        async for progress in drone.mission.mission_progress():
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
        raise RuntimeError("進度串流在任務完成前結束(鏈路中斷?)")
    except Exception as e:
        await emit(mission_pb2.MissionProgress.STATE_FAILED)
        raise MissionExecError(f"任務 {plan.mission_id} 執行失敗:{e}") from e

"""任務執行狀態機:RTL 設定 → 上傳 → arm → start → 進度訂閱 → 完成判定。

狀態機(對應 drone.v1.MissionProgress.State):
    RECEIVED → UPLOADED → IN_PROGRESS(current_item 遞增)→ COMPLETED
    IN_PROGRESS ⇄ PAUSED(S23:MissionCommand PAUSE/RESUME)
    ABORT → RTL 收尾 → FAILED(契約 State 無 ABORTED,以 FAILED 承載,
    log 與例外訊息註明 abort;對齊 S12「rc≠0 一律補發 FAILED」語意,重複無害)
    任何例外(上傳失敗、飛控拒絕、鏈路中斷、定位/進度逾時)→ FAILED 後 raise MissionExecError

任務控制(S23):`ctrl_queue` 由呼叫端餵入 drone.v1.MissionCommand——
    - PAUSE  → drone.mission.pause_mission()   → 發 STATE_PAUSED(帶 current_item)
    - RESUME → drone.mission.start_mission()   → 回 STATE_IN_PROGRESS
    - ABORT  → drone.action.return_to_launch() → 發 STATE_FAILED 後 raise
    mission_id 不符當前任務、未知命令、狀態不符(未暫停收 RESUME 等)一律
    log 後忽略。**PAUSED 期間停滯逾時暫停計時**(暫停是合法靜止,不可誤殺)。

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


class _MissionAborted(RuntimeError):
    """收到 COMMAND_ABORT、RTL 已下發(內部訊號:走統一 FAILED 收尾)。"""


def _now_ms() -> int:
    return int(time.time() * 1000)


async def wait_position_ready(drone) -> None:
    """等待全球定位 + home 點就緒(可被 asyncio.wait_for 包逾時)。

    公開複用點(tools/sitl_scenarios 亦 import 此函式)。
    """
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            return
    raise RuntimeError("健康狀態串流在定位就緒前結束(鏈路中斷?)")


ARM_ATTEMPTS = 8
ARM_RETRY_DELAY_S = 5.0


async def _arm_with_retry(drone) -> None:
    """arm 並對飛控拒絕重試(慢 runner 上 SITL 就緒晚於定位就緒的常見情況)。

    2026-07-11 nightly 實錄:wait_position_ready 已過但 arm 立即 COMMAND_DENIED。
    重試耗盡讓最後一次 ActionError 原樣拋出,由 run_mission 統一轉 MissionExecError
    (FAILED 事件照發)。
    """
    from mavsdk.action import ActionError

    for attempt in range(1, ARM_ATTEMPTS + 1):
        try:
            await drone.action.arm()
            return
        except ActionError as e:
            if attempt == ARM_ATTEMPTS:
                raise
            print(
                f"arm 被拒({e}),{ARM_RETRY_DELAY_S:.0f}s 後重試({attempt}/{ARM_ATTEMPTS})",
                flush=True,
            )
            await asyncio.sleep(ARM_RETRY_DELAY_S)


async def run_mission(
    drone,
    plan: mission_pb2.MissionPlan,
    drone_id: str,
    progress_cb: ProgressCallback,
    *,
    health_timeout_s: float = DEFAULT_HEALTH_TIMEOUT_S,
    progress_stall_s: float = DEFAULT_PROGRESS_STALL_S,
    ctrl_queue: "asyncio.Queue[mission_pb2.MissionCommand] | None" = None,
    resume_from: int = 0,
) -> None:
    """執行整趟任務;progress_cb 於每次狀態變化/航點推進時被 await。

    前置條件:drone 已連線(connection_state 已 is_connected)。
    progress_cb 例外一律吞下並記 WARNING(進度發布永不致命)。

    ctrl_queue:任務控制命令來源(MissionCommand;None = 控制通道停用)。
    resume_from:斷點續飛——上傳後 set_current_mission_item(N) 再 start
    (0 = 從頭;需 0 <= N < 航點總數)。
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

    paused = False

    async def handle_ctrl(cmd: mission_pb2.MissionCommand) -> bool:
        """處理單筆控制命令;回傳是否有效執行(RESUME 生效時重置停滯計時)。

        不符/未知/狀態不符一律 log 後忽略(QoS 1 at-least-once,dup 常態);
        ABORT 下 RTL 後 raise _MissionAborted,由外層統一發 FAILED 收尾。
        """
        nonlocal paused
        try:
            cmd_name = mission_pb2.MissionCommand.Command.Name(cmd.command)
        except ValueError:
            # proto3 開放 enum:未知數字值能通過 Parse,Name() 才炸——
            # 不可讓未知命令炸掉任務,一律走忽略分支
            cmd_name = f"UNKNOWN({cmd.command})"
        if cmd.mission_id != plan.mission_id:
            _LOG.warning(
                "忽略 mission_ctrl %s:mission_id %r 不符當前任務 %r",
                cmd_name,
                cmd.mission_id,
                plan.mission_id,
            )
            return False
        if cmd.command == mission_pb2.MissionCommand.COMMAND_PAUSE:
            if paused:
                _LOG.info("忽略重複 PAUSE:任務已暫停(QoS 1 dup)")
                return False
            await drone.mission.pause_mission()
            paused = True
            _LOG.info("任務 %s 已暫停(current_item=%d)", plan.mission_id, current)
            await emit(mission_pb2.MissionProgress.STATE_PAUSED)
            return True
        if cmd.command == mission_pb2.MissionCommand.COMMAND_RESUME:
            if not paused:
                _LOG.info("忽略 RESUME:任務未在暫停中")
                return False
            await drone.mission.start_mission()
            paused = False
            _LOG.info("任務 %s 已續飛(current_item=%d)", plan.mission_id, current)
            await emit(mission_pb2.MissionProgress.STATE_IN_PROGRESS)
            return True
        if cmd.command == mission_pb2.MissionCommand.COMMAND_ABORT:
            _LOG.warning("任務 %s 收到 ABORT:下發 RTL 返航", plan.mission_id)
            await drone.action.return_to_launch()
            raise _MissionAborted("收到 COMMAND_ABORT:任務中止,已下 RTL 返航")
        _LOG.warning("忽略未知 mission_ctrl 命令:%s", cmd_name)
        return False

    await emit(mission_pb2.MissionProgress.STATE_RECEIVED)
    try:
        # RTL 設定必須在 upload_mission「之前」:MAVSDK 明載該設定
        # 「will only take effect for the next mission upload」,上傳後才設完全無效。
        await drone.mission.set_return_to_launch_after_mission(plan.rtl_after_last)
        await drone.mission.upload_mission(MavMissionPlan(to_mission_items(plan)))
        await emit(mission_pb2.MissionProgress.STATE_UPLOADED)

        # 斷點續飛:上傳後、start 前把目前航點撥到 N(進度事件的 current_item
        # 可供外部記錄斷點)
        if resume_from:
            if not 0 <= resume_from < total:
                raise ValueError(f"resume_from={resume_from} 超出範圍 [0, {total})")
            await drone.mission.set_current_mission_item(resume_from)
            current = resume_from

        # 等待可起飛(全球定位 + home 點就緒);加逾時避免串流靜默時永久阻塞
        try:
            await asyncio.wait_for(wait_position_ready(drone), timeout=health_timeout_s)
        except (asyncio.TimeoutError, TimeoutError):
            raise TimeoutError(
                f"定位未就緒:等待 GPS/home 超過 {health_timeout_s:g} 秒"
            ) from None

        await _arm_with_retry(drone)
        await drone.mission.start_mission()

        # 進度訂閱:current 每推進一個航點發一次 IN_PROGRESS;
        # current == total 即全部航點完成(RTL 由飛控接手,不屬任務進度)。
        # 每筆事件間加停滯逾時:飛控斷線/失效保護接管時串流會靜默,不可永久等待;
        # 控制命令與進度事件併聽(asyncio.wait FIRST_COMPLETED)。
        # **PAUSED 期間停滯計時暫停**(timeout=None):暫停是合法靜止,
        # 不可被當停滯誤殺;RESUME 後重新起算。
        last_reported = -1
        progress_iter = aiter(drone.mission.mission_progress())
        progress_task: asyncio.Task | None = None
        ctrl_task: asyncio.Task | None = None
        try:
            deadline = time.monotonic() + progress_stall_s
            while True:
                if progress_task is None:
                    progress_task = asyncio.ensure_future(anext(progress_iter))
                if ctrl_queue is not None and ctrl_task is None:
                    ctrl_task = asyncio.ensure_future(ctrl_queue.get())
                waiting = {progress_task} | ({ctrl_task} if ctrl_task is not None else set())
                timeout = None if paused else max(0.0, deadline - time.monotonic())
                done, _ = await asyncio.wait(
                    waiting, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
                )
                if not done:
                    raise TimeoutError(
                        f"進度停滯逾時:{progress_stall_s:g} 秒內無任何進度事件"
                        "(鏈路中斷或失效保護接管?)"
                    )
                if ctrl_task is not None and ctrl_task in done:
                    cmd = ctrl_task.result()
                    ctrl_task = None
                    if await handle_ctrl(cmd) and not paused:
                        deadline = time.monotonic() + progress_stall_s  # RESUME 後重新起算
                if progress_task in done:
                    try:
                        progress = progress_task.result()
                    except StopAsyncIteration:
                        raise RuntimeError("進度串流在任務完成前結束(鏈路中斷?)") from None
                    progress_task = None
                    deadline = time.monotonic() + progress_stall_s
                    if progress.total <= 0:
                        continue
                    if progress.current >= progress.total:
                        current = total
                        await emit(mission_pb2.MissionProgress.STATE_COMPLETED)
                        return
                    if progress.current != last_reported:
                        last_reported = progress.current
                        current = progress.current
                        # 暫停中飛控可能重發同/舊 current(Hold 靜止),
                        # 只更新斷點、不發 IN_PROGRESS 以免蓋掉 PAUSED 狀態
                        if not paused:
                            await emit(mission_pb2.MissionProgress.STATE_IN_PROGRESS)
        finally:
            for task in (progress_task, ctrl_task):
                if task is not None:
                    task.cancel()
    except Exception as e:
        await emit(mission_pb2.MissionProgress.STATE_FAILED)
        raise MissionExecError(f"任務 {plan.mission_id} 執行失敗:{e}") from e

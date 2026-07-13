"""precision_land 純狀態機邏輯(零 ROS 依賴)。

視覺標靶精準降落狀態機(REQ-LOG-03:ArUco/AprilTag 標靶引導,著陸誤差 < 30 cm)。
比照 obstacle_guard.safety:飛安/降落決策全在此零 ROS 純邏輯庫,進 pytest gate
每 PR 回歸;ROS node(node.py)只做薄 I/O 包裝。

安全邊界鐵則(docs/20-software/companion-computer.md):
- Jetson 只對 PX4 發**速度限制 / setpoint 修正**,絕不發姿態級指令。本狀態機輸出
  水平對準速度 + 下降速率(皆為 setpoint 級),交由 node/PX4 執行。
- 感知輸入失效(標靶不可見 / 置信度不足 / 逾時)→ 一律**停止下降並保守處置**
  (REACQUIRE 懸停重試,逾時 ABORT 中止降落),寧可中止不可盲降。

狀態:
    SEARCH    —— 尋找標靶(懸停/搜尋),逾 search_timeout_s 未見 → ABORT。
    ACQUIRED  —— 已鎖定標靶,水平對準中(不下降);對準進 acquire_offset_m → DESCEND。
    DESCEND   —— 對準且在容差內,邊修正水平邊下降;高度 <= landed_altitude_m → LANDED。
    REACQUIRE —— 標靶丟失,懸停停降重試;逾 lost_timeout_s 未復得 → ABORT。
    ABORT     —— 中止降落(停止下降、停在原地/交由上層 RTH),終止態。
    LANDED    —— 已著陸(零速度),終止態。

座標/單位:水平偏移公尺(標靶相對機體,0=正下方對準),高度公尺(AGL),
置信度 0..1,時間秒(呼叫端傳入單調時鐘)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class LandState(str, Enum):
    """精準降落狀態(str 子類:方便直接發布為 std_msgs/String)。"""

    SEARCH = "SEARCH"
    ACQUIRED = "ACQUIRED"
    DESCEND = "DESCEND"
    REACQUIRE = "REACQUIRE"
    ABORT = "ABORT"
    LANDED = "LANDED"


TERMINAL_STATES = frozenset({LandState.ABORT, LandState.LANDED})


@dataclass(frozen=True)
class LandParams:
    """精準降落參數(建構時驗證)。距離公尺、速度公尺/秒、時間秒。"""

    acquire_offset_m: float = 0.30  # 水平偏移 <= 此值視為對準,可開始下降(REQ 誤差目標)
    align_tolerance_m: float = 0.60  # 下降中偏移 <= 此值續降;超過退回 ACQUIRED 重對準(遲滯)
    abort_offset_m: float = 3.0  # 偏移超過此硬上限 → 直接 ABORT(標靶誤鎖/發散)
    descend_speed_ms: float = 0.35  # 標稱下降速率(向下為正)
    horizontal_gain: float = 1.0  # 水平對準 P 增益(偏移 → 修正速度)
    max_horizontal_speed_ms: float = 1.0  # 水平修正速度模長上限
    min_confidence: float = 0.5  # 標靶置信度低於此值視為不可信(等同不可見)
    landed_altitude_m: float = 0.15  # 高度 <= 此值視為已著陸
    search_timeout_s: float = 30.0  # SEARCH 逾此秒數未見標靶 → ABORT
    lost_timeout_s: float = 3.0  # 標靶丟失(REACQUIRE)逾此秒數未復得 → ABORT

    def __post_init__(self) -> None:
        if not (0 < self.acquire_offset_m <= self.align_tolerance_m < self.abort_offset_m):
            raise ValueError("需 0 < acquire_offset_m <= align_tolerance_m < abort_offset_m")
        if self.descend_speed_ms <= 0:
            raise ValueError("descend_speed_ms 需 > 0")
        if self.max_horizontal_speed_ms <= 0:
            raise ValueError("max_horizontal_speed_ms 需 > 0")
        if not (0 <= self.min_confidence <= 1):
            raise ValueError("min_confidence 需在 [0, 1]")
        if self.landed_altitude_m < 0:
            raise ValueError("landed_altitude_m 需 >= 0")
        if self.search_timeout_s <= 0 or self.lost_timeout_s <= 0:
            raise ValueError("search_timeout_s / lost_timeout_s 需 > 0")


@dataclass(frozen=True)
class Observation:
    """單一控制週期的感知輸入。

    target_visible: 標靶偵測器本週期是否有輸出。
    offset_x / offset_y: 標靶相對機體的水平偏移(公尺;0=正下方對準)。
    altitude_m: 對地高度(AGL,公尺)。
    confidence: 標靶偵測置信度(0..1)。
    """

    target_visible: bool
    offset_x: float
    offset_y: float
    altitude_m: float
    confidence: float


@dataclass(frozen=True)
class LandCommand:
    """狀態機輸出(setpoint 級,絕不含姿態指令)。

    vx / vy: 水平對準速度指令(公尺/秒,機體/局部平面)。
    descent_rate_ms: 下降速率(公尺/秒,向下為正;>0 才下降)。
    state: 本週期結束後的狀態。
    abort: 是否進入中止(state == ABORT)。
    landed: 是否已著陸(state == LANDED)。
    """

    vx: float
    vy: float
    descent_rate_ms: float
    state: LandState
    abort: bool
    landed: bool


def _target_valid(obs: Observation, params: LandParams) -> bool:
    """標靶是否可信:可見、置信度足夠、偏移/高度為合法數值。"""
    if not obs.target_visible:
        return False
    conf = obs.confidence
    if conf is None or math.isnan(conf) or conf < params.min_confidence:
        return False
    for v in (obs.offset_x, obs.offset_y, obs.altitude_m):
        if v is None or math.isnan(v):
            return False
    return True


def horizontal_offset(obs: Observation) -> float:
    """水平偏移模長(公尺);非法值回 inf(視為未對準)。"""
    if obs.offset_x is None or obs.offset_y is None:
        return float("inf")
    if math.isnan(obs.offset_x) or math.isnan(obs.offset_y):
        return float("inf")
    return math.hypot(obs.offset_x, obs.offset_y)


def alignment_velocity(obs: Observation, params: LandParams) -> tuple[float, float]:
    """由水平偏移算對準速度(P 控制,模長夾到 max_horizontal_speed_ms,方向不變)。

    偏移 = 標靶相對機體;機體朝標靶方向移動以對準,故速度同號於偏移。
    """
    vx = obs.offset_x * params.horizontal_gain
    vy = obs.offset_y * params.horizontal_gain
    mag = math.hypot(vx, vy)
    if mag > params.max_horizontal_speed_ms and mag > 0:
        scale = params.max_horizontal_speed_ms / mag
        vx, vy = vx * scale, vy * scale
    return (vx, vy)


class PrecisionLandStateMachine:
    """精準降落狀態機(有狀態容器,轉移為純決策)。

    node 每個控制週期呼叫 ``update(obs, now)``;``now`` 為單調時鐘秒數
    (比照 obstacle_guard node 傳入 time.monotonic()),使逾時判斷可在測試中
    以假時間完全決定,零 ROS。
    """

    def __init__(self, params: LandParams | None = None) -> None:
        self.params = params or LandParams()
        self.state: LandState = LandState.SEARCH
        self._state_entered_at: float | None = None  # 進入當前狀態的時間戳

    def reset(self) -> None:
        """回到 SEARCH 初始態(重新啟動一次降落)。"""
        self.state = LandState.SEARCH
        self._state_entered_at = None

    def _enter(self, state: LandState, now: float) -> None:
        self.state = state
        self._state_entered_at = now

    def _time_in_state(self, now: float) -> float:
        if self._state_entered_at is None:
            return 0.0
        return now - self._state_entered_at

    @staticmethod
    def _hold(state: LandState) -> LandCommand:
        """懸停(零速度)輸出,附帶狀態旗標。"""
        return LandCommand(
            vx=0.0,
            vy=0.0,
            descent_rate_ms=0.0,
            state=state,
            abort=state is LandState.ABORT,
            landed=state is LandState.LANDED,
        )

    def update(self, obs: Observation, now: float) -> LandCommand:
        """推進一個控制週期,回傳本週期速度/下降指令。

        終止態(ABORT/LANDED)為吸收態:持續回傳懸停/零速度,需 reset() 才重啟。
        """
        if self._state_entered_at is None:
            self._state_entered_at = now

        if self.state in TERMINAL_STATES:
            return self._hold(self.state)

        valid = _target_valid(obs, self.params)
        offset = horizontal_offset(obs)

        if self.state is LandState.SEARCH:
            if valid:
                self._enter(LandState.ACQUIRED, now)
                return self._corrective(obs, descend=False)
            if self._time_in_state(now) > self.params.search_timeout_s:
                self._enter(LandState.ABORT, now)
                return self._hold(LandState.ABORT)
            return self._hold(LandState.SEARCH)

        if self.state is LandState.ACQUIRED:
            if not valid:
                self._enter(LandState.REACQUIRE, now)
                return self._hold(LandState.REACQUIRE)
            if offset > self.params.abort_offset_m:
                self._enter(LandState.ABORT, now)
                return self._hold(LandState.ABORT)
            if offset <= self.params.acquire_offset_m:
                self._enter(LandState.DESCEND, now)
                return self._corrective(obs, descend=True)
            return self._corrective(obs, descend=False)

        if self.state is LandState.DESCEND:
            if not valid:
                self._enter(LandState.REACQUIRE, now)
                return self._hold(LandState.REACQUIRE)
            if offset > self.params.abort_offset_m:
                self._enter(LandState.ABORT, now)
                return self._hold(LandState.ABORT)
            if obs.altitude_m <= self.params.landed_altitude_m:
                self._enter(LandState.LANDED, now)
                return self._hold(LandState.LANDED)
            if offset > self.params.align_tolerance_m:
                # 下降中漂出容差:停降退回 ACQUIRED 重對準(遲滯避免抖動)。
                self._enter(LandState.ACQUIRED, now)
                return self._corrective(obs, descend=False)
            return self._corrective(obs, descend=True)

        if self.state is LandState.REACQUIRE:
            if valid:
                # 復得標靶:依當前對準程度回 DESCEND 或 ACQUIRED。
                if offset <= self.params.acquire_offset_m:
                    self._enter(LandState.DESCEND, now)
                    return self._corrective(obs, descend=True)
                self._enter(LandState.ACQUIRED, now)
                return self._corrective(obs, descend=False)
            if self._time_in_state(now) > self.params.lost_timeout_s:
                self._enter(LandState.ABORT, now)
                return self._hold(LandState.ABORT)
            return self._hold(LandState.REACQUIRE)

        # 不可達:防禦性保守停。
        return self._hold(self.state)

    def _corrective(self, obs: Observation, descend: bool) -> LandCommand:
        """輸出水平對準速度 +(可選)下降速率。"""
        vx, vy = alignment_velocity(obs, self.params)
        rate = self.params.descend_speed_ms if descend else 0.0
        return LandCommand(
            vx=vx,
            vy=vy,
            descent_rate_ms=rate,
            state=self.state,
            abort=False,
            landed=False,
        )

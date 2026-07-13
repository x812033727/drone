"""obstacle_guard 純安全決策邏輯(零 ROS 依賴)。

安全邊界鐵則(docs/20-software/companion-computer.md):
- Jetson 只對 PX4 發**速度限制 / setpoint 修正**,絕不發姿態級指令。
- 感知輸入失效(stale / 缺值 / 非法)→ 一律退回**保守限速(停)**,不影響飛安。
- 本模組刻意零 ROS import:純函式進 ci.yml pytest gate,飛安決策每 PR 回歸
  (比照 tools/sitl_scenarios/checks.py)。ROS node 包裝在 P1(node.py)。

座標/單位:距離公尺(前方最近障礙),速度公尺/秒(水平),時間秒。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class GuardParams:
    """避障限速參數。stop < slow;超過 slow 不限速(回 max_speed)。"""

    stop_distance_m: float = 3.0  # <= 此距離:速度限為 0(逼停)
    slow_distance_m: float = 10.0  # stop~slow 之間:線性遞增限速
    max_speed_ms: float = 12.0  # 無障礙時的水平速度上限
    watchdog_timeout_s: float = 0.5  # 感知輸入超過此秒數未更新視為 stale
    min_valid_distance_m: float = 0.05  # 小於此值視為感測雜訊/非法

    def __post_init__(self) -> None:
        if not (0 <= self.stop_distance_m < self.slow_distance_m):
            raise ValueError("需 0 <= stop_distance_m < slow_distance_m")
        if self.max_speed_ms <= 0:
            raise ValueError("max_speed_ms 需 > 0")
        if self.watchdog_timeout_s <= 0:
            raise ValueError("watchdog_timeout_s 需 > 0")


def speed_limit_from_distance(distance_m: float, params: GuardParams) -> float:
    """依前方最近障礙距離算水平速度上限(公尺/秒)。

    距離無效(NaN / < min_valid)→ 保守回 0。<= stop → 0;>= slow → max;
    之間線性內插。回傳恆在 [0, max_speed_ms]。
    """
    if distance_m is None or math.isnan(distance_m) or distance_m < params.min_valid_distance_m:
        return 0.0
    if distance_m <= params.stop_distance_m:
        return 0.0
    if distance_m >= params.slow_distance_m:
        return params.max_speed_ms
    span = params.slow_distance_m - params.stop_distance_m
    frac = (distance_m - params.stop_distance_m) / span
    return max(0.0, min(params.max_speed_ms, frac * params.max_speed_ms))


def is_stale(age_s: float, params: GuardParams) -> bool:
    """感知輸入是否過期(age 為距上次更新的秒數;負值/NaN 視為 stale)。"""
    if age_s is None or math.isnan(age_s) or age_s < 0:
        return True
    return age_s > params.watchdog_timeout_s


def safe_speed_limit(distance_m: float, age_s: float, params: GuardParams) -> float:
    """綜合決策:感知 stale → 保守停(0);否則依距離限速。

    這是 node 每個控制週期呼叫的主入口。stale 優先於距離判斷——
    寧可停,不可用過期距離放行。
    """
    if is_stale(age_s, params):
        return 0.0
    return speed_limit_from_distance(distance_m, params)


def clamp_horizontal_speed(vx: float, vy: float, max_speed_ms: float) -> tuple[float, float]:
    """把水平速度向量的模長夾到 max_speed_ms(方向不變)。

    對 PX4 發送前對 companion 期望的速度 setpoint 做上限夾制。
    max_speed_ms<=0 → 回 (0,0)(逼停)。
    """
    if max_speed_ms <= 0:
        return (0.0, 0.0)
    mag = math.hypot(vx, vy)
    if mag <= max_speed_ms or mag == 0:
        return (vx, vy)
    scale = max_speed_ms / mag
    return (vx * scale, vy * scale)

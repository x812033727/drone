"""共享遙測狀態與 MAVSDK 訂閱協程。

由 tools/telemetry_monitor.py 重構而來:原本各 watch_* 直接 print,
這裡改為寫入共享 TelemetryState(只存最新快照),讓 publisher 以固定
頻率取樣組包。欄位命名刻意與 drone.v1.TelemetrySummary 一致,
snapshot() 可直接逐欄映射。
"""

import logging
import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from mavsdk import System

logger = logging.getLogger(__name__)


@dataclass
class TelemetryState:
    """各 MAVSDK 遙測流的最新值;None 表示尚未收到該流的任何資料。

    last_update_monotonic / last_update_wall 由 touch() 維護:任一流每次
    更新欄位後呼叫,分別記單調時鐘(供斷流判定,不受系統校時影響)與
    wall-clock(供 unix_time_ms 表達真正的取樣時間)。

    pending_events:armed 流邊緣(False→True / True→False)產生的待發
    飛行事件佇列,元素為 (armed, unix_time_ms);由 publisher 發佈迴圈取出
    組成 FlightEvent 上報 fleet/{id}/events(QoS 1)。啟動後收到的第一筆
    armed 值只是初始狀態,不算邊緣、不產生事件。

    disarm_callback:True→False 邊緣(上鎖)時同步呼叫的回呼(None=不掛)。
    S20 的 ULog 自動回收由 main 組裝時掛 LogUploader.trigger;回呼本身
    必須非阻塞(trigger 只 create_task 就返回),不得拖慢遙測訂閱迴圈。
    """

    lat_deg: float | None = None
    lon_deg: float | None = None
    rel_alt_m: float | None = None
    heading_deg: float | None = None
    ground_speed_ms: float | None = None
    flight_mode: str | None = None
    armed: bool | None = None
    battery_v: float | None = None
    battery_pct: float | None = None
    health_all_ok: bool | None = None
    satellites: int | None = None
    gps_fix_type: str | None = None
    hdop: float | None = None
    vertical_speed_ms: float | None = None
    last_update_monotonic: float | None = None
    last_update_wall: float | None = None
    pending_events: deque = field(default_factory=deque)
    disarm_callback: Callable[[], None] | None = None

    def touch(self) -> None:
        """記錄「最後一次任一流更新」的時間;每個 watch_* 更新欄位後呼叫。"""
        self.last_update_monotonic = time.monotonic()
        self.last_update_wall = time.time()


async def watch_position(drone: System, state: TelemetryState) -> None:
    async for pos in drone.telemetry.position():
        state.lat_deg = pos.latitude_deg
        state.lon_deg = pos.longitude_deg
        state.rel_alt_m = pos.relative_altitude_m
        state.touch()


async def watch_heading(drone: System, state: TelemetryState) -> None:
    async for heading in drone.telemetry.heading():
        state.heading_deg = heading.heading_deg
        state.touch()


async def watch_velocity(drone: System, state: TelemetryState) -> None:
    async for vel in drone.telemetry.velocity_ned():
        # 地速 = NED 水平分量合成(不含垂直速度)
        state.ground_speed_ms = math.hypot(vel.north_m_s, vel.east_m_s)
        # 垂直速度:契約定義向上為正,NED 的 down 分量反號
        state.vertical_speed_ms = -vel.down_m_s
        state.touch()


async def watch_flight_mode(drone: System, state: TelemetryState) -> None:
    async for mode in drone.telemetry.flight_mode():
        state.flight_mode = str(mode)
        state.touch()


async def watch_armed(drone: System, state: TelemetryState) -> None:
    async for armed in drone.telemetry.armed():
        prev = state.armed
        state.armed = armed
        state.touch()
        # 邊緣偵測:啟動後第一筆(prev is None)只是初始狀態,不算邊緣
        if prev is not None and prev != armed:
            state.pending_events.append((armed, int(state.last_update_wall * 1000)))
            # 上鎖邊緣(True→False)另觸發 disarm 回呼(S20 ULog 自動回收);
            # 回呼必須非阻塞,例外不得炸掉遙測訂閱迴圈
            if not armed and state.disarm_callback is not None:
                try:
                    state.disarm_callback()
                except Exception:
                    logger.exception("disarm 回呼失敗(忽略,不影響遙測)")


async def watch_gps_info(drone: System, state: TelemetryState) -> None:
    async for gps in drone.telemetry.gps_info():
        state.satellites = gps.num_satellites
        # MAVSDK FixType enum 名(如 "FIX_3D"、"RTK_FIXED"),契約以字串傳輸
        state.gps_fix_type = gps.fix_type.name
        state.touch()


async def watch_raw_gps(drone: System, state: TelemetryState) -> None:
    async for raw in drone.telemetry.raw_gps():
        state.hdop = raw.hdop
        state.touch()


async def watch_battery(drone: System, state: TelemetryState) -> None:
    async for battery in drone.telemetry.battery():
        state.battery_v = battery.voltage_v
        state.battery_pct = battery.remaining_percent
        state.touch()


async def watch_health(drone: System, state: TelemetryState) -> None:
    async for health in drone.telemetry.health():
        # 契約定義:可解鎖 / 定位 / 校準各項全部通過才算 all ok
        state.health_all_ok = (
            health.is_armable
            and health.is_global_position_ok
            and health.is_local_position_ok
            and health.is_home_position_ok
            and health.is_gyrometer_calibration_ok
            and health.is_accelerometer_calibration_ok
            and health.is_magnetometer_calibration_ok
        )
        state.touch()


# main.py 以 asyncio.gather 啟動的全部訂閱協程
WATCHERS = (
    watch_position,
    watch_heading,
    watch_velocity,
    watch_flight_mode,
    watch_armed,
    watch_battery,
    watch_health,
    watch_gps_info,
    watch_raw_gps,
)

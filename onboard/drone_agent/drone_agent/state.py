"""共享遙測狀態與 MAVSDK 訂閱協程。

由 tools/telemetry_monitor.py 重構而來:原本各 watch_* 直接 print,
這裡改為寫入共享 TelemetryState(只存最新快照),讓 publisher 以固定
頻率取樣組包。欄位命名刻意與 drone.v1.TelemetrySummary 一致,
snapshot() 可直接逐欄映射。
"""

import math
from dataclasses import dataclass

from mavsdk import System


@dataclass
class TelemetryState:
    """各 MAVSDK 遙測流的最新值;None 表示尚未收到該流的任何資料。"""

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


async def watch_position(drone: System, state: TelemetryState) -> None:
    async for pos in drone.telemetry.position():
        state.lat_deg = pos.latitude_deg
        state.lon_deg = pos.longitude_deg
        state.rel_alt_m = pos.relative_altitude_m


async def watch_heading(drone: System, state: TelemetryState) -> None:
    async for heading in drone.telemetry.heading():
        state.heading_deg = heading.heading_deg


async def watch_velocity(drone: System, state: TelemetryState) -> None:
    async for vel in drone.telemetry.velocity_ned():
        # 地速 = NED 水平分量合成(不含垂直速度)
        state.ground_speed_ms = math.hypot(vel.north_m_s, vel.east_m_s)


async def watch_flight_mode(drone: System, state: TelemetryState) -> None:
    async for mode in drone.telemetry.flight_mode():
        state.flight_mode = str(mode)


async def watch_armed(drone: System, state: TelemetryState) -> None:
    async for armed in drone.telemetry.armed():
        state.armed = armed


async def watch_battery(drone: System, state: TelemetryState) -> None:
    async for battery in drone.telemetry.battery():
        state.battery_v = battery.voltage_v
        state.battery_pct = battery.remaining_percent


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


# main.py 以 asyncio.gather 啟動的全部訂閱協程
WATCHERS = (
    watch_position,
    watch_heading,
    watch_velocity,
    watch_flight_mode,
    watch_armed,
    watch_battery,
    watch_health,
)

#!/usr/bin/env python3
"""Phase 0 遙測監看工具:連上 PX4(SITL 或實機)後即時列印關鍵遙測。

用途:驗證 MAVLink 鏈路與飛行狀態,是 POC 階段的第一個煙霧測試。

用法:
    # PX4 SITL(預設 offboard 埠 14540)
    python telemetry_monitor.py

    # 實機(經數傳,序列埠)
    python telemetry_monitor.py --url serial:///dev/ttyUSB0:57600

依賴:pip install -r requirements.txt(mavsdk)
"""

import argparse
import asyncio
import sys
import time

from mavsdk import System


async def watch_flight_mode(drone: System) -> None:
    async for mode in drone.telemetry.flight_mode():
        print(f"[模式] {mode}")


async def watch_armed(drone: System) -> None:
    async for armed in drone.telemetry.armed():
        print(f"[解鎖] {'已解鎖' if armed else '已上鎖'}")


async def watch_battery(drone: System) -> None:
    last_report = 0.0
    async for battery in drone.telemetry.battery():
        now = time.monotonic()
        if now - last_report >= 5.0:  # 每 5 秒一筆
            print(
                f"[電池] {battery.voltage_v:.1f} V"
                f"  剩餘 {battery.remaining_percent:.0f}%"
            )
            last_report = now


async def watch_position(drone: System) -> None:
    last_report = 0.0
    async for pos in drone.telemetry.position():
        now = time.monotonic()
        if now - last_report >= 1.0:  # 1 Hz
            print(
                f"[位置] lat={pos.latitude_deg:.6f} lon={pos.longitude_deg:.6f}"
                f"  相對高度 {pos.relative_altitude_m:.1f} m"
            )
            last_report = now


async def watch_health(drone: System) -> None:
    healthy = None
    async for health in drone.telemetry.health():
        ok = health.is_armable and health.is_global_position_ok
        if ok != healthy:
            healthy = ok
            print(
                f"[健康] 可解鎖={health.is_armable}"
                f" 全球定位={health.is_global_position_ok}"
                f" 本地定位={health.is_local_position_ok}"
                f" 校準(陀螺/加計/磁)="
                f"{health.is_gyrometer_calibration_ok}/"
                f"{health.is_accelerometer_calibration_ok}/"
                f"{health.is_magnetometer_calibration_ok}"
            )


async def run(url: str) -> None:
    drone = System()
    print(f"連線中:{url}")
    await drone.connect(system_address=url)

    async for state in drone.core.connection_state():
        if state.is_connected:
            print("已連上飛行器")
            break

    await asyncio.gather(
        watch_flight_mode(drone),
        watch_armed(drone),
        watch_battery(drone),
        watch_position(drone),
        watch_health(drone),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="udpin://0.0.0.0:14540",
        help="MAVSDK 連線字串(預設 SITL:udpin://0.0.0.0:14540;"
        "序列埠範例:serial:///dev/ttyUSB0:57600)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args.url))
    except KeyboardInterrupt:
        print("\n結束監看")
        sys.exit(0)


if __name__ == "__main__":
    main()

"""drone-agent 進入點:連 PX4 → 訂閱遙測流 → 1 Hz MQTT 上報。

用法:
    # PX4 SITL(預設 offboard 埠 14540)+ 本機 mosquitto
    python -m drone_agent.main --drone-id dev-1

    # 實機(經序列埠)上報到雲端 broker
    python -m drone_agent.main --url serial:///dev/ttyUSB0:57600 \
        --mqtt-host broker.example.com --drone-id qs-0001

    # 同機多程序:共用另一程序已啟動的 mavsdk_server(不自行 spawn)
    python -m drone_agent.main --mavsdk-address localhost:50051 --drone-id dev-1
"""

import argparse
import asyncio
import logging
import sys

from mavsdk import System

from drone_agent.publisher import STALE_TIMEOUT_S, publish_loop
from drone_agent.state import WATCHERS, TelemetryState

logger = logging.getLogger("drone_agent")


def parse_mavsdk_address(value: str) -> tuple[str, int]:
    """解析 --mavsdk-address 的 host:port(供 argparse type= 使用)。"""
    host, sep, port = value.rpartition(":")
    if not sep or not host or not port.isdigit():
        raise argparse.ArgumentTypeError(f"格式須為 host:port,收到:{value!r}")
    return host, int(port)


async def run(args: argparse.Namespace) -> None:
    state = TelemetryState()
    if args.mavsdk_address is not None:
        # 連既有 mavsdk_server(不自行 spawn);飛控連線字串由該 server 決定,--url 不生效
        host, port = args.mavsdk_address
        drone = System(mavsdk_server_address=host, port=port)
        logger.info("連線既有 mavsdk_server:%s:%d(--url 由該 server 決定,不生效)", host, port)
        await drone.connect()
    else:
        drone = System()
        logger.info("連線中:%s", args.url)
        await drone.connect(system_address=args.url)

    async for conn in drone.core.connection_state():
        if conn.is_connected:
            logger.info("已連上飛行器")
            break

    # 全部訂閱協程 + 發佈迴圈並行;MQTT 斷線重連由 publish_loop 自理,
    # 任一 MAVSDK 訂閱異常結束則整體結束(交給 systemd 重啟,Phase 0 策略)
    await asyncio.gather(
        *(watch(drone, state) for watch in WATCHERS),
        publish_loop(
            state,
            args.mqtt_host,
            args.mqtt_port,
            args.drone_id,
            args.rate,
            args.stale_timeout,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="udpin://0.0.0.0:14540",
        help="MAVSDK 連線字串(預設 SITL:udpin://0.0.0.0:14540;"
        "序列埠範例:serial:///dev/ttyUSB0:57600)",
    )
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT broker 主機")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker 埠")
    parser.add_argument("--drone-id", required=True, help="機隊內唯一機身識別碼")
    parser.add_argument("--rate", type=float, default=1.0, help="上報頻率 Hz(預設 1)")
    parser.add_argument(
        "--stale-timeout",
        type=float,
        default=STALE_TIMEOUT_S,
        help=f"遙測斷流判定秒數,超過即暫停上報(預設 {STALE_TIMEOUT_S:.0f})",
    )
    parser.add_argument(
        "--mavsdk-address",
        type=parse_mavsdk_address,
        default=None,
        metavar="HOST:PORT",
        help="連既有 mavsdk_server(如 localhost:50051),不自行啟動;"
        "未給時自行 spawn(預設行為,佔 50051)。給此參數時 --url 不生效",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        logger.info("結束 drone-agent")
        sys.exit(0)


if __name__ == "__main__":
    main()

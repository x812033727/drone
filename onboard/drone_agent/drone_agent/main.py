"""drone-agent 進入點:連 PX4 → 訂閱遙測流 → 1 Hz MQTT 上報 + 雲端任務下行。

任務下行(--enable-cmd,預設開):訂閱 fleet/{drone_id}/cmd/mission,
收到 MissionPlan 後以子程序跑 mission_exec(共用本程序的 mavsdk_server),
細節與 Phase 0 安全豁免見 drone_agent/command.py 與 README。

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
import os
import sys
from collections import deque

from mavsdk import System

from drone_agent.cert_monitor import DEFAULT_WARN_DAYS, cert_monitor_loop
from drone_agent.command import DEFAULT_MISSION_TIMEOUT_S, command_loop
from drone_agent.log_uploader import DEFAULT_DOWNLOAD_TIMEOUT_S, LogUploader
from drone_agent.publisher import (
    DEFAULT_TELEMETRY_BUFFER_MAX,
    HEARTBEAT_INTERVAL_S,
    STALE_TIMEOUT_S,
    heartbeat_loop,
    publish_loop,
    telemetry_producer,
)
from drone_agent.state import WATCHERS, TelemetryState

logger = logging.getLogger("drone_agent")

#: MAVSDK Python 內嵌 mavsdk_server 的預設 gRPC 埠(System() 未指定時)
DEFAULT_MAVSDK_PORT = 50051


def parse_mavsdk_address(value: str) -> tuple[str, int]:
    """解析 --mavsdk-address 的 host:port(供 argparse type= 使用)。"""
    host, sep, port = value.rpartition(":")
    if not sep or not host or not port.isdigit():
        raise argparse.ArgumentTypeError(f"格式須為 host:port,收到:{value!r}")
    return host, int(port)


async def _fetch_firmware_version(drone: System) -> str:
    """最佳努力取飛控韌體版本(供心跳);info 尚未就緒/逾時則留空,不阻塞啟動。"""
    try:
        version = await asyncio.wait_for(drone.info.get_version(), timeout=5.0)
        return f"{version.flight_sw_major}.{version.flight_sw_minor}.{version.flight_sw_patch}"
    except Exception:
        logger.warning("取不到韌體版本(心跳 firmware_version 留空)")
        return ""


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

    firmware_version = await _fetch_firmware_version(drone)

    if args.log_svc_url:
        # S20 ULog 自動回收(選配,預設關):disarm 邊緣觸發下載+上傳,
        # 全程獨立 task 不阻塞遙測,細節見 log_uploader.py
        uploader = LogUploader(
            drone, args.drone_id, args.log_svc_url, args.log_download_timeout
        )
        state.disarm_callback = uploader.trigger
        logger.info("ULog 自動回收已啟用:disarm 後上傳至 %s", args.log_svc_url)

    # 遙測取樣(producer)與發佈(publish_loop)拆開,共用離線緩衝 buffer:
    # 斷線期間 producer 續取堆進 buffer,publish_loop 重連後 FIFO 補發(G24)
    telemetry_buffer: deque = deque()

    # 全部訂閱協程 + 取樣/發佈迴圈(+ cmd 訂閱)並行;MQTT 斷線重連由各迴圈自理,
    # 任一 MAVSDK 訂閱異常結束則整體結束(交給 systemd 重啟,Phase 0 策略)
    coros = [
        *(watch(drone, state) for watch in WATCHERS),
        telemetry_producer(
            state,
            telemetry_buffer,
            args.drone_id,
            args.telemetry_buffer_max,
            args.rate,
            args.stale_timeout,
        ),
        publish_loop(
            state,
            telemetry_buffer,
            args.mqtt_host,
            args.mqtt_port,
            args.drone_id,
            args.rate,
        ),
        heartbeat_loop(
            args.mqtt_host,
            args.mqtt_port,
            args.drone_id,
            firmware_version,
            args.heartbeat_interval,
        ),
    ]
    # 憑證到期/輪換偵測(G22):僅在有設裝置憑證(mTLS)時啟動;
    # Phase 0 明文(MQTT_TLS_CERT 未設)無憑證可監控,略過
    cert_path = os.environ.get("MQTT_TLS_CERT")
    if cert_path:
        coros.append(
            cert_monitor_loop(
                cert_path,
                args.mqtt_host,
                args.mqtt_port,
                args.drone_id,
                args.cert_warn_days,
            )
        )
    else:
        logger.info("未設 MQTT_TLS_CERT(明文模式),略過憑證到期監控")
    if args.enable_cmd:
        # mission_exec 子程序共用的 mavsdk_server 位址:agent 連既有 server 就透傳
        # 同一個;自行 spawn 時為內嵌 server 的 localhost:50051
        mavsdk_address = args.mavsdk_address or ("localhost", DEFAULT_MAVSDK_PORT)
        coros.append(
            command_loop(
                args.mqtt_host,
                args.mqtt_port,
                args.drone_id,
                mavsdk_address,
                timeout_s=args.cmd_timeout,
            )
        )
    await asyncio.gather(*coros)


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
        "--telemetry-buffer-max",
        type=int,
        default=int(os.environ.get("TELEMETRY_BUFFER_MAX", DEFAULT_TELEMETRY_BUFFER_MAX)),
        help="離線緩衝上限筆數(MQTT 斷線期間 store-and-forward,滿了丟最舊;"
        f"預設 {DEFAULT_TELEMETRY_BUFFER_MAX},env TELEMETRY_BUFFER_MAX 可覆寫)",
    )
    parser.add_argument(
        "--cert-warn-days",
        type=float,
        default=float(os.environ.get("CERT_EXPIRY_WARN_DAYS", DEFAULT_WARN_DAYS)),
        help="裝置憑證剩餘天數低於此值即告警(需設 MQTT_TLS_CERT;"
        f"預設 {DEFAULT_WARN_DAYS},env CERT_EXPIRY_WARN_DAYS 可覆寫)",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=HEARTBEAT_INTERVAL_S,
        help=f"裝置心跳發佈間隔秒數(fleet/{{id}}/heartbeat,預設 {HEARTBEAT_INTERVAL_S:.0f})",
    )
    parser.add_argument(
        "--mavsdk-address",
        type=parse_mavsdk_address,
        default=None,
        metavar="HOST:PORT",
        help="連既有 mavsdk_server(如 localhost:50051),不自行啟動;"
        "未給時自行 spawn(預設行為,佔 50051)。給此參數時 --url 不生效",
    )
    parser.add_argument(
        "--enable-cmd",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="訂閱 fleet/{drone_id}/cmd/mission 接受雲端任務派遣(預設開;"
        "關閉用 --no-enable-cmd)。Phase 0 安全豁免:anonymous broker = 內網"
        "任何人可派任務,僅限開發內網,見 docs/20-software/security.md §8",
    )
    parser.add_argument(
        "--cmd-timeout",
        type=float,
        default=DEFAULT_MISSION_TIMEOUT_S,
        help=f"任務子程序逾時秒數,超過即 kill 並補發 FAILED(預設 {DEFAULT_MISSION_TIMEOUT_S:.0f})",
    )
    parser.add_argument(
        "--log-svc-url",
        default=None,
        help="log-svc 基底 URL(如 http://localhost:8090):disarm 後自動下載最新 ULog "
        "並上傳(S20 閉環)。未給則整個功能停用(預設關,Phase 0 選配)",
    )
    parser.add_argument(
        "--log-download-timeout",
        type=float,
        default=DEFAULT_DOWNLOAD_TIMEOUT_S,
        help="ULog MAVLink 下載加總逾時秒數,逾時放棄本次回收"
        f"(預設 {DEFAULT_DOWNLOAD_TIMEOUT_S:.0f};實機大檔經數傳慢,視鏈路調大)",
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

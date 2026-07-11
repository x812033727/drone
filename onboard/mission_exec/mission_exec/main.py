"""mission_exec CLI:載入 JSON 任務檔 → 連 PX4 → 執行並回報進度。

用法:
    # PX4 SITL(預設 offboard 埠 14540,自動 spawn mavsdk_server)
    python -m mission_exec.main --mission missions/demo_square.json --drone-id dev-1

    # 進度事件同時上 MQTT(主題 fleet/{drone_id}/mission/progress,QoS 1)
    python -m mission_exec.main --mission missions/demo_square.json \
        --drone-id dev-1 --mqtt-host localhost

    # 連既有 mavsdk_server(例如與 drone_agent 同機併跑時顯式共用)
    python -m mission_exec.main --mission missions/demo_square.json \
        --drone-id dev-1 --mavsdk-address localhost:50051

依賴:pip install -r requirements.txt 以及 interfaces/proto/gen/python(drone-proto)。
"""

import argparse
import asyncio
import logging
import sys

from drone.v1 import mission_pb2
from google.protobuf import json_format
from mavsdk import System

from mission_exec.executor import (
    DEFAULT_HEALTH_TIMEOUT_S,
    DEFAULT_PROGRESS_STALL_S,
    MissionExecError,
    run_mission,
)
from mission_exec.plan import load_plan

_LOG = logging.getLogger(__name__)
_STATE_NAMES = mission_pb2.MissionProgress.State


def _print_progress(progress: mission_pb2.MissionProgress) -> None:
    state = _STATE_NAMES.Name(progress.state)
    print(
        f"[進度] mission={progress.mission_id} drone={progress.drone_id}"
        f" state={state} item={progress.current_item}/{progress.total_items}",
        flush=True,
    )


def _make_progress_cb(mqtt_client, drone_id: str):
    async def progress_cb(progress: mission_pb2.MissionProgress) -> None:
        _print_progress(progress)  # stdout 一定印
        if mqtt_client is None:
            return
        payload = json_format.MessageToJson(progress, indent=None)
        try:
            await mqtt_client.publish(
                f"fleet/{drone_id}/mission/progress", payload=payload, qos=1
            )
        except Exception:
            # 進度發布永不致命:broker 斷線等問題只記 WARNING,任務照常繼續。
            # (若在 except 區塊發 STATE_FAILED 時再拋例外,會吞掉原始例外。)
            _LOG.warning("MQTT 進度發布失敗(broker 斷線?),任務照常繼續", exc_info=True)

    return progress_cb


def _parse_server_address(value: str) -> tuple[str, int] | None:
    """解析 --mavsdk-address 的 host:port;空字串 = 不使用(spawn 內建 server)。"""
    if not value:
        return None
    host, sep, port = value.rpartition(":")
    if not sep or not host or not port.isdigit():
        raise ValueError(f"--mavsdk-address 格式錯誤:{value!r}(需 host:port,如 localhost:50051)")
    return host, int(port)


async def wait_connected(drone: System) -> None:
    """等待 core.connection_state 連上飛行器;串流先結束則 raise RuntimeError。

    公開複用點(tools/sitl_scenarios 亦 import 此函式);可被 asyncio.wait_for 包逾時。
    """
    async for state in drone.core.connection_state():
        if state.is_connected:
            return
    raise RuntimeError("連線串流結束仍未連上飛行器")


async def _connect(url: str, server_address: tuple[str, int] | None) -> System:
    if server_address is None:
        drone = System()
        print(f"連線中:{url}", flush=True)
    else:
        host, port = server_address
        drone = System(mavsdk_server_address=host, port=port)
        print(f"連線既有 mavsdk_server:{host}:{port}", flush=True)
    await drone.connect(system_address=url)
    await wait_connected(drone)
    print("已連上飛行器", flush=True)
    return drone


async def _run(args: argparse.Namespace) -> None:
    plan = load_plan(args.mission)
    print(f"已載入任務 {plan.mission_id}({len(plan.waypoints)} 個航點)", flush=True)
    drone = await _connect(args.url, args.mavsdk_server)

    async def _execute(progress_cb) -> None:
        await run_mission(
            drone,
            plan,
            args.drone_id,
            progress_cb,
            health_timeout_s=args.health_timeout,
            progress_stall_s=args.stall_timeout,
        )

    if args.mqtt_host:
        import aiomqtt

        async with aiomqtt.Client(args.mqtt_host, port=args.mqtt_port) as client:
            await _execute(_make_progress_cb(client, args.drone_id))
    else:
        await _execute(_make_progress_cb(None, args.drone_id))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission", required=True, help="任務檔路徑(MissionPlan proto3 JSON)")
    parser.add_argument(
        "--url",
        default="udpin://0.0.0.0:14540",
        help="MAVSDK 連線字串(預設 SITL:udpin://0.0.0.0:14540;"
        "序列埠範例:serial:///dev/ttyUSB0:57600)",
    )
    parser.add_argument(
        "--mavsdk-address",
        default="",
        help="既有 mavsdk_server 的 host:port(如 localhost:50051);"
        "未給則自動 spawn 內建 server(現行為)",
    )
    parser.add_argument("--mqtt-host", default=None, help="MQTT broker 主機(未給則只印 stdout)")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker 埠(預設 1883)")
    parser.add_argument("--drone-id", default="dev-1", help="機身識別碼(MQTT 主題用)")
    parser.add_argument(
        "--health-timeout",
        type=float,
        default=DEFAULT_HEALTH_TIMEOUT_S,
        help=f"等待 GPS/home 就緒逾時秒數(預設 {DEFAULT_HEALTH_TIMEOUT_S:g})",
    )
    parser.add_argument(
        "--stall-timeout",
        type=float,
        default=DEFAULT_PROGRESS_STALL_S,
        help="進度事件停滯逾時秒數:超過此時間完全無進度事件即判失敗"
        f"(預設 {DEFAULT_PROGRESS_STALL_S:g};針對「無事件」而非「未完成」)",
    )
    args = parser.parse_args()
    try:
        args.mavsdk_server = _parse_server_address(args.mavsdk_address)
    except ValueError as e:
        parser.error(str(e))
    try:
        asyncio.run(_run(args))
    except ValueError as e:
        print(f"任務檔錯誤:{e}", file=sys.stderr)
        sys.exit(2)
    except MissionExecError as e:
        print(f"{e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n中斷執行", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()

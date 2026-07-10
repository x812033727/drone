"""mission_exec CLI:載入 JSON 任務檔 → 連 PX4 → 執行並回報進度。

用法:
    # PX4 SITL(預設 offboard 埠 14540)
    python -m mission_exec.main --mission missions/demo_square.json --drone-id dev-1

    # 進度事件同時上 MQTT(主題 fleet/{drone_id}/mission/progress,QoS 1)
    python -m mission_exec.main --mission missions/demo_square.json \
        --drone-id dev-1 --mqtt-host localhost

依賴:pip install -r requirements.txt 以及 interfaces/proto/gen/python(drone-proto)。
"""

import argparse
import asyncio
import sys

from drone.v1 import mission_pb2
from google.protobuf import json_format
from mavsdk import System

from mission_exec.executor import MissionExecError, run_mission
from mission_exec.plan import load_plan

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
        if mqtt_client is not None:
            payload = json_format.MessageToJson(progress, indent=None)
            await mqtt_client.publish(
                f"fleet/{drone_id}/mission/progress", payload=payload, qos=1
            )

    return progress_cb


async def _connect(url: str) -> System:
    drone = System()
    print(f"連線中:{url}", flush=True)
    await drone.connect(system_address=url)
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("已連上飛行器", flush=True)
            return drone
    raise RuntimeError("連線串流結束仍未連上飛行器")


async def _run(args: argparse.Namespace) -> None:
    plan = load_plan(args.mission)
    print(f"已載入任務 {plan.mission_id}({len(plan.waypoints)} 個航點)", flush=True)
    drone = await _connect(args.url)

    if args.mqtt_host:
        import aiomqtt

        async with aiomqtt.Client(args.mqtt_host, port=args.mqtt_port) as client:
            await run_mission(drone, plan, args.drone_id, _make_progress_cb(client, args.drone_id))
    else:
        await run_mission(drone, plan, args.drone_id, _make_progress_cb(None, args.drone_id))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission", required=True, help="任務檔路徑(MissionPlan proto3 JSON)")
    parser.add_argument(
        "--url",
        default="udpin://0.0.0.0:14540",
        help="MAVSDK 連線字串(預設 SITL:udpin://0.0.0.0:14540;"
        "序列埠範例:serial:///dev/ttyUSB0:57600)",
    )
    parser.add_argument("--mqtt-host", default=None, help="MQTT broker 主機(未給則只印 stdout)")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker 埠(預設 1883)")
    parser.add_argument("--drone-id", default="dev-1", help="機身識別碼(MQTT 主題用)")
    args = parser.parse_args()
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

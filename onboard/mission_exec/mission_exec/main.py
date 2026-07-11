"""mission_exec CLI:載入 JSON 任務檔 → 連 PX4 → 執行並回報進度。

用法:
    # PX4 SITL(預設 offboard 埠 14540,自動 spawn mavsdk_server)
    python -m mission_exec.main --mission missions/demo_square.json --drone-id dev-1

    # 進度事件同時上 MQTT(主題 fleet/{drone_id}/mission/progress,QoS 1);
    # 同時訂閱 fleet/{drone_id}/cmd/mission_ctrl 接收 PAUSE/RESUME/ABORT
    # (S23;無 --mqtt-host 時控制通道自然停用)
    python -m mission_exec.main --mission missions/demo_square.json \
        --drone-id dev-1 --mqtt-host localhost

    # 斷點續飛:上傳後自航點 2 開始(搭配進度事件裡的 current_item 記錄斷點)
    python -m mission_exec.main --mission missions/demo_square.json \
        --drone-id dev-1 --resume 2

    # 連既有 mavsdk_server(例如與 drone_agent 同機併跑時顯式共用)
    python -m mission_exec.main --mission missions/demo_square.json \
        --drone-id dev-1 --mavsdk-address localhost:50051

依賴:pip install -r requirements.txt 以及 interfaces/proto/gen/python(drone-proto)。
"""

import argparse
import asyncio
import os
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


def _make_ctrl_listener(client, ctrl_topic: str, queue: "asyncio.Queue"):
    """回傳控制通道監聽 coroutine:訂閱訊息 → 解析 MissionCommand → 入佇列。

    壞 payload 只記 WARNING 後略過;串流中斷(broker 斷線)log 後結束——
    控制通道為 best-effort,永不中斷任務本體(與進度發布同語意)。
    mission_id / 命令合法性驗證在 executor(單一事實來源),此處只做 Parse 級把關。
    """

    async def listen() -> None:
        try:
            async for message in client.messages:
                if not message.topic.matches(ctrl_topic):
                    continue
                cmd = mission_pb2.MissionCommand()
                try:
                    json_format.Parse(bytes(message.payload), cmd)
                except json_format.ParseError:
                    _LOG.warning("忽略非法 mission_ctrl payload(非 MissionCommand JSON)",
                                 exc_info=True)
                    continue
                await queue.put(cmd)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOG.warning("mission_ctrl 訂閱中斷(broker 斷線?),控制通道停用,任務照常繼續",
                         exc_info=True)

    return listen


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

    async def _execute(progress_cb, ctrl_queue=None) -> None:
        await run_mission(
            drone,
            plan,
            args.drone_id,
            progress_cb,
            health_timeout_s=args.health_timeout,
            progress_stall_s=args.stall_timeout,
            ctrl_queue=ctrl_queue,
            resume_from=args.resume,
        )

    if args.mqtt_host:
        import aiomqtt

        async with aiomqtt.Client(args.mqtt_host, port=args.mqtt_port) as client:
            # 控制通道(S23):同一條 MQTT 連線訂 mission_ctrl,監聽任務餵佇列;
            # 無 --mqtt-host 時自然停用(ctrl_queue=None)
            ctrl_topic = f"fleet/{args.drone_id}/cmd/mission_ctrl"
            await client.subscribe(ctrl_topic, qos=1)
            print(f"控制通道已訂閱:{ctrl_topic}", flush=True)
            ctrl_queue: asyncio.Queue = asyncio.Queue()
            listener = asyncio.create_task(_make_ctrl_listener(client, ctrl_topic, ctrl_queue)())
            try:
                await _execute(_make_progress_cb(client, args.drone_id), ctrl_queue)
            finally:
                listener.cancel()
    else:
        await _execute(_make_progress_cb(None, args.drone_id))


def _hard_exit(code: int) -> None:
    """失敗路徑保證立即退出。

    2026-07-11 nightly 實錄:STATE_FAILED 已發、sys.exit(1) 已呼叫,但 mavsdk/grpc
    的非 daemon 背景執行緒拖住直譯器關閉,行程懸掛吃滿外層 timeout(exit 124)。
    成功路徑歷史上正常退出,僅失敗分支用 os._exit 硬退出(先 flush 輸出)。
    """
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


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
        "--resume",
        type=int,
        default=0,
        help="斷點續飛:上傳後自航點 N(0-based)開始執行"
        "(set_current_mission_item;預設 0 = 從頭)",
    )
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
    if args.resume < 0:
        parser.error(f"--resume 需為非負整數(收到 {args.resume})")
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
        _hard_exit(1)
    except KeyboardInterrupt:
        print("\n中斷執行", file=sys.stderr)
        _hard_exit(130)


if __name__ == "__main__":
    main()

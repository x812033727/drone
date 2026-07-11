"""雲端側任務派遣 CLI:把 MissionPlan JSON 發到 `fleet/{drone_id}/cmd/mission`。

用法:
    # 派遣並等結果(訂 progress 主題,印進度序列直到 COMPLETED/FAILED)
    python dispatch_mission.py --drone-id dev-1 \
        --mission ../onboard/mission_exec/missions/demo_square.json --wait

    # 只派遣不等(fire-and-forget)
    python dispatch_mission.py --drone-id dev-1 --mission plan.json \
        --mqtt-host broker.internal --mqtt-port 1883

結束碼:0 = COMPLETED(或未 --wait 時發布成功);1 = FAILED;2 = 任務檔錯誤;
3 = --wait 逾時。

安全註記(Phase 0 明列豁免,見 docs/20-software/security.md §8):
broker 為 anonymous、無 TLS/ACL——開發內網上任何人都能對任何機派任務,
本工具即以此前提設計,僅限開發內網使用;Phase 1 起 mTLS + ACL 才對外。

依賴:pip install -r requirements.txt 以及 interfaces/proto/gen/python(drone-proto)。
"""

import argparse
import asyncio
import sys
from pathlib import Path

import aiomqtt
from drone.v1 import mission_pb2
from google.protobuf import json_format

DEFAULT_WAIT_TIMEOUT_S = 600.0
_STATE = mission_pb2.MissionProgress.State


def load_plan(path: str | Path) -> tuple[mission_pb2.MissionPlan, str]:
    """載入任務檔,回傳 (MissionPlan, 原始 JSON 文字);問題 raise ValueError。

    派遣端只做 Parse 級把關 + mission_id 非空(語意驗證由機上 mission_exec
    把關);線上 payload 用原始檔案內容,不重新序列化。
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"無法讀取任務檔 {path}:{e}") from e
    plan = mission_pb2.MissionPlan()
    try:
        json_format.Parse(text, plan)
    except json_format.ParseError as e:
        raise ValueError(f"任務檔 {path} 不是合法的 MissionPlan JSON:{e}") from e
    if not plan.mission_id:
        raise ValueError("任務檔驗證失敗:mission_id 不可為空")
    return plan, text


def _print_progress(progress: mission_pb2.MissionProgress) -> None:
    state = _STATE.Name(progress.state)
    print(
        f"[進度] mission={progress.mission_id} drone={progress.drone_id}"
        f" state={state} item={progress.current_item}/{progress.total_items}",
        flush=True,
    )


async def _dispatch_and_wait(args: argparse.Namespace, plan_json: str, mission_id: str) -> int:
    topic = f"fleet/{args.drone_id}/cmd/mission"
    progress_topic = f"fleet/{args.drone_id}/mission/progress"
    async with aiomqtt.Client(hostname=args.mqtt_host, port=args.mqtt_port) as client:
        if args.wait:
            # 先訂 progress 再發派遣,避免漏掉 RECEIVED
            await client.subscribe(progress_topic, qos=1)
        await client.publish(topic, payload=plan_json, qos=1)
        print(f"已派遣任務 {mission_id} → {topic}", flush=True)
        if not args.wait:
            return 0
        async for message in client.messages:
            progress = mission_pb2.MissionProgress()
            try:
                json_format.Parse(bytes(message.payload), progress)
            except json_format.ParseError:
                continue  # 別的發布者的壞 payload,不干擾等待
            if progress.mission_id != mission_id:
                continue  # 只看本次派遣(互斥拒絕別的任務時會有他人的事件)
            _print_progress(progress)
            if progress.state == _STATE.STATE_COMPLETED:
                return 0
            if progress.state == _STATE.STATE_FAILED:
                return 1
    return 1  # 訂閱串流提前結束(broker 斷線)


async def _run(args: argparse.Namespace) -> int:
    plan, plan_json = load_plan(args.mission)
    print(f"已載入任務 {plan.mission_id}({len(plan.waypoints)} 個航點)", flush=True)
    try:
        return await asyncio.wait_for(
            _dispatch_and_wait(args, plan_json, plan.mission_id), timeout=args.timeout
        )
    except (asyncio.TimeoutError, TimeoutError):
        print(f"逾時:{args.timeout:g} 秒內未收到 COMPLETED/FAILED", file=sys.stderr)
        return 3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drone-id", required=True, help="目標機身識別碼(MQTT 主題用)")
    parser.add_argument("--mission", required=True, help="任務檔路徑(MissionPlan proto3 JSON)")
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT broker 主機")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker 埠(預設 1883)")
    parser.add_argument(
        "--wait",
        action="store_true",
        help="訂閱 progress 主題等待結果:印進度序列,COMPLETED 結束碼 0、FAILED 1",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_WAIT_TIMEOUT_S,
        help=f"--wait 等待逾時秒數(預設 {DEFAULT_WAIT_TIMEOUT_S:g};逾時結束碼 3)",
    )
    args = parser.parse_args()
    try:
        code = asyncio.run(_run(args))
    except ValueError as e:
        print(f"任務檔錯誤:{e}", file=sys.stderr)
        code = 2
    except aiomqtt.MqttError as e:
        print(f"MQTT 連線失敗:{e}", file=sys.stderr)
        code = 1
    except KeyboardInterrupt:
        print("\n中斷", file=sys.stderr)
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()

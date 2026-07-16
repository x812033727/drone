"""雲端側任務派遣 CLI:把 MissionPlan JSON 發到 `fleet/{drone_id}/cmd/mission`。

用法:
    # 派遣並等結果(訂 progress 主題,印進度序列直到 COMPLETED/FAILED)
    python dispatch_mission.py --drone-id dev-1 \
        --mission ../onboard/mission_exec/missions/demo_square.json --wait

    # 只派遣不等(fire-and-forget)
    python dispatch_mission.py --drone-id dev-1 --mission plan.json \
        --mqtt-host broker.internal --mqtt-port 1883

    # 直接派遣 QGC .plan(經 flight_ops.qgc_plan 轉 MissionPlan;需 --mission-id)
    python dispatch_mission.py --drone-id dev-1 \
        --plan ../gcs/qgc-profiles/plans/survey-rect-demo.plan \
        --mission-id survey-demo-1 --wait

    # 任務控制(S23):對執行中任務發 PAUSE/RESUME/ABORT
    # (MissionCommand → fleet/{drone_id}/cmd/mission_ctrl;fire-and-forget,
    #  結果看 progress 主題:PAUSE → STATE_PAUSED、ABORT → RTL + STATE_FAILED)
    python dispatch_mission.py --drone-id dev-1 --ctrl pause --mission-id demo-square-v1

結束碼:0 = COMPLETED(或未 --wait / --ctrl 模式時發布成功);1 = FAILED;
2 = 任務檔/參數錯誤;3 = --wait 逾時;4 = MQTT 連線失敗/訂閱串流提前結束
(結果未知,非任務失敗)。

終態語意:機上側為 at-least-once,同一任務的終態事件可能重複;本工具以
**首個終態為準**(收到即退出)。等待逾時預設 960 秒,刻意大於 agent 的任務
子程序逾時(--cmd-timeout 預設 900 秒),確保 agent 逾時 kill 後補發的
FAILED 能在本工具退出前收到。

安全註記(Phase 0 明列豁免,見 docs/20-software/security.md §8):
broker 為 anonymous、無 TLS/ACL——開發內網上任何人都能對任何機派任務,
本工具即以此前提設計,僅限開發內網使用;Phase 1 起 mTLS + ACL 才對外。

依賴:pip install -r requirements.txt 以及 interfaces/proto/gen/python(drone-proto)。
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import aiomqtt
from drone.v1 import mission_pb2
from google.protobuf import json_format

#: --wait 逾時預設:> agent 任務子程序逾時 900 秒(等得到逾時 kill 後補發的 FAILED)
DEFAULT_WAIT_TIMEOUT_S = 960.0
_STATE = mission_pb2.MissionProgress.State
#: --ctrl 子模式 → MissionCommand.Command 映射
CTRL_COMMANDS = {
    "pause": mission_pb2.MissionCommand.COMMAND_PAUSE,
    "resume": mission_pb2.MissionCommand.COMMAND_RESUME,
    "abort": mission_pb2.MissionCommand.COMMAND_ABORT,
}


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


def load_qgc_plan(path: str | Path, mission_id: str) -> tuple[mission_pb2.MissionPlan, str]:
    """QGC .plan → MissionPlan(經 flight_ops.qgc_plan 轉換,再走 proto Parse 驗證)。"""
    from flight_ops.qgc_plan import to_mission_plan  # 延遲匯入:僅 --plan 模式需要

    plan_dict = to_mission_plan(path, mission_id)
    text = json.dumps(plan_dict, ensure_ascii=False)
    plan = mission_pb2.MissionPlan()
    json_format.Parse(text, plan)  # 轉換器輸出必須過契約 Parse(壞了直接炸)
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
    return 4  # 訂閱串流提前結束(broker 斷線):結果未知,不可與 FAILED(1)混淆


async def _send_ctrl(args: argparse.Namespace, mission_id: str) -> int:
    """發 MissionCommand 到 ctrl 主題(fire-and-forget;成敗看 progress 主題)。"""
    topic = f"fleet/{args.drone_id}/cmd/mission_ctrl"
    cmd = mission_pb2.MissionCommand(
        mission_id=mission_id,
        command=CTRL_COMMANDS[args.ctrl],
        unix_time_ms=int(time.time() * 1000),
    )
    payload = json_format.MessageToJson(cmd, indent=None)
    async with aiomqtt.Client(hostname=args.mqtt_host, port=args.mqtt_port) as client:
        await client.publish(topic, payload=payload, qos=1)
    print(f"已發控制命令 {args.ctrl.upper()}(mission={mission_id})→ {topic}", flush=True)
    return 0


async def _run(args: argparse.Namespace) -> int:
    if args.ctrl:
        mission_id = args.mission_id
        if not mission_id:
            plan, _ = load_plan(args.mission)
            mission_id = plan.mission_id
        return await _send_ctrl(args, mission_id)
    if args.plan:
        plan, plan_json = load_qgc_plan(args.plan, args.mission_id)
    else:
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
    parser.add_argument(
        "--mission",
        default=None,
        help="任務檔路徑(MissionPlan proto3 JSON);派遣模式必填,"
        "--ctrl 模式可代替 --mission-id(取檔內 missionId)",
    )
    parser.add_argument(
        "--plan",
        default=None,
        help="QGC .plan 檔路徑(自動轉 MissionPlan;與 --mission 互斥,需 --mission-id)",
    )
    parser.add_argument(
        "--ctrl",
        choices=sorted(CTRL_COMMANDS),
        default=None,
        help="任務控制子模式:對執行中任務發 PAUSE/RESUME/ABORT"
        "(MissionCommand → fleet/{drone_id}/cmd/mission_ctrl,fire-and-forget)",
    )
    parser.add_argument(
        "--mission-id",
        default=None,
        help="--ctrl 模式的目標 mission_id(未給則自 --mission 檔讀取)",
    )
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
        help=f"--wait 等待逾時秒數(預設 {DEFAULT_WAIT_TIMEOUT_S:g},"
        "> agent --cmd-timeout 900;逾時結束碼 3)",
    )
    args = parser.parse_args()
    if args.ctrl:
        if not args.mission_id and not args.mission:
            parser.error("--ctrl 模式需要 --mission-id 或 --mission(取檔內 missionId)")
        if args.wait:
            parser.error("--ctrl 模式不支援 --wait(結果請看 progress 主題)")
    elif args.plan:
        if args.mission:
            parser.error("--plan 與 --mission 互斥")
        if not args.mission_id:
            parser.error("--plan 模式需要 --mission-id(雲端派遣語意:識別碼由派遣端產生)")
    elif not args.mission:
        parser.error("派遣模式需要 --mission 或 --plan")
    try:
        code = asyncio.run(_run(args))
    except ValueError as e:
        print(f"任務檔錯誤:{e}", file=sys.stderr)
        code = 2
    except aiomqtt.MqttError as e:
        print(f"MQTT 連線失敗:{e}", file=sys.stderr)
        code = 4  # 連線異常 ≠ 任務 FAILED(1):結果未知,由呼叫端決定重試/查證
    except KeyboardInterrupt:
        print("\n中斷", file=sys.stderr)
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()

"""雲端任務下行:訂閱 `fleet/{drone_id}/cmd/mission`,以子程序跑 mission_exec。

安全註記(對齊 docs/20-software/security.md §8 分階段落地表):
Phase 0 為**明列豁免**——anonymous MQTT、無 TLS/ACL,即「開發內網上任何人都能
對任何機派任務」;僅限開發內網部署,Phase 1 起 mTLS + 裝置憑證 + 主題 ACL
才對外。本模組的把關只防呆、不防敵:

- 訂閱主題寫死為自身 `fleet/{drone_id}/cmd/mission`(不收別機的指令);
- payload 需為合法 MissionPlan proto3 JSON 且 mission_id 非空(Parse 級把關;
  語意驗證由 mission_exec 載入任務檔時自行執行,agent 不重複實作);
- **單一任務互斥**:已有任務子程序存活時拒絕新任務,發 STATE_FAILED 事件
  (Phase 0 不做佇列)。

執行面:agent 本體維持唯讀遙測,不對 PX4 發任何指令;任務指令一律由
mission_exec 子程序轉譯下發(對齊 architecture.md §2 安全邊界)。agent 已
spawn mavsdk_server(佔 14540 與 gRPC 50051),故子程序必以
`--mavsdk-address` 顯式共用同一 server,絕不能讓 mission_exec 自行 spawn
(會搶飛控埠;這正是 mission_exec 支援該參數的原因)。

純函式(should_accept / build_cmd / parse_plan / failed_progress_json)與
I/O 分離,單測不需 SITL/MQTT。
"""

import asyncio
import logging
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiomqtt
from drone.v1 import mission_pb2
from google.protobuf import json_format

logger = logging.getLogger(__name__)

RECONNECT_DELAY_S = 3.0
#: 任務子程序逾時(秒):超過即 kill 並補發 STATE_FAILED
DEFAULT_MISSION_TIMEOUT_S = 900.0
#: monorepo 內 mission_exec 專案目錄(子程序的 cwd,讓 `-m mission_exec.main` 可解析)
MISSION_EXEC_DIR = Path(__file__).resolve().parents[2] / "mission_exec"

#: 補發 STATE_FAILED 的 async 回呼(引數:mission_id);發布失敗永不致命
FailedPublisher = Callable[[str], Awaitable[None]]


def should_accept(running: bool) -> bool:
    """單一任務互斥:已有任務子程序存活即拒絕(Phase 0 不做佇列)。"""
    return not running


def parse_plan(payload: bytes | str) -> mission_pb2.MissionPlan:
    """Parse 級把關:合法 MissionPlan proto3 JSON 且 mission_id 非空。

    語意驗證(waypoints 非空、經緯度範圍)不在此重複——mission_exec 載入
    任務檔時自會執行(單一事實來源在 mission_exec.plan)。
    任何問題 raise ValueError(中文訊息)。
    """
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(f"cmd payload 不是 UTF-8:{e}") from e
    plan = mission_pb2.MissionPlan()
    try:
        json_format.Parse(payload, plan)
    except json_format.ParseError as e:
        raise ValueError(f"cmd payload 不是合法的 MissionPlan JSON:{e}") from e
    if not plan.mission_id:
        raise ValueError("cmd payload 驗證失敗:mission_id 不可為空")
    return plan


def build_cmd(
    mission_file: str | Path,
    mavsdk_address: tuple[str, int],
    mqtt_host: str,
    mqtt_port: int,
    drone_id: str,
) -> list[str]:
    """組 mission_exec 子程序指令列(以 cwd=MISSION_EXEC_DIR 執行)。

    `--mavsdk-address` 必給:顯式共用 agent 已 spawn 的 mavsdk_server,
    避免子程序自行 spawn 搶飛控埠。`--mqtt-*` / `--drone-id` 透傳,
    讓進度事件由 mission_exec 直接發 `fleet/{drone_id}/mission/progress`。
    """
    host, port = mavsdk_address
    return [
        sys.executable,
        "-m",
        "mission_exec.main",
        "--mission",
        str(mission_file),
        "--mavsdk-address",
        f"{host}:{port}",
        "--mqtt-host",
        mqtt_host,
        "--mqtt-port",
        str(mqtt_port),
        "--drone-id",
        drone_id,
    ]


def failed_progress_json(mission_id: str, drone_id: str, unix_time_ms: int) -> str:
    """組 agent 端 STATE_FAILED 進度事件(拒絕/逾時/驗證未過等,mission_exec 不在場)。"""
    msg = mission_pb2.MissionProgress(
        mission_id=mission_id,
        drone_id=drone_id,
        state=mission_pb2.MissionProgress.STATE_FAILED,
        unix_time_ms=unix_time_ms,
    )
    return json_format.MessageToJson(msg, indent=None)


class MissionRunner:
    """任務子程序生命週期:啟動、輸出收進 log、逾時 kill、結束回收。

    同一時間至多一個子程序(互斥由 command_loop 以 `running` 把關)。
    子程序結束碼語意:0 = 完成;1 = mission_exec 已自行發過 STATE_FAILED;
    其餘(驗證錯 2、逾時 kill、訊號終止)mission_exec 沒機會發事件,
    由 on_failed 回呼補發(best-effort,失敗只記 log)。
    """

    def __init__(
        self,
        timeout_s: float = DEFAULT_MISSION_TIMEOUT_S,
        on_failed: FailedPublisher | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self._on_failed = on_failed
        self._proc: asyncio.subprocess.Process | None = None
        self._reaper: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self, cmd: list[str], mission_id: str, mission_file: Path) -> None:
        """啟動子程序並掛回收任務(呼叫前需以 running 確認互斥)。"""
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=MISSION_EXEC_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info("任務 %s 子程序已啟動(pid=%d):%s", mission_id, self._proc.pid, " ".join(cmd))
        self._reaper = asyncio.create_task(self._reap(self._proc, mission_id, mission_file))

    async def _reap(
        self, proc: asyncio.subprocess.Process, mission_id: str, mission_file: Path
    ) -> None:
        """收攏 stdout/stderr 進 log、逾時 kill、記錄結束碼、清暫存檔。"""
        timed_out = False
        pump = [
            asyncio.create_task(_pump(proc.stdout, logging.INFO, mission_id)),
            asyncio.create_task(_pump(proc.stderr, logging.WARNING, mission_id)),
        ]
        try:
            try:
                await asyncio.wait_for(proc.wait(), timeout=self.timeout_s)
            except (asyncio.TimeoutError, TimeoutError):
                timed_out = True
                logger.error("任務 %s 逾時(%.0f 秒),kill 子程序", mission_id, self.timeout_s)
                proc.kill()
                await proc.wait()
            await asyncio.gather(*pump)
        finally:
            mission_file.unlink(missing_ok=True)
        rc = proc.returncode
        if rc == 0:
            logger.info("任務 %s 子程序正常結束(exit=0)", mission_id)
            return
        logger.error(
            "任務 %s 子程序失敗(exit=%s%s)", mission_id, rc, ",逾時 kill" if timed_out else ""
        )
        if rc != 1 and self._on_failed is not None:
            try:
                await self._on_failed(mission_id)
            except Exception:
                logger.warning(
                    "任務 %s 補發 STATE_FAILED 失敗(broker 斷線?)", mission_id, exc_info=True
                )


async def _pump(stream: asyncio.StreamReader | None, level: int, mission_id: str) -> None:
    """把子程序輸出逐行收進 agent log。"""
    if stream is None:
        return
    async for raw in stream:
        line = raw.decode("utf-8", errors="replace").rstrip()
        if line:
            logger.log(level, "[mission_exec %s] %s", mission_id, line)


async def command_loop(
    mqtt_host: str,
    mqtt_port: int,
    drone_id: str,
    mavsdk_address: tuple[str, int],
    timeout_s: float = DEFAULT_MISSION_TIMEOUT_S,
) -> None:
    """訂閱 `fleet/{drone_id}/cmd/mission`(QoS 1),收任務、派 mission_exec 子程序。

    MQTT 斷線自動重連(重連期間到達的指令由 broker QoS 1 補投或丟棄,
    Phase 0 不另做補收)。拒絕事件走訂閱連線;子程序異常結束的補發事件
    由回收任務另開短連線(best-effort)。
    """
    topic = f"fleet/{drone_id}/cmd/mission"
    progress_topic = f"fleet/{drone_id}/mission/progress"

    async def publish_failed(mission_id: str) -> None:
        """另開短連線補發 STATE_FAILED(訂閱連線可能已斷/已換代)。"""
        payload = failed_progress_json(mission_id, drone_id, int(time.time() * 1000))
        async with aiomqtt.Client(hostname=mqtt_host, port=mqtt_port) as client:
            await client.publish(progress_topic, payload=payload, qos=1)

    runner = MissionRunner(timeout_s=timeout_s, on_failed=publish_failed)

    while True:
        try:
            async with aiomqtt.Client(hostname=mqtt_host, port=mqtt_port) as client:
                await client.subscribe(topic, qos=1)
                logger.info(
                    "cmd 已訂閱 %s(Phase 0 內網豁免:anonymous broker,見 security.md §8)", topic
                )
                async for message in client.messages:
                    payload = bytes(message.payload)
                    try:
                        plan = parse_plan(payload)
                    except ValueError as e:
                        # Parse 失敗多半拿不到可信 mission_id,無從對應事件,只記 log
                        logger.error("拒收 cmd(payload 驗證失敗):%s", e)
                        continue
                    if not should_accept(runner.running):
                        logger.warning(
                            "拒收任務 %s:已有任務執行中(Phase 0 單一任務互斥,不做佇列)",
                            plan.mission_id,
                        )
                        await client.publish(
                            progress_topic,
                            payload=failed_progress_json(
                                plan.mission_id, drone_id, int(time.time() * 1000)
                            ),
                            qos=1,
                        )
                        continue
                    with tempfile.NamedTemporaryFile(
                        mode="wb", suffix=".json", prefix="mission_", delete=False
                    ) as f:
                        f.write(payload)
                        mission_file = Path(f.name)
                    cmd = build_cmd(mission_file, mavsdk_address, mqtt_host, mqtt_port, drone_id)
                    await runner.start(cmd, plan.mission_id, mission_file)
        except aiomqtt.MqttError as exc:
            logger.warning("cmd MQTT 斷線:%s;%.0f 秒後重連", exc, RECONNECT_DELAY_S)
            await asyncio.sleep(RECONNECT_DELAY_S)

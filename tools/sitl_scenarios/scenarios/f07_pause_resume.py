"""F07 任務中斷續飛(飛行中 PAUSE → 進度凍結 → RESUME → 完成)SITL 回歸場景。

對應架次:flight-test-plan F07「任務中斷續飛」的 SITL 預跑。

與試飛計畫寫法的差異(誠實註記):
  計畫寫「操手切 Position 暫停 → 重入 Mission」——SITL 無實體 RC,改用 S23 的
  MQTT 任務控制通道作代理:`fleet/{id}/cmd/mission_ctrl` 發 COMMAND_PAUSE
  (機上 pause_mission → Hold 懸停)/ COMMAND_RESUME(start_mission 自暫停點
  續跑);驗的是「中斷後自斷點續飛、不重頭」的任務層行為,與 RC 切模式殊途
  同歸。「續飛點誤差 ≤ 5 m」屬實機 ULog 量測項,SITL 以「RESUME 後首個
  IN_PROGRESS 的 current_item ≥ 暫停斷點」承載「不重頭」語義。

執行方式(與 S23 e2e 同構,收斂進場景內):
  1. 自帶一個高位埠 mosquitto 容器(名稱/埠含 PID,獨特不相撞;跑完必清)。
  2. 以子行程跑 `python -m mission_exec.main --mqtt-host …`(f05 縮小版網格:
     80×40 m、行距 40、25 m 高、5 m/s,4 航點,rtl_after_last=True;任務檔為
     臨時檔)。本場景「不」自行連 MAVSDK——SITL 的 14540 只能有一個監聽者,
     由子行程獨占;所有觀測走 MQTT 進度事件。子行程會 spawn mavsdk_server
     (gRPC 預設 50051),本機並行他用時注意相撞。
  3. 網格中心用映像固定家點(47.397742, 8.545594;無 MAVSDK 連線可查 home)。

通過準則:
  1. 飛行中(IN_PROGRESS current_item ≥ 1)發 PAUSE → 30 s 內 STATE_PAUSED
  2. 暫停後進度凍結 ≥ 8 s(無 current_item 推進、無 COMPLETED)
  3. RESUME → 30 s 內回 STATE_IN_PROGRESS,且首個 item ≥ 暫停斷點(不重頭)
  4. STATE_COMPLETED 且子行程 exit code 0
"""

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import aiomqtt
from drone.v1 import mission_pb2
from google.protobuf import json_format
from mission_exec.patterns import survey_grid

from sitl_scenarios.checks import progress_frozen
from sitl_scenarios.runner import (
    ScenarioConfig,
    ScenarioError,
    ScenarioResult,
    logline,
    make_clock,
)

NAME = "f07"
TITLE = "F07 任務中斷續飛(飛行中 MQTT PAUSE → 凍結 ≥8 s → RESUME → 完成)"

#: jonasvautherin/px4-gazebo-headless 映像固定家點(demo_square 同源;
#: 本場景無 MAVSDK 連線,無法動態查 home)
SITL_HOME = (47.397742, 8.545594)
MISSION_ID = "f07-pause-resume"
DRONE_ID = "f07-sitl"
GRID_W_M, GRID_H_M, SPACING_M = 80.0, 40.0, 40.0  # f05 縮小版:2 行 4 航點
ALT_M, SPEED_MS = 25.0, 5.0
FREEZE_WINDOW_S = 8.0  # 通過準則:凍結 ≥ 8 s
PAUSE_ACK_TIMEOUT_S = 30.0
COMPLETE_TIMEOUT_S = 300.0

Event = tuple[float, str, int]  # (t, state 名, current_item)


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], check=check, capture_output=True, text=True, timeout=60
    )


def _start_mosquitto(name: str, port: int) -> None:
    """啟動專屬 mosquitto 容器(高位埠、匿名連線;映像自帶 no-auth 設定檔)。"""
    try:
        _docker(
            "run", "--rm", "-d", "--name", name, "-p", f"{port}:1883",
            "eclipse-mosquitto:2", "mosquitto", "-c", "/mosquitto-no-auth.conf",
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        detail = e.stderr if isinstance(e, subprocess.CalledProcessError) else str(e)
        raise ScenarioError(f"mosquitto 容器啟動失敗:{detail}") from e


async def _wait_broker(port: int, timeout_s: float) -> None:
    """等待 broker 可完成 MQTT CONNECT(拋棄式連線重試)。

    不可只探 TCP 埠:docker-proxy 在 mosquitto 尚未監聽前就 accept,
    TCP 通了但 CONNACK 不會來(實跑踩過,連線逾時)。
    """
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            async with aiomqtt.Client(hostname="127.0.0.1", port=port, timeout=3):
                return
        except aiomqtt.MqttError as e:
            if time.monotonic() >= deadline:
                raise ScenarioError(
                    f"mosquitto 127.0.0.1:{port} 於 {timeout_s:g} s 內未就緒:{e}"
                ) from e
            await asyncio.sleep(0.5)


async def _listen(client: aiomqtt.Client, events: list[Event], clock) -> None:
    """進度事件監聽:Parse MissionProgress 入列(壞 payload 略過)。"""
    async for message in client.messages:
        p = mission_pb2.MissionProgress()
        try:
            json_format.Parse(bytes(message.payload), p)
        except json_format.ParseError:
            continue
        state = mission_pb2.MissionProgress.State.Name(p.state)
        events.append((clock(), state, p.current_item))
        logline(clock(), f"進度事件 {state} item={p.current_item}/{p.total_items}")


async def _wait_event(events: list[Event], pred, timeout_s: float) -> Event | None:
    """輪詢等待首個滿足 pred 的事件;逾時回傳 None。"""
    deadline = time.monotonic() + timeout_s
    seen = 0
    while time.monotonic() < deadline:
        while seen < len(events):
            ev = events[seen]
            seen += 1
            if pred(ev):
                return ev
        await asyncio.sleep(0.2)
    return None


async def _publish_ctrl(client: aiomqtt.Client, command: int) -> None:
    cmd = mission_pb2.MissionCommand(
        mission_id=MISSION_ID, command=command, unix_time_ms=int(time.time() * 1000)
    )
    await client.publish(
        f"fleet/{DRONE_ID}/cmd/mission_ctrl",
        payload=json_format.MessageToJson(cmd, indent=None),
        qos=1,
    )


async def run(cfg: ScenarioConfig) -> ScenarioResult:
    clock = make_clock()
    result = ScenarioResult(NAME)

    mosq_name = f"f07-mosq-{os.getpid()}"
    mosq_port = 41000 + os.getpid() % 1000  # 高位埠,含 PID 避免相撞

    plan = survey_grid(
        *SITL_HOME, GRID_W_M, GRID_H_M, SPACING_M, ALT_M, SPEED_MS, mission_id=MISSION_ID
    )
    plan.rtl_after_last = True
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", prefix="f07-mission-", delete=False, encoding="utf-8"
    ) as f:
        f.write(json_format.MessageToJson(plan))
        mission_file = Path(f.name)

    proc: asyncio.subprocess.Process | None = None
    listener: asyncio.Task | None = None
    events: list[Event] = []
    try:
        _start_mosquitto(mosq_name, mosq_port)
        await _wait_broker(mosq_port, 30.0)
        logline(clock(), f"mosquitto 就緒:{mosq_name} @ 127.0.0.1:{mosq_port}")

        async with aiomqtt.Client(hostname="127.0.0.1", port=mosq_port) as client:
            await client.subscribe(f"fleet/{DRONE_ID}/mission/progress", qos=1)
            listener = asyncio.create_task(_listen(client, events, clock))

            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "mission_exec.main",
                "--mission", str(mission_file), "--drone-id", DRONE_ID,
                "--url", cfg.url, "--mqtt-host", "127.0.0.1", "--mqtt-port", str(mosq_port),
            )
            logline(clock(), f"mission_exec 子行程已啟動(pid={proc.pid},4 航點縮小網格)")

            # 1. 等飛行中(current_item ≥ 1)再暫停;FAILED 直接快速失敗
            flying = await _wait_event(
                events,
                lambda ev: ev[1] == "STATE_FAILED"
                or (ev[1] == "STATE_IN_PROGRESS" and ev[2] >= 1),
                240.0,
            )
            if flying is None:
                raise ScenarioError("240 s 內未見 IN_PROGRESS item≥1(任務未起飛或未推進)")
            if flying[1] == "STATE_FAILED":
                raise ScenarioError("任務在暫停前即 STATE_FAILED(見子行程輸出)")

            logline(clock(), f"飛行中 item={flying[2]},發 COMMAND_PAUSE")
            await _publish_ctrl(client, mission_pb2.MissionCommand.COMMAND_PAUSE)
            paused = await _wait_event(
                events, lambda ev: ev[1] == "STATE_PAUSED", PAUSE_ACK_TIMEOUT_S
            )
            result.add(
                f"飛行中 PAUSE → {PAUSE_ACK_TIMEOUT_S:g} s 內 STATE_PAUSED",
                paused is not None,
                f"t={paused[0]:.1f}s 斷點 item={paused[2]}" if paused else "未觀測到 PAUSED",
            )
            if paused is None:
                raise ScenarioError("PAUSE 未生效,無從繼續(後續斷言全數不成立)")
            t_paused, _, item_paused = paused

            # 2. 凍結觀察窗:多留 2 s 緩衝,凍結判定嚴格取 [t_paused, t_paused+8]
            await asyncio.sleep(FREEZE_WINDOW_S + 2.0)
            in_prog = [(t, i) for t, s, i in events if s == "STATE_IN_PROGRESS"]
            frozen = progress_frozen(
                in_prog, t_paused, t_paused + FREEZE_WINDOW_S, item_paused
            ) and not any(
                s == "STATE_COMPLETED" and t <= t_paused + FREEZE_WINDOW_S
                for t, s, _ in events
            )
            result.add(
                f"暫停後進度凍結 ≥ {FREEZE_WINDOW_S:g} s(無推進、無完成)",
                frozen,
                f"斷點 item={item_paused},窗內 IN_PROGRESS="
                f"{[(round(t, 1), i) for t, i in in_prog if t >= t_paused]}",
            )

            # 3. RESUME:回 IN_PROGRESS 且不重頭
            t_resume = clock()
            logline(t_resume, "發 COMMAND_RESUME")
            await _publish_ctrl(client, mission_pb2.MissionCommand.COMMAND_RESUME)
            resumed = await _wait_event(
                events,
                lambda ev: ev[1] == "STATE_IN_PROGRESS" and ev[0] >= t_resume,
                PAUSE_ACK_TIMEOUT_S,
            )
            result.add(
                "RESUME → 回 STATE_IN_PROGRESS 且自斷點續飛(不重頭)",
                resumed is not None and resumed[2] >= item_paused,
                f"續飛 item={resumed[2]}(斷點 {item_paused})" if resumed else "未觀測到續飛",
            )

            # 4. 完成 + 子行程結束碼(FAILED 也結束等待,誠實記錄)
            terminal = await _wait_event(
                events,
                lambda ev: ev[1] in ("STATE_COMPLETED", "STATE_FAILED"),
                COMPLETE_TIMEOUT_S,
            )
            completed = terminal if terminal and terminal[1] == "STATE_COMPLETED" else None
            result.add(
                "任務 STATE_COMPLETED",
                completed is not None,
                f"t={completed[0]:.1f}s"
                if completed
                else (
                    f"終態={terminal[1]}" if terminal else f"{COMPLETE_TIMEOUT_S:g} s 內未完成"
                ),
            )
            try:
                rc = await asyncio.wait_for(proc.wait(), timeout=60)
            except (asyncio.TimeoutError, TimeoutError):
                rc = None
            result.add(
                "mission_exec 子行程 exit code 0",
                rc == 0,
                f"rc={rc}" + ("(60 s 內未退出)" if rc is None else ""),
            )
    finally:
        if listener is not None:
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)
        if proc is not None and proc.returncode is None:
            proc.kill()
            await asyncio.gather(proc.wait(), return_exceptions=True)
        _docker("rm", "-f", mosq_name, check=False)
        mission_file.unlink(missing_ok=True)

    # 無 MAVSDK 遙測(14540 由子行程獨占);以進度狀態轉換序列代模式序列輸出
    seen_state = None
    for t, s, _ in events:
        if s != seen_state:
            result.mode_events.append((t, s))
            seen_state = s
    return result

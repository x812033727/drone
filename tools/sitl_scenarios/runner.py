"""共用骨架:連 SITL、方形 demo 任務、遙測記錄、PASS/FAIL 結果輸出。

複用來源(S11 起 mission_exec 為可安裝套件 `pip install -e onboard/mission_exec`,
直接 import,不再抄碼;本檔僅保留場景專屬邏輯與錯誤域轉換):
- wait_connected():mission_exec.main.wait_connected(RuntimeError → ScenarioError)
- wait_position_ready():mission_exec.executor.wait_position_ready(同上轉換)
- SQUARE_CORNERS:mission_exec.plan.load_plan 載自 onboard/mission_exec/missions/
  demo_square.json(editable 安裝下由套件位置反解 repo 內路徑)
- square_mission_items():組 drone.v1 Waypoint 後走 mission_exec.translate
  .to_mission_items(speed<=0 → NaN、不停點 fly-through、相機/雲台欄位 NaN/NONE)
"""

import asyncio
import math
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import mission_exec
from drone.v1 import mission_pb2
from mavsdk import System
from mavsdk.mission import MissionItem, MissionPlan
from mission_exec.executor import wait_position_ready as _me_wait_position_ready
from mission_exec.main import wait_connected as _me_wait_connected
from mission_exec.plan import load_plan
from mission_exec.translate import to_mission_items

#: 示範任務檔(mission_exec 套件旁的 missions/;需 editable 安裝 = repo 樹在場)
_DEMO_SQUARE_JSON = Path(mission_exec.__file__).resolve().parents[1] / "missions/demo_square.json"

#: demo_square.json 的四個角點(SITL Zurich 家點附近,邊長約 100 m);
#: 單一事實來源在任務檔,經 load_plan 載入(格式/範圍驗證一併生效)
SQUARE_CORNERS = [(wp.lat_deg, wp.lon_deg) for wp in load_plan(_DEMO_SQUARE_JSON).waypoints]

#: 容器內 PX4 build 工具目錄(px4-param / px4-listener;F10 docker exec 用)
PX4_BIN_DIR = "/root/Firmware/build/px4_sitl_default/bin"


class ScenarioError(RuntimeError):
    """場景前置條件不滿足或執行環境錯誤(非行為斷言失敗)。"""


@dataclass
class ScenarioConfig:
    """CLI 傳入的場景執行組態。"""

    url: str = "udpin://0.0.0.0:14540"
    container: str | None = None  # SITL 容器名(F10 docker exec、F09 取源 IP 需要)
    source_ip: str | None = None  # F09 被動觀測的源 IP 過濾(不給則由 container 推導)
    grpc_port: int = 50600  # mavsdk_server gRPC 埠(避免多場景/多 agent 相撞)


@dataclass
class Check:
    label: str
    ok: bool
    detail: str = ""


@dataclass
class ScenarioResult:
    """單一場景的執行結果:逐項檢查 + 模式轉換序列。"""

    name: str
    checks: list[Check] = field(default_factory=list)
    mode_events: list[tuple[float, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    def add(self, label: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(label, ok, detail))


def print_result(result: ScenarioResult) -> None:
    """輸出逐項檢查、模式序列與 CI 可 grep 的結論行(RESULT: PASS/FAIL)。"""
    print(f"\n===== 場景 {result.name} 結果 =====", flush=True)
    for c in result.checks:
        mark = "PASS" if c.ok else "FAIL"
        line = f"  [{mark}] {c.label}"
        if c.detail:
            line += f":{c.detail}"
        print(line, flush=True)
    for n in result.notes:
        print(f"  (note) {n}", flush=True)
    print("  模式轉換序列:", flush=True)
    for t, m in result.mode_events:
        print(f"    t={t:7.1f}s  {m}", flush=True)
    print(f"RESULT: {'PASS' if result.passed else 'FAIL'} scenario={result.name}", flush=True)


def make_clock():
    """回傳相對秒數時鐘(各場景自己歸零)。"""
    t0 = time.monotonic()
    return lambda: time.monotonic() - t0


def logline(t: float, msg: str) -> None:
    print(f"[{t:7.1f}s] {msg}", flush=True)


def ne_offset_m(
    lat0: float, lon0: float, lat: float, lon: float
) -> tuple[float, float]:
    """(lat, lon) 相對 (lat0, lon0) 的北/東平面近似偏移(公尺;S24 覆蓋斷言用)。"""
    k = math.pi / 180.0
    east = (lon - lon0) * k * math.cos((lat0 + lat) * 0.5 * k) * 6371000.0
    north = (lat - lat0) * k * 6371000.0
    return north, east


def dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """兩經緯度點的近距離平面近似(公尺);百餘公尺尺度誤差可忽略。"""
    return math.hypot(*ne_offset_m(lat1, lon1, lat2, lon2))


async def wait_connected(drone: System) -> None:
    """等待 core.connection_state 連上(複用 mission_exec.main.wait_connected)。"""
    try:
        await _me_wait_connected(drone)
    except RuntimeError as e:
        raise ScenarioError(str(e)) from e


async def connect(cfg: ScenarioConfig, timeout_s: float = 60.0) -> System:
    """spawn 內建 mavsdk_server 並連線(gRPC 埠取 cfg.grpc_port,避免多場景相撞)。"""
    drone = System(port=cfg.grpc_port)
    logline(0.0, f"連線中:{cfg.url}(gRPC {cfg.grpc_port})")
    await drone.connect(system_address=cfg.url)
    await asyncio.wait_for(wait_connected(drone), timeout=timeout_s)
    return drone


async def arm_with_retry(drone: System, attempts: int = 8, delay_s: float = 5.0) -> None:
    """arm 並對 COMMAND_DENIED 重試(慢 runner 上 SITL 就緒晚於固定等待的常見情況)。

    2026-07-11 nightly 實錄:f10/f11 在較慢的 hosted runner 上 arm 立即被拒,
    且例外未被接住導致行程懸掛吃滿外層 timeout(exit 124)——就緒與快速失敗都在此收斂。
    超過 attempts 仍被拒 → 升級 ScenarioError(main 會立刻 RESULT: FAIL)。
    """
    from mavsdk.action import ActionError

    for i in range(1, attempts + 1):
        try:
            await drone.action.arm()
            return
        except ActionError as e:
            if i == attempts:
                raise ScenarioError(f"arm 連續 {attempts} 次被拒:{e}") from e
            logline(0.0, f"arm 被拒({e}),{delay_s:.0f}s 後重試({i}/{attempts})")
            await asyncio.sleep(delay_s)


async def wait_position_ready(drone: System) -> None:
    """等待全球定位 + home 就緒(複用 mission_exec.executor.wait_position_ready)。"""
    try:
        await _me_wait_position_ready(drone)
    except RuntimeError as e:
        raise ScenarioError(str(e)) from e


def square_mission_items(
    alt_m: float = 20.0, speed_ms: float = 5.0, loops: int = 1
) -> list[MissionItem]:
    """方形任務航點(座標取自 demo_square.json;轉譯複用 mission_exec.translate)。

    hold_s 固定 0(不停點 fly-through);speed_ms <= 0 → 飛控預設(NaN),
    相機/雲台欄位 NaN/NONE——均由 to_mission_items 的單一實作保證。
    """
    plan = mission_pb2.MissionPlan(
        mission_id="sitl-square",
        waypoints=[
            mission_pb2.Waypoint(lat_deg=lat, lon_deg=lon, rel_alt_m=alt_m, speed_ms=speed_ms)
            for lat, lon in SQUARE_CORNERS * loops
        ],
    )
    return to_mission_items(plan)


async def upload_square(
    drone: System,
    *,
    alt_m: float = 20.0,
    speed_ms: float = 5.0,
    loops: int = 1,
    rtl_after_last: bool = False,
) -> None:
    """上傳方形任務;RTL 設定必在 upload 之前(對齊 mission_exec.executor 的註記)。"""
    await drone.mission.set_return_to_launch_after_mission(rtl_after_last)
    await drone.mission.upload_mission(MissionPlan(square_mission_items(alt_m, speed_ms, loops)))


def docker_container_ip(name: str) -> str:
    """docker inspect 取容器 IP(F09 被動觀測的源 IP 過濾用)。"""
    try:
        out = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                name,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raise ScenarioError(f"docker inspect {name} 失敗:{e}") from e
    if not out:
        raise ScenarioError(f"docker inspect 取不到容器 {name} 的 IP")
    return out


def pxh_param_set(container: str, name: str, value) -> None:
    """容器內 px4-param set(毫秒級生效,避開 MAVLink 往返;F10 放慢 drain 用)。"""
    subprocess.run(
        ["docker", "exec", container, f"{PX4_BIN_DIR}/px4-param", "set", name, str(value)],
        check=True,
        capture_output=True,
        timeout=10,
    )


class Recorder:
    """背景遙測記錄器:flight_mode 轉換(含當下離 home 距離)、in_air / armed、相對高度。

    mavsdk_server 3.15.3 曾有串流無聲死亡的前例(F10 探測),故僅供 F11/F12 這類
    「MAVSDK 連線全程存活」的場景使用;F09(kill server)與 F10(長時間放電)各自
    使用被動 pymavlink / 容器內 px4-listener 觀測。
    """

    def __init__(self, drone: System, clock, home: tuple[float, float] | None = None):
        self._drone = drone
        self._clock = clock
        self.home = home
        self.mode_marks: list[tuple[float, str, float]] = []  # (t, mode, 當下離 home 距離)
        self.mode_now: str | None = None
        self.in_air: bool | None = None
        self.armed: bool | None = None
        self.dist_home = 0.0
        self.max_dist_home = 0.0
        self.rel_alt = 0.0
        # home 相對北/東偏移極值(公尺;S24 F05 網格覆蓋斷言用,home=None 時不更新)
        self.north_min = 0.0
        self.north_max = 0.0
        self.east_min = 0.0
        self.east_max = 0.0
        self._tasks: list[asyncio.Task] = []

    @property
    def mode_events(self) -> list[tuple[float, str]]:
        return [(t, m) for t, m, _ in self.mode_marks]

    async def _watch_position(self) -> None:
        async for p in self._drone.telemetry.position():
            self.rel_alt = p.relative_altitude_m
            if self.home is not None:
                n, e = ne_offset_m(self.home[0], self.home[1], p.latitude_deg, p.longitude_deg)
                self.north_min = min(self.north_min, n)
                self.north_max = max(self.north_max, n)
                self.east_min = min(self.east_min, e)
                self.east_max = max(self.east_max, e)
                d = math.hypot(n, e)
                self.dist_home = d
                self.max_dist_home = max(self.max_dist_home, d)

    async def _watch_mode(self) -> None:
        async for m in self._drone.telemetry.flight_mode():
            s = str(m)
            if s != self.mode_now:
                self.mode_now = s
                t = self._clock()
                self.mode_marks.append((t, s, self.dist_home))
                logline(t, f"MODE -> {s}(dist={self.dist_home:.1f} m,alt={self.rel_alt:.1f} m)")

    async def _watch_in_air(self) -> None:
        async for v in self._drone.telemetry.in_air():
            self.in_air = v

    async def _watch_armed(self) -> None:
        async for v in self._drone.telemetry.armed():
            self.armed = v

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._watch_position()),
            asyncio.create_task(self._watch_mode()),
            asyncio.create_task(self._watch_in_air()),
            asyncio.create_task(self._watch_armed()),
        ]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

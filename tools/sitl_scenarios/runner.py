"""共用骨架:連 SITL、方形 demo 任務、遙測記錄、PASS/FAIL 結果輸出。

複用來源(S7 規格:盡量複用 onboard/mission_exec;該目錄非可安裝套件、無法跨樹
import,故抄最小必要段並在此註明):
- wait_connected()/connect():改寫自 onboard/mission_exec/mission_exec/main.py::_connect
- wait_position_ready():抄自 onboard/mission_exec/mission_exec/executor.py::_wait_position_ready
- SQUARE_CORNERS:取自 onboard/mission_exec/missions/demo_square.json 的四個角點
- square_mission_items():欄位慣例對齊 onboard/mission_exec/mission_exec/translate.py
  ::to_mission_item(speed<=0 → NaN、不停點 fly-through、相機/雲台欄位 NaN/NONE)
"""

import asyncio
import math
import subprocess
import time
from dataclasses import dataclass, field

from mavsdk import System
from mavsdk.mission import MissionItem, MissionPlan

_NAN = float("nan")

#: demo_square.json 的四個角點(SITL Zurich 家點附近,邊長約 100 m)
SQUARE_CORNERS = [
    (47.398642, 8.545594),
    (47.398642, 8.546920),
    (47.397742, 8.546920),
    (47.397742, 8.545594),
]

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


def dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """兩經緯度點的近距離平面近似(公尺);百餘公尺尺度誤差可忽略。"""
    k = math.pi / 180.0
    x = (lon2 - lon1) * k * math.cos((lat1 + lat2) * 0.5 * k) * 6371000.0
    y = (lat2 - lat1) * k * 6371000.0
    return math.hypot(x, y)


async def wait_connected(drone: System) -> None:
    """等待 core.connection_state 連上(改寫自 mission_exec.main._connect)。"""
    async for state in drone.core.connection_state():
        if state.is_connected:
            return
    raise ScenarioError("連線串流結束仍未連上飛行器")


async def connect(cfg: ScenarioConfig, timeout_s: float = 60.0) -> System:
    """spawn 內建 mavsdk_server 並連線(gRPC 埠取 cfg.grpc_port,避免多場景相撞)。"""
    drone = System(port=cfg.grpc_port)
    logline(0.0, f"連線中:{cfg.url}(gRPC {cfg.grpc_port})")
    await drone.connect(system_address=cfg.url)
    await asyncio.wait_for(wait_connected(drone), timeout=timeout_s)
    return drone


async def wait_position_ready(drone: System) -> None:
    """等待全球定位 + home 就緒(抄自 mission_exec.executor._wait_position_ready)。"""
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            return
    raise ScenarioError("健康狀態串流在定位就緒前結束(鏈路中斷?)")


def square_mission_items(
    alt_m: float = 20.0, speed_ms: float = 5.0, loops: int = 1
) -> list[MissionItem]:
    """方形任務航點(座標取自 demo_square.json;欄位慣例對齊 translate.to_mission_item)。"""
    items = []
    for lat, lon in SQUARE_CORNERS * loops:
        items.append(
            MissionItem(
                latitude_deg=lat,
                longitude_deg=lon,
                relative_altitude_m=alt_m,
                speed_m_s=speed_ms if speed_ms > 0.0 else _NAN,
                is_fly_through=True,
                gimbal_pitch_deg=_NAN,
                gimbal_yaw_deg=_NAN,
                camera_action=MissionItem.CameraAction.NONE,
                loiter_time_s=_NAN,
                camera_photo_interval_s=_NAN,
                acceptance_radius_m=_NAN,
                yaw_deg=_NAN,
                camera_photo_distance_m=_NAN,
                vehicle_action=MissionItem.VehicleAction.NONE,
            )
        )
    return items


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
        self._tasks: list[asyncio.Task] = []

    @property
    def mode_events(self) -> list[tuple[float, str]]:
        return [(t, m) for t, m, _ in self.mode_marks]

    async def _watch_position(self) -> None:
        async for p in self._drone.telemetry.position():
            self.rel_alt = p.relative_altitude_m
            if self.home is not None:
                d = dist_m(self.home[0], self.home[1], p.latitude_deg, p.longitude_deg)
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

"""F09 失聯保護(datalink/GCS 失聯 → RTL)SITL 回歸場景。

對應架次:flight-test-plan F09「失聯 RTL」/ 03-safety-analysis §4「RC 失聯」列。

觸發語義偏移(誠實註記,以探測實測為準):
  F09 矩陣的承載觸發本是 RC 失聯(NAV_RCL_ACT=2),但本 SITL 映像無實體 RC 且
  COM_RC_IN_MODE=1 令 RC 失聯失效保護關閉,RC 失聯「不可注入」;MAVSDK failure
  plugin 的 SYSTEM_MAVLINK_SIGNAL / RC_SIGNAL 在 PX4 v1.15.4 亦無韌體消費者
  (Commander 不處理該注入,實跑後模式恆為 AUTO_MISSION,且 inject() 一律回
  TIMEOUT——那是 mavlink_receiver 對 INJECT_FAILURE 不回 ack,非「不支援」的證據)。
  故本場景以 datalink/GCS 失聯(NAV_DLL_ACT=2)作為「同樣切 RTL」的可測代理;
  Phase 0 參數表 NAV_DLL_ACT 預設 0,此處臨時改 2——驗的是 RTL 失效保護機制,
  不是 Phase 0 datalink 的預設行為。

注入法(Path B,韌體實證 CHECK_FAILSAFE(gcs_connection_lost, ...) → Action::RTL):
  1. 自 spawn mavsdk_server(啟動時必須帶連線 URL;connect() 在給了
     mavsdk_server_address 時會忽略 system_address)。它就是 PX4 眼中唯一的
     GCS 心跳源,同時負責上傳 4 航點方形任務、arm、start。
  2. 前置參數(皆 INT32,必須 set_param_int;set_param_float 會 TIMEOUT):
     NAV_DLL_ACT=2、COM_DL_LOSS_T=3。
  3. 注入 = 以自持 Popen PID 精準 kill 該 mavsdk_server(勿 pkill 免誤傷他人)
     → GCS 心跳中斷 → 逾 COM_DL_LOSS_T 後 gcs_connection_lost=true
     → AUTO_LOITER 短暫過渡 → AUTO_RTL。
  4. 斷言全靠「被動」pymavlink 觀測 socket(綁 0.0.0.0:14550,絕不發送,故不算
     GCS);必須依本容器源 IP 過濾——多個 SITL 容器都把 GCS MAVLink 廣播到
     host:14550,混收他機心跳曾造成假 PASS。

通過準則(兩次獨立實測 run4/run5:+5.3/6.1s LOITER、+10.4/11.2s RTL):
  1. 注入前:AUTO_MISSION 且 armed 且 IN_AIR(任務僅飛數秒、遠未完成 4 航點,
     排除 rtl_after_last 誤判)
  2. kill 後 30 秒內觀測到 AUTO_RTL(實測約 10–11 秒,COM_DL_LOSS_T=3)
  3. RTL 觸發前 landed_state 維持 IN_AIR(續飛返航,而非就地降落)
"""

import asyncio
import socket
import subprocess
import threading
from pathlib import Path

from pymavlink import mavutil

from sitl_scenarios.checks import latency_to_mode
from sitl_scenarios.runner import (
    ScenarioConfig,
    ScenarioError,
    ScenarioResult,
    docker_container_ip,
    logline,
    make_clock,
    upload_square,
    wait_connected,
    wait_position_ready,
)

NAME = "f09"
TITLE = "F09 失聯保護(datalink/GCS 失聯 → RTL)"

#: SITL 映像固定把 GCS MAVLink 廣播到 host docker gateway 的 14550(不可調)
OBS_PORT = 14550

#: HEARTBEAT.custom_mode 的 (main_mode, sub_mode) 解碼表(PX4)
_MODES = {
    (1, 0): "MANUAL",
    (2, 0): "ALTCTL",
    (3, 0): "POSCTL",
    (4, 2): "AUTO_TAKEOFF",
    (4, 3): "AUTO_LOITER",
    (4, 4): "AUTO_MISSION",
    (4, 5): "AUTO_RTL",
    (4, 6): "AUTO_LAND",
    (6, 0): "ACRO",
    (7, 0): "OFFBOARD",
    (8, 0): "STABILIZED",
}
_LANDED = {0: "UNDEFINED", 1: "ON_GROUND", 2: "IN_AIR", 3: "TAKEOFF", 4: "LANDING"}


class _Observer(threading.Thread):
    """被動 MAVLink 觀測:綁 14550 只收不發(不構成 GCS 心跳),依源 IP 過濾。"""

    def __init__(self, source_ip: str, clock):
        super().__init__(daemon=True)
        self._source_ip = source_ip
        self._clock = clock
        self.mode_events: list[tuple[float, str]] = []
        self.landed_events: list[tuple[float, str]] = []
        self.mode_now: str | None = None
        self.armed_now: bool | None = None
        self.landed_now: str | None = None
        # 注意:不可命名 self._stop —— 會遮蔽 threading.Thread._stop(),join() 會炸
        self._stop_flag = False
        # 在主執行緒 bind,埠被占直接以 ScenarioError 浮出(而非 thread 內靜默死亡)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._sock.bind(("0.0.0.0", OBS_PORT))
        except OSError as e:
            raise ScenarioError(
                f"觀測埠 {OBS_PORT} bind 失敗(他人 GCS/觀測器占用?):{e}"
            ) from e
        self._sock.settimeout(0.5)

    def run(self) -> None:
        mav = mavutil.mavlink.MAVLink(None)
        mav.robust_parsing = True
        while not self._stop_flag:
            try:
                data, addr = self._sock.recvfrom(4096)
            except TimeoutError:
                continue
            except OSError:
                break
            if addr[0] != self._source_ip:
                continue  # 過濾掉其他 agent 容器的心跳(混收會產生假結果)
            try:
                msgs = mav.parse_buffer(data) or []
            except Exception:
                continue
            for msg in msgs:
                t = msg.get_type()
                if t == "HEARTBEAT":
                    cm = msg.custom_mode
                    mode = _MODES.get(((cm >> 16) & 0xFF, (cm >> 24) & 0xFF), f"raw={cm}")
                    armed = bool(msg.base_mode & 128)
                    if mode != self.mode_now or armed != self.armed_now:
                        now = self._clock()
                        if mode != self.mode_now:
                            self.mode_events.append((now, mode))
                        logline(now, f"OBS mode={mode} armed={armed}")
                        self.mode_now, self.armed_now = mode, armed
                elif t == "EXTENDED_SYS_STATE":
                    ls = _LANDED.get(msg.landed_state, str(msg.landed_state))
                    if ls != self.landed_now:
                        self.landed_events.append((self._clock(), ls))
                        self.landed_now = ls
        self._sock.close()

    def stop(self) -> None:
        self._stop_flag = True


def _spawn_mavsdk_server(grpc_port: int, url: str) -> subprocess.Popen:
    """外部 mavsdk_server:必須啟動時帶 URL(見模組 docstring 注入法第 1 點)。"""
    from mavsdk import bin as mavsdk_bin

    server_bin = Path(mavsdk_bin.__file__).with_name("mavsdk_server")
    return subprocess.Popen(
        [str(server_bin), "-p", str(grpc_port), url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def run(cfg: ScenarioConfig) -> ScenarioResult:
    from mavsdk import System

    source_ip = cfg.source_ip or (docker_container_ip(cfg.container) if cfg.container else None)
    if not source_ip:
        raise ScenarioError(
            "F09 需要 --container(docker inspect 取源 IP)或 --source-ip:"
            "被動觀測 14550 不過濾源 IP 會混收其他 SITL 容器的心跳,產生假結果"
        )

    clock = make_clock()
    result = ScenarioResult(NAME)
    result.notes.append(f"觀測源 IP 過濾:{source_ip}(容器 {cfg.container or '手動指定'})")

    obs = _Observer(source_ip, clock)
    obs.start()
    server = _spawn_mavsdk_server(cfg.grpc_port, cfg.url)
    try:
        drone = System(mavsdk_server_address="127.0.0.1", port=cfg.grpc_port)
        await drone.connect()  # URL 已由外部 server 帶入,此處參數會被忽略
        await asyncio.wait_for(wait_connected(drone), timeout=60)
        logline(clock(), "已連上(外部 mavsdk_server = 唯一 GCS 心跳源)")

        await drone.param.set_param_int("NAV_DLL_ACT", 2)
        await drone.param.set_param_int("COM_DL_LOSS_T", 3)
        dll = await drone.param.get_param_int("NAV_DLL_ACT")
        dlt = await drone.param.get_param_int("COM_DL_LOSS_T")
        if dll != 2 or dlt != 3:
            raise ScenarioError(f"參數驗證失敗:NAV_DLL_ACT={dll} COM_DL_LOSS_T={dlt}")
        result.notes.append(f"param 驗證:NAV_DLL_ACT={dll} COM_DL_LOSS_T={dlt}")

        await upload_square(drone, alt_m=30.0, speed_ms=4.0, rtl_after_last=True)
        await asyncio.wait_for(wait_position_ready(drone), timeout=120)
        await drone.action.arm()
        await drone.mission.start_mission()
        logline(clock(), "已 arm + start_mission(4 航點方形,30 m,4 m/s)")

        deadline = clock() + 90
        while clock() < deadline:
            if obs.mode_now == "AUTO_MISSION" and obs.armed_now and obs.landed_now == "IN_AIR":
                break
            await asyncio.sleep(0.3)
        pre_ok = (
            obs.mode_now == "AUTO_MISSION" and obs.armed_now is True and obs.landed_now == "IN_AIR"
        )
        result.add(
            "注入前 AUTO_MISSION + armed + IN_AIR",
            pre_ok,
            f"mode={obs.mode_now} armed={obs.armed_now} landed={obs.landed_now}",
        )

        await asyncio.sleep(5)  # 任務中基線(僅飛數秒,遠未完成,排除 rtl_after_last)
        inject_t = clock()
        logline(inject_t, "注入:kill 自持 mavsdk_server PID(GCS 心跳中斷)")
        server.kill()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

        while clock() < inject_t + 30:
            if obs.mode_now == "AUTO_RTL":
                break
            await asyncio.sleep(0.2)
        await asyncio.sleep(1)  # 收尾一拍,讓事件寫完

        rtl_lat = latency_to_mode(obs.mode_events, "AUTO_RTL", inject_t)
        result.add(
            "注入後 30 s 內切 AUTO_RTL",
            rtl_lat is not None and rtl_lat <= 30.0,
            f"延遲 {rtl_lat:.1f} s(實測基準約 10–11 s,COM_DL_LOSS_T=3)"
            if rtl_lat is not None
            else f"30 s 內未見 AUTO_RTL(mode={obs.mode_now})",
        )
        loiter_lat = latency_to_mode(obs.mode_events, "AUTO_LOITER", inject_t)
        loiter_txt = f"+{loiter_lat:.1f} s" if loiter_lat is not None else "未觀測到"
        result.notes.append(
            f"AUTO_LOITER 過渡:{loiter_txt}(失效保護狀態機的短暫過渡,非硬性準則)"
        )
        rtl_abs = None if rtl_lat is None else inject_t + rtl_lat
        grounded = [
            t
            for t, s in obs.landed_events
            if s == "ON_GROUND" and inject_t < t <= (rtl_abs if rtl_abs is not None else clock())
        ]
        result.add(
            "RTL 觸發前維持 IN_AIR(續飛返航,非就地降落)",
            not grounded,
            f"landed 事件:{obs.landed_events}" if grounded else f"landed={obs.landed_now}",
        )
    finally:
        if server.poll() is None:
            server.kill()
        obs.stop()
        obs.join(timeout=3)

    result.mode_events = obs.mode_events
    return result

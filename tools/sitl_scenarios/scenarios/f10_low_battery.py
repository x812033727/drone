"""F10 低電量三級(Low 警告 → Critical RTL → Emergency 就地降落)SITL 回歸場景。

對應架次:flight-test-plan F10「低電量分級」/ 03-safety-analysis §4 低電量三列。

參數差異(誠實註記,以韌體源碼與實測為準):
  參數表 v1(build-and-first-flight.md §3)寫 COM_LOW_BAT_ACT=2「Critical 觸發 RTL」,
  但 PX4 v1.15 韌體(commander_params.c)2=「Land mode」= critical 即就地降落
  (實測 Flight C:remaining=0.067、尚未到 Emergency 即入 AUTO_LAND,全程無 RTL);
  要矩陣「Critical RTL → Emergency 降落」必須 =3(Return at critical, land at
  emergency)。本場景以 3 驗證矩陣行為;參數表 v1 與 03-safety-analysis §4.1 的
  該格需要修訂(見 README「探測發現」)。

注入法(探測實證):
  * 前置 param:COM_LOW_BAT_ACT=3(INT32,set_param_int);
    BAT_LOW_THR/BAT_CRIT_THR/BAT_EMERGEN_THR=0.20/0.10/0.05(FLOAT,對齊參數表 v1);
    BAT1_V_LOAD_DROP=0.0——SITL 必要:SOC 是電壓推估+油門×0.1V 補償,sim 電壓地板
    = BAT1_V_EMPTY,懸停油門 ≈0.7 下 SOC 地板 ≈0.157,不清零則 Critical/Emergency
    永不觸發(實測 run1 卡死 0.157)。此 workaround 僅 SITL 適用,實機 SOC 來自
    真實電壓/BMS。
  * 注入 = SIM_BAT_MIN_PCT=0 + SIM_BAT_DRAIN=90(90 秒線性放電;預設 MIN_PCT=50
    會把電量擋在 50%;drain 自 arm 起算,disarm 後 sim 電池立即回滿)。
  * CRITICAL 觸發瞬間把 SIM_BAT_DRAIN 放慢到 240(容器內 px4-param,毫秒級生效):
    否則 v1 門檻下 Crit→Emerg 僅約 4.5 s,小於 COM_FAIL_ACT_T=5 s 的 failsafe Hold,
    RTL 段會被吞掉直接 LAND(實測 Flight B)。實機真實放電率下間隔遠大於 5 s,
    非問題;但架次規劃應知道有這 5 s Hold。
  * 監控走容器內 px4-listener 0.4 s 輪詢(docker exec):mavsdk_server 3.15.3 曾於
    飛行中無聲死亡(telemetry 串流靜默無例外),故斷言不依賴 MAVSDK 遙測。

通過準則(實測 Flight D:0.200 LOW 警告留 MISSION → 0.098 CRITICAL Hold 5s →
AUTO_RTL → 0.049 EMERGENCY → AUTO_LAND → 落地自動 disarm):
  1. LOW / CRITICAL / EMERGENCY 三門檻依序觸發
  2. LOW 當下 nav=AUTO_MISSION 且到 CRITICAL 前不離開(Low 僅警告不中斷)
  3. CRITICAL 後出現 AUTO_RTL(允許 AUTO_LOITER 5s Hold 過渡)
  4. EMERGENCY 後 AUTO_LAND 且 RTL 在 LAND 之前
  5. 最終落地自動 disarm

需要 --container(docker exec 跑 px4-listener / px4-param)。
"""

import asyncio

from sitl_scenarios.checks import evaluate_battery_ladder
from sitl_scenarios.runner import (
    PX4_BIN_DIR,
    ScenarioConfig,
    ScenarioError,
    ScenarioResult,
    arm_with_retry,
    connect,
    logline,
    make_clock,
    pxh_param_set,
    upload_square,
    wait_position_ready,
)

NAME = "f10"
TITLE = "F10 低電量三級(Low 警告 → Critical RTL → Emergency 就地降落)"

_V1_THRESHOLDS = {"BAT_LOW_THR": 0.20, "BAT_CRIT_THR": 0.10, "BAT_EMERGEN_THR": 0.05}
_NAV_NAMES = {
    3: "AUTO_MISSION",
    4: "AUTO_LOITER",
    5: "AUTO_RTL",
    12: "DESCEND",
    13: "TERMINATION",
    17: "AUTO_TAKEOFF",
    18: "AUTO_LAND",
}
_WARN_NAMES = {0: "NONE", 1: "LOW", 2: "CRITICAL", 3: "EMERGENCY"}

#: 容器內輪詢腳本(0.4 s):battery_status / vehicle_status / land_detected / mavlink_log
_POLL_SH = rf"""
B={PX4_BIN_DIR}
while true; do
  bat=$($B/px4-listener battery_status -n 1 2>/dev/null \
        | awk '$1=="remaining:"{{r=$2}} $1=="warning:"{{w=$2}} END{{print r" "w}}')
  vs=$($B/px4-listener vehicle_status -n 1 2>/dev/null \
       | awk '$1=="nav_state:"{{n=$2}} $1=="arming_state:"{{a=$2}} END{{print n" "a}}')
  ld=$($B/px4-listener vehicle_land_detected -n 1 2>/dev/null \
       | awk '$1=="landed:"{{print $2}}')
  tx=$($B/px4-listener mavlink_log -n 1 2>/dev/null | awk -F'"' '$1 ~ /text:/{{print $2}}')
  echo "BAT $bat VS $vs LAND $ld TXT $tx"
  sleep 0.4
done
"""


class _Watch:
    """容器內輪詢的狀態機:記錄 warning / nav_state 轉換,偵測 armed→disarmed。"""

    def __init__(self, clock, container: str):
        self._clock = clock
        self._container = container
        self.pct: float | None = None
        self.warn: int | None = None
        self.nav: int | None = None
        self.arming: int | None = None
        self.landed: str | None = None
        self.last_txt: str | None = None
        self.was_armed = False
        self.warn_events: list[tuple[float, str]] = []
        self.nav_events: list[tuple[float, str]] = []
        self.status_notes: list[str] = []
        self.done = asyncio.Event()
        self._slow_task: asyncio.Task | None = None

    @property
    def nav_name(self) -> str | None:
        return _NAV_NAMES.get(self.nav, str(self.nav)) if self.nav is not None else None

    def _slow_down_drain(self) -> None:
        """CRITICAL 一到就放慢放電(拉開 Crit→Emerg 間隔,別讓 5s Hold 吞掉 RTL)。"""

        def _do():
            pxh_param_set(self._container, "SIM_BAT_DRAIN", 240)

        async def _runner():
            try:
                await asyncio.to_thread(_do)
                logline(self._clock(), "CRITICAL → px4-param set SIM_BAT_DRAIN 240(放慢)")
            except Exception as e:
                logline(self._clock(), f"放慢 drain 失敗:{e}")

        self._slow_task = asyncio.create_task(_runner())

    def feed(self, pct: float, warn: int, nav: int, arming: int, landed: str, txt: str) -> None:
        now = self._clock()
        self.pct = round(pct, 3)
        if warn != self.warn:
            name = _WARN_NAMES.get(warn, str(warn))
            self.warn_events.append((now, name))
            logline(now, f"BATTERY_WARNING -> {name}(remaining={pct:.3f})")
            self.warn = warn
            if warn == 2:
                self._slow_down_drain()
        if nav != self.nav:
            name = _NAV_NAMES.get(nav, str(nav))
            self.nav_events.append((now, name))
            logline(now, f"NAV_STATE -> {name}(remaining={pct:.3f})")
            self.nav = nav
        if arming != self.arming:
            logline(now, f"ARMING_STATE -> {arming}(2=armed)")
            self.arming = arming
            if arming == 2:
                self.was_armed = True
            elif self.was_armed and arming == 1:
                self.done.set()
        if landed != self.landed:
            self.landed = landed
        if txt and txt != self.last_txt:
            self.last_txt = txt
            low = txt.lower()
            if any(k in low for k in ("batt", "land", "return", "rtl", "failsafe", "disarm")):
                logline(now, f"STATUSTEXT: {txt}")
                if len(self.status_notes) < 12:
                    self.status_notes.append(f"t={now:.1f}s {txt}")


async def _poller(container: str, watch: _Watch) -> None:
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        container,
        "bash",
        "-c",
        _POLL_SH,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                logline(watch._clock(), "poller:docker exec 輸出結束")
                break
            p = raw.decode().split()
            try:
                i_bat, i_vs = p.index("BAT"), p.index("VS")
                i_land, i_txt = p.index("LAND"), p.index("TXT")
                pct = float(p[i_bat + 1])
                warn = int(p[i_bat + 2])
                nav = int(p[i_vs + 1])
                arming = int(p[i_vs + 2])
                landed = p[i_land + 1] if i_land + 1 < i_txt else "?"
                txt = " ".join(p[i_txt + 1 :])
            except (ValueError, IndexError):
                continue  # px4-listener 偶發空輸出,略過該筆
            watch.feed(pct, warn, nav, arming, landed, txt)
    finally:
        proc.kill()
        await proc.wait()


async def _inject_drain(drone, watch, container: str, clock) -> None:
    """放電注入 + 回讀驗證 + 生效看門狗。

    2026-07-12 nightly 實錄:單發 set_param_float(SIM_BAT_MIN_PCT=0) 疑似未黏住,
    三門檻全程未觸發、420 s 靜默逾時吃滿。把「靜默無效」收斂為自癒或快速失敗:
    (1) 寫後回讀不符即重寫(×3);(2) 60 s 內電量未跌破 0.45 → 容器內 px4-param
    後備注入;再 30 s 仍無下降 → ScenarioError 快速失敗(帶當下 pct 可診斷)。
    """
    for attempt in range(1, 4):
        await drone.param.set_param_float("SIM_BAT_MIN_PCT", 0.0)
        try:
            rb = await drone.param.get_param_float("SIM_BAT_MIN_PCT")
        except Exception:
            rb = None
        if rb is not None and rb < 0.5:
            logline(
                clock(),
                f"注入:SIM_BAT_MIN_PCT=0 生效(回讀 {rb:.1f},第 {attempt} 次;90 s 放電開始)",
            )
            break
        logline(clock(), f"注入回讀不符(rb={rb}),重寫 {attempt}/3")
    else:
        raise ScenarioError("SIM_BAT_MIN_PCT 注入三次回讀皆不符")

    deadline = clock() + 60
    while clock() < deadline:
        if watch.pct is not None and watch.pct < 0.45:
            return
        await asyncio.sleep(1)
    logline(clock(), f"60 s 電量未開始下降(pct={watch.pct}),px4-param 後備注入")
    await asyncio.to_thread(pxh_param_set, container, "SIM_BAT_MIN_PCT", 0)
    deadline = clock() + 30
    while clock() < deadline:
        if watch.pct is not None and watch.pct < 0.45:
            return
        await asyncio.sleep(1)
    raise ScenarioError(f"放電注入未生效(pct={watch.pct})——快速失敗取代 420 s 靜默逾時")


async def run(cfg: ScenarioConfig) -> ScenarioResult:
    if not cfg.container:
        raise ScenarioError("F10 需要 --container(docker exec 跑 px4-listener / px4-param)")

    clock = make_clock()
    result = ScenarioResult(NAME)
    drone = await connect(cfg)

    await drone.param.set_param_int("COM_LOW_BAT_ACT", 3)
    for name, value in _V1_THRESHOLDS.items():
        await drone.param.set_param_float(name, value)
    await drone.param.set_param_float("BAT1_V_LOAD_DROP", 0.0)  # SITL SOC 地板 workaround
    await drone.param.set_param_float("SIM_BAT_MIN_PCT", 50.0)  # 先擋住,注入時才放
    await drone.param.set_param_float("SIM_BAT_DRAIN", 90.0)
    act = await drone.param.get_param_int("COM_LOW_BAT_ACT")
    if act != 3:
        raise ScenarioError(f"參數驗證失敗:COM_LOW_BAT_ACT={act}(需 3)")
    result.notes.append(
        "COM_LOW_BAT_ACT=3(參數表 v1 寫 2,但 v1.15 韌體 2=Land mode;見模組 docstring)"
    )

    await upload_square(drone, alt_m=20.0, speed_ms=5.0, loops=2, rtl_after_last=False)
    await asyncio.wait_for(wait_position_ready(drone), timeout=120)

    watch = _Watch(clock, cfg.container)
    ptask = asyncio.create_task(_poller(cfg.container, watch))
    try:
        await arm_with_retry(drone)
        await drone.mission.start_mission()
        logline(clock(), "已 arm + start_mission(方形 ×2,20 m,5 m/s)")

        deadline = clock() + 120
        while clock() < deadline:
            if watch.nav_name == "AUTO_MISSION" and watch.landed == "False":
                break
            await asyncio.sleep(0.2)
        else:
            raise ScenarioError(f"未進入 AUTO_MISSION(nav={watch.nav_name} landed={watch.landed})")

        await asyncio.sleep(5)  # 任務中基線
        await _inject_drain(drone, watch, cfg.container, clock)

        try:
            await asyncio.wait_for(watch.done.wait(), timeout=420)
            logline(clock(), "落地且自動 disarm,飛行結束")
        except asyncio.TimeoutError:
            logline(clock(), "逾時:420 s 內未觀測到落地 disarm")
    finally:
        ptask.cancel()
        await asyncio.gather(ptask, return_exceptions=True)
        if watch._slow_task is not None:
            await asyncio.gather(watch._slow_task, return_exceptions=True)

    for label, ok, detail in evaluate_battery_ladder(watch.warn_events, watch.nav_events):
        result.add(label, ok, detail)
    result.add(
        "落地自動 disarm",
        watch.was_armed and watch.done.is_set(),
        f"was_armed={watch.was_armed} disarmed={watch.done.is_set()}",
    )
    result.notes.extend(watch.status_notes)
    result.mode_events = watch.nav_events
    return result

"""F12 GPS 劣化/失效(任務中 SENSOR_GPS OFF → 就地 LAND)SITL 回歸場景。

對應架次:flight-test-plan F12「GPS 劣化降級」/ 03-safety-analysis §4 GPS 劣化列。

行為語義(誠實註記,以探測實測為準):
  GPS「完全 OFF」觸發的是失效保護終端分支 LAND(就地降落):位置估計徹底發散,
  Hold/RTL 都需要位置故無法執行,PX4 1.15 直接下降降落。這不是矩陣列的
  「懸停 → RTH」漸進分支——要觀察漸進行為需注入部分劣化(FailureType.GARBAGE
  或降衛星數),不能用 OFF。本場景斷言 LAND(descend-in-place),不可寫 RTL/Hold。
  另:SITL 無 RC 連線,屬「無人接管」自主情境;實機 RC 在手時 GPS 失效可能交還
  操手(手動),行為與此不同(對照 REQ-NAV-02)。

注入法(探測實證):
  * 前置:SYS_FAILURE_EN=1(啟用失效注入;僅 SIM 接受,實機禁用)
  * 注入:drone.failure.inject(FailureUnit.SENSOR_GPS, FailureType.OFF, 0)
    ——MAVSDK 3.15 的 inject 簽名第三參 instance=0 為必填位置參數。
  * 收尾 best-effort 恢復:inject(SENSOR_GPS, FailureType.OK, 0)。

通過準則(實測:+0.8 s NO_GPS、+5.1 s CRITICAL "Failsafe activated" + LAND、
+8.2 s global_pos_ok=False、落地 "Landing detected" → 自動 disarm;
時序為 EKF 驅動、逐次浮動,故斷言用寬鬆時窗,不卡死秒數):
  1. 注入前:flight_mode=MISSION、is_global_position_ok=True、fix=FIX_3D
  2. 注入後 8 s 內 gps fix → NO_GPS
  3. 注入後 15 s 內 flight_mode → LAND(就地降落,非 RTL/Hold)
  4. 注入後 25 s 內 is_global_position_ok → False
  5. 150 s 內落地並自動 disarm
     (落地後地面 idle 會回報 flight_mode=MISSION——mission 未清的 idle nav state,
     不可誤讀為持續飛行;判斷結合 in_air/armed)

已知雜訊:落地前後的 'Preflight Fail: Battery unhealthy'、'height estimate not
stable' 等為 SITL 電池/估計器模型副作用,與 GPS 斷言無關,一律忽略。
"""

import asyncio

from mavsdk.failure import FailureType, FailureUnit

from sitl_scenarios.checks import latency_to_mode, reached_within
from sitl_scenarios.runner import (
    Recorder,
    ScenarioConfig,
    ScenarioError,
    ScenarioResult,
    arm_with_retry,
    connect,
    logline,
    make_clock,
    upload_square,
    wait_position_ready,
)

NAME = "f12"
TITLE = "F12 GPS 劣化/失效(任務中 SENSOR_GPS OFF → 就地 LAND)"


class _GpsHealthWatch:
    """gps_info fix 與 health.is_global_position_ok 的轉換記錄。"""

    def __init__(self, drone, clock):
        self._drone = drone
        self._clock = clock
        self.fix_events: list[tuple[float, str]] = []
        self.fix_now: str | None = None
        self.global_ok_events: list[tuple[float, str]] = []
        self.global_ok_now: bool | None = None
        self.status_notes: list[str] = []
        self._tasks: list[asyncio.Task] = []

    async def _watch_gps(self) -> None:
        async for g in self._drone.telemetry.gps_info():
            fix = str(g.fix_type)
            if fix != self.fix_now:
                t = self._clock()
                self.fix_events.append((t, fix))
                logline(t, f"GPS fix -> {fix}(sats={g.num_satellites})")
                self.fix_now = fix

    async def _watch_health(self) -> None:
        async for h in self._drone.telemetry.health():
            ok = h.is_global_position_ok
            if ok != self.global_ok_now:
                t = self._clock()
                self.global_ok_events.append((t, "OK" if ok else "NOT_OK"))
                logline(t, f"is_global_position_ok -> {ok}")
                self.global_ok_now = ok

    async def _watch_status(self) -> None:
        async for s in self._drone.telemetry.status_text():
            low = s.text.lower()
            if any(k in low for k in ("failsafe", "gps", "land", "disarm", "position")):
                t = self._clock()
                logline(t, f"STATUS[{s.type}] {s.text}")
                if len(self.status_notes) < 12:
                    self.status_notes.append(f"t={t:.1f}s [{s.type}] {s.text}")

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._watch_gps()),
            asyncio.create_task(self._watch_health()),
            asyncio.create_task(self._watch_status()),
        ]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []


async def run(cfg: ScenarioConfig) -> ScenarioResult:
    clock = make_clock()
    result = ScenarioResult(NAME)
    drone = await connect(cfg)

    await drone.param.set_param_int("SYS_FAILURE_EN", 1)
    en = await drone.param.get_param_int("SYS_FAILURE_EN")
    if en != 1:
        raise ScenarioError(f"參數驗證失敗:SYS_FAILURE_EN={en}")
    result.notes.append("SYS_FAILURE_EN=1(失效注入啟用;僅 SIM,實機禁用)")

    await upload_square(drone, alt_m=30.0, speed_ms=5.0, rtl_after_last=True)
    await asyncio.wait_for(wait_position_ready(drone), timeout=120)

    rec = Recorder(drone, clock)
    watch = _GpsHealthWatch(drone, clock)
    rec.start()
    watch.start()
    try:
        await arm_with_retry(drone)
        await drone.mission.start_mission()
        logline(clock(), "已 arm + start_mission(4 航點方形,30 m,5 m/s)")

        deadline = clock() + 120
        while clock() < deadline:
            if rec.mode_now == "MISSION" and rec.in_air:
                break
            await asyncio.sleep(0.3)
        else:
            raise ScenarioError(f"未進入 MISSION/空中(mode={rec.mode_now} in_air={rec.in_air})")

        await asyncio.sleep(10)  # 飛進任務段,確保注入時在自動任務巡航中

        baseline_ok = (
            rec.mode_now == "MISSION" and watch.global_ok_now is True and watch.fix_now == "FIX_3D"
        )
        result.add(
            "注入前 MISSION + global_pos_ok + FIX_3D",
            baseline_ok,
            f"mode={rec.mode_now} global_ok={watch.global_ok_now} fix={watch.fix_now}",
        )

        inject_t = clock()
        logline(inject_t, "注入:failure.inject(SENSOR_GPS, OFF, instance=0)")
        await drone.failure.inject(FailureUnit.SENSOR_GPS, FailureType.OFF, 0)

        await asyncio.sleep(30)  # 觀測窗(實測 +0.8s NO_GPS、+5.1s LAND、+8.2s not-ok)

        no_gps_lat = latency_to_mode(watch.fix_events, "NO_GPS", inject_t)
        result.add(
            "注入後 8 s 內 gps fix → NO_GPS",
            no_gps_lat is not None and no_gps_lat <= 8.0,
            f"延遲 {no_gps_lat:.1f} s(實測 ~0.8 s)" if no_gps_lat is not None else "未觀測到",
        )
        land_lat = latency_to_mode(rec.mode_events, "LAND", inject_t)
        result.add(
            "注入後 15 s 內 flight_mode → LAND(就地降落,非 RTL/Hold)",
            land_lat is not None and land_lat <= 15.0,
            f"延遲 {land_lat:.1f} s(實測 ~5.1 s)"
            if land_lat is not None
            else f"未觀測到 LAND(mode={rec.mode_now})",
        )
        result.add(
            "注入後 25 s 內 is_global_position_ok → False",
            reached_within(watch.global_ok_events, "NOT_OK", inject_t, 25.0),
            f"轉換序列:{watch.global_ok_events}",
        )

        landed_disarmed = False
        deadline = inject_t + 150
        while clock() < deadline:
            if rec.in_air is False and rec.armed is False:
                landed_disarmed = True
                break
            await asyncio.sleep(1.0)
        result.add(
            "150 s 內落地並自動 disarm",
            landed_disarmed,
            f"in_air={rec.in_air} armed={rec.armed}"
            + ("" if landed_disarmed else "(逾時;落地後 idle 回報 MISSION 非飛行,見 docstring)"),
        )

        # 收尾 best-effort:恢復 GPS,讓容器回到可再用狀態(斷言不依賴此步)
        try:
            await drone.failure.inject(FailureUnit.SENSOR_GPS, FailureType.OK, 0)
            logline(clock(), "恢復:failure.inject(SENSOR_GPS, OK, 0)")
        except Exception as e:
            logline(clock(), f"GPS 恢復注入失敗(不影響斷言):{e}")
    finally:
        await watch.stop()
        await rec.stop()

    result.notes.extend(watch.status_notes)
    result.mode_events = rec.mode_events
    return result

"""場景斷言純函式:模式序列判定、注入延遲、圍欄穿越、低電量三級序列。

刻意不依賴 mavsdk / SITL,可直接單元測試(tests/test_checks.py)。
事件模型:list[tuple[float, str]] = (相對秒, 名稱) 的「轉換」序列,時間遞增。
"""

ModeEvent = tuple[float, str]


def modes_in_order(observed: list[str], expected: list[str]) -> bool:
    """expected 是否為 observed 的子序列(允許中間夾其他模式)。"""
    it = iter(observed)
    return all(any(mode == want for mode in it) for want in expected)


def first_mode_time(events: list[ModeEvent], name: str, t_min: float = 0.0) -> float | None:
    """回傳 t_min(含)之後首次出現 name 的時間;沒出現回傳 None。"""
    for t, m in events:
        if t >= t_min and m == name:
            return t
    return None


def latency_to_mode(events: list[ModeEvent], name: str, inject_t: float) -> float | None:
    """注入時刻到首次出現 name 的延遲秒數;沒出現回傳 None。"""
    t = first_mode_time(events, name, inject_t)
    return None if t is None else t - inject_t


def reached_within(
    events: list[ModeEvent], name: str, inject_t: float, timeout_s: float
) -> bool:
    """注入後 timeout_s 內是否出現 name。"""
    lat = latency_to_mode(events, name, inject_t)
    return lat is not None and lat <= timeout_s


def mode_at(events: list[ModeEvent], t: float) -> str | None:
    """t 時刻(含)生效中的名稱 = 最後一筆 time <= t 的轉換;t 之前無事件回傳 None。"""
    current = None
    for et, m in events:
        if et > t:
            break
        current = m
    return current


def crossed_boundary(max_dist_m: float, radius_m: float, margin_m: float = 10.0) -> bool:
    """是否穿越圍欄邊界超過容許值(F11 通過準則:不穿越 > 10 m)。"""
    return max_dist_m > radius_m + margin_m


def evaluate_battery_ladder(
    warn_events: list[ModeEvent], nav_events: list[ModeEvent]
) -> list[tuple[str, bool, str]]:
    """F10 低電量三級序列判定(COM_LOW_BAT_ACT=3 的矩陣行為)。

    warn_events:BATTERY_WARNING 轉換,如 [(t, "LOW"), (t, "CRITICAL"), (t, "EMERGENCY")]
    nav_events:nav_state 轉換,如 [(t, "AUTO_MISSION"), (t, "AUTO_LOITER"), ...]

    準則(SITL 實測 Flight D,見 scenarios/f10_low_battery.py docstring):
      1. LOW → CRITICAL → EMERGENCY 依序出現
      2. LOW 當下在 AUTO_MISSION,且到 CRITICAL 前不離開(Low 僅警告不中斷)
      3. CRITICAL 之後出現 AUTO_RTL(允許先入 AUTO_LOITER:COM_FAIL_ACT_T=5s Hold 過渡)
      4. EMERGENCY 之後出現 AUTO_LAND,且 RTL 在 LAND 之前(RTL 未被 Hold 吞掉)

    回傳 [(檢查名, 是否通過, 說明)],供 ScenarioResult 逐項記錄。
    """
    checks: list[tuple[str, bool, str]] = []
    t_low = first_mode_time(warn_events, "LOW")
    t_crit = first_mode_time(warn_events, "CRITICAL")
    t_emerg = first_mode_time(warn_events, "EMERGENCY")
    order_ok = (
        t_low is not None
        and t_crit is not None
        and t_emerg is not None
        and t_low < t_crit < t_emerg
    )
    checks.append(
        (
            "三門檻依序觸發 LOW→CRITICAL→EMERGENCY",
            order_ok,
            f"t_low={t_low} t_crit={t_crit} t_emerg={t_emerg}",
        )
    )
    if not order_ok:
        return checks

    low_mode = mode_at(nav_events, t_low)
    stayed = all(m == "AUTO_MISSION" for t, m in nav_events if t_low <= t < t_crit)
    checks.append(
        (
            "LOW 僅警告(在 AUTO_MISSION 且到 CRITICAL 前不離開)",
            low_mode == "AUTO_MISSION" and stayed,
            f"LOW 當下 nav={low_mode},期間維持={stayed}",
        )
    )

    t_rtl = first_mode_time(nav_events, "AUTO_RTL", t_crit)
    checks.append(
        (
            "CRITICAL 後切 AUTO_RTL(允許 AUTO_LOITER 5s Hold 過渡)",
            t_rtl is not None,
            f"t_rtl={t_rtl}(CRITICAL {t_crit} 之後)",
        )
    )

    t_land = first_mode_time(nav_events, "AUTO_LAND", t_emerg)
    land_ok = t_land is not None and t_rtl is not None and t_rtl < t_land
    checks.append(
        (
            "EMERGENCY 後 AUTO_LAND 且 RTL 在 LAND 之前",
            land_ok,
            f"t_land={t_land} t_rtl={t_rtl}",
        )
    )
    return checks

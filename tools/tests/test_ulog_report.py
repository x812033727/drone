"""ulog_report.py 異常門檻純函式單元測試:電池單芯電壓、GPS 3D fix 佔比、
振動 RMS 的觸發/不觸發邊界。用合成 numpy 陣列,不需真實 ULog。"""

import numpy as np
from ulog_report import (
    VIBRATION_WARN_MS2,
    VOLTAGE_SAG_WARN,
    battery_warning,
    gps_fix_ratio,
    gps_fix_warning,
    min_cell_voltage,
    vibration_rms,
    vibration_warning,
)


# --- 電池 ---------------------------------------------------------------
def test_min_cell_voltage_filters_unpowered_noise_and_divides_by_cells():
    # 6S:22.2 V/6 = 3.7;<1.0 V 的未上電雜訊被濾掉不影響 min
    v = np.array([0.0, 0.2, 25.2, 22.2, 24.0])
    assert min_cell_voltage(v, 6) == 22.2 / 6


def test_min_cell_voltage_none_when_all_noise():
    assert min_cell_voltage(np.array([0.0, 0.5, 0.9]), 6) is None


def test_min_cell_voltage_zero_cells_treated_as_one():
    assert min_cell_voltage(np.array([3.5]), 0) == 3.5


def test_battery_warning_boundary():
    # 剛好等於門檻不告警(< 才觸發);略低於才告警
    assert battery_warning(VOLTAGE_SAG_WARN) is None
    assert battery_warning(VOLTAGE_SAG_WARN + 0.01) is None
    w = battery_warning(VOLTAGE_SAG_WARN - 0.01)
    assert w is not None and "低於" in w


# --- GPS ----------------------------------------------------------------
def test_gps_fix_ratio():
    fix = np.array([3, 3, 3, 2])  # 3/4 = 0.75
    assert gps_fix_ratio(fix) == 0.75


def test_gps_fix_warning_boundary():
    # 佔比剛好 0.95 不告警;低於才告警
    assert gps_fix_warning(0.95) is None
    assert gps_fix_warning(0.96) is None
    assert gps_fix_warning(0.94) is not None


def test_gps_fix_ratio_and_warning_integration():
    fix96 = np.array([3] * 96 + [2] * 4)
    fix94 = np.array([3] * 94 + [1] * 6)
    assert gps_fix_warning(gps_fix_ratio(fix96)) is None
    assert gps_fix_warning(gps_fix_ratio(fix94)) is not None


# --- 振動 ---------------------------------------------------------------
def _acc_noise(n: int, sigma: float) -> np.ndarray:
    """1g 直流 + 三軸高頻雜訊(seed 固定,結果可重現)。
    vibration_rms 取每筆合成振幅的『標準差』——量的是振動起伏,故用雜訊而非穩態震盪。"""
    rng = np.random.default_rng(42)
    return 9.81 + rng.normal(0, sigma, (n, 3))


def test_vibration_rms_scales_with_noise_level():
    n = 500
    small = vibration_rms(_acc_noise(n, 5.0))
    big = vibration_rms(_acc_noise(n, 30.0))
    assert big > small > 0.0


def test_vibration_warning_via_rms_end_to_end():
    n = 500
    # 低雜訊不觸發;高雜訊(σ 大)使 RMS 超過門檻而觸發
    assert vibration_warning(vibration_rms(_acc_noise(n, 2.0))) is None
    assert vibration_warning(vibration_rms(_acc_noise(n, 80.0))) is not None


def test_vibration_warning_boundary():
    assert vibration_warning(VIBRATION_WARN_MS2) is None       # 等於不觸發(> 才觸發)
    assert vibration_warning(VIBRATION_WARN_MS2 - 0.1) is None
    w = vibration_warning(VIBRATION_WARN_MS2 + 0.1)
    assert w is not None and "振動" in w

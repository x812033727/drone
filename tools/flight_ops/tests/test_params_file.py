"""dev-machine-v1.params 與 build-and-first-flight.md §3 參數表逐項一致(雙重錨定)。"""

from flight_ops.apply_params import DEFAULT_PARAMS_FILE, parse_params_file

# 期望值硬編碼自 docs/50-project/phase0/build-and-first-flight.md §3(rev 1)
# 失效保護參數表 v1 + 電池三參數;檔案與文件任一單方改動都會讓本測試翻紅。
EXPECTED = {
    "NAV_RCL_ACT": (2, "INT32"),
    "COM_RC_LOSS_T": (0.5, "REAL32"),
    "NAV_DLL_ACT": (0, "INT32"),
    "COM_LOW_BAT_ACT": (3, "INT32"),  # 3=Critical 返航;2=Land mode(F10 實測,勿回退)
    "BAT_LOW_THR": (0.20, "REAL32"),
    "BAT_CRIT_THR": (0.10, "REAL32"),
    "BAT_EMERGEN_THR": (0.05, "REAL32"),
    "GF_ACTION": (3, "INT32"),
    "GF_MAX_HOR_DIST": (500.0, "REAL32"),  # PX4 v1.15 此二參數為 FLOAT
    "GF_MAX_VER_DIST": (100.0, "REAL32"),
    "RTL_RETURN_ALT": (40.0, "REAL32"),
    "RTL_DESCEND_ALT": (10.0, "REAL32"),
    "COM_OBL_RC_ACT": (0, "INT32"),
    "BAT1_N_CELLS": (4, "INT32"),  # X500 V2 開發機 = 4S
    "BAT1_V_EMPTY": (3.5, "REAL32"),
    "BAT1_V_CHARGED": (4.05, "REAL32"),
}


def test_default_file_exists():
    assert DEFAULT_PARAMS_FILE.is_file()


def test_all_16_params_present_with_expected_values_and_types():
    params = parse_params_file(DEFAULT_PARAMS_FILE)
    assert len(params) == 16
    by_name = {p.name: p for p in params}
    assert set(by_name) == set(EXPECTED)
    for name, (value, ptype) in EXPECTED.items():
        p = by_name[name]
        assert p.ptype == ptype, f"{name} 型別應為 {ptype},實為 {p.ptype}"
        assert p.value == float(value), f"{name} 值應為 {value},實為 {p.value}"


def test_int_params_have_integral_values():
    for p in parse_params_file(DEFAULT_PARAMS_FILE):
        if p.ptype == "INT32":
            assert p.value == int(p.value)

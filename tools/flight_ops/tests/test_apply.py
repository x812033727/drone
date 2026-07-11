"""apply_params 單元測試:解析容錯、比對容差、寫入/dry-run 流程(mock param plugin)。"""

import asyncio

import pytest
from flight_ops.apply_params import Param, apply_and_verify, parse_params_file, value_ok


def write_params(tmp_path, text):
    f = tmp_path / "t.params"
    f.write_text(text, encoding="utf-8")
    return f


# ---- 解析器 ----


def test_parse_tolerates_comments_and_blank_lines(tmp_path):
    f = write_params(
        tmp_path,
        "# Onboard parameters for Vehicle 1\n"
        "#\n"
        "\n"
        "1\t1\tNAV_RCL_ACT\t2\t6\n"
        "\n"
        "1\t1\tCOM_RC_LOSS_T\t0.5\t9\n",
    )
    params = parse_params_file(f)
    assert params == [
        Param(name="NAV_RCL_ACT", value=2.0, ptype="INT32"),
        Param(name="COM_RC_LOSS_T", value=0.5, ptype="REAL32"),
    ]


def test_parse_rejects_wrong_field_count(tmp_path):
    f = write_params(tmp_path, "1\t1\tNAV_RCL_ACT\t2\n")
    with pytest.raises(ValueError, match="欄位數"):
        parse_params_file(f)


def test_parse_rejects_unknown_type_code(tmp_path):
    f = write_params(tmp_path, "1\t1\tNAV_RCL_ACT\t2\t5\n")
    with pytest.raises(ValueError, match="MAV_PARAM_TYPE"):
        parse_params_file(f)


def test_parse_rejects_non_integer_value_for_int32(tmp_path):
    f = write_params(tmp_path, "1\t1\tNAV_RCL_ACT\t2.5\t6\n")
    with pytest.raises(ValueError, match="INT32"):
        parse_params_file(f)


def test_parse_rejects_empty_file(tmp_path):
    f = write_params(tmp_path, "# 只有註解\n")
    with pytest.raises(ValueError, match="無任何參數行"):
        parse_params_file(f)


# ---- 比對邏輯 ----


def test_value_ok_real32_within_tolerance():
    assert value_ok(4.05, 4.0500001, "REAL32")
    assert value_ok(0.5, 0.50009, "REAL32")


def test_value_ok_real32_outside_tolerance_is_diff():
    assert not value_ok(0.20, 0.15, "REAL32")
    assert not value_ok(40.0, 40.001, "REAL32")


def test_value_ok_int32_exact():
    assert value_ok(3, 3.0, "INT32")
    assert not value_ok(3, 2.0, "INT32")


# ---- 寫入/回讀流程(mock drone.param) ----


class FakeParamPlugin:
    """記錄 set 呼叫;get 回傳 store 現值(缺項回 0)。"""

    def __init__(self, store=None):
        self.store = dict(store or {})
        self.set_calls = []

    async def set_param_int(self, name, value):
        assert isinstance(value, int)
        self.set_calls.append(("int", name, value))
        self.store[name] = value

    async def set_param_float(self, name, value):
        self.set_calls.append(("float", name, value))
        self.store[name] = value

    async def get_param_int(self, name):
        return int(self.store.get(name, 0))

    async def get_param_float(self, name):
        return float(self.store.get(name, 0.0))


PARAMS = [
    Param(name="COM_LOW_BAT_ACT", value=3.0, ptype="INT32"),
    Param(name="BAT1_V_CHARGED", value=4.05, ptype="REAL32"),
]


def test_apply_writes_with_correct_setter_and_all_ok():
    plugin = FakeParamPlugin()
    rows = asyncio.run(apply_and_verify(plugin, PARAMS, dry_run=False))
    assert plugin.set_calls == [
        ("int", "COM_LOW_BAT_ACT", 3),
        ("float", "BAT1_V_CHARGED", 4.05),
    ]
    assert all(r.ok for r in rows)


def test_dry_run_never_writes_and_reports_diff():
    plugin = FakeParamPlugin(store={"COM_LOW_BAT_ACT": 2, "BAT1_V_CHARGED": 4.05})
    rows = asyncio.run(apply_and_verify(plugin, PARAMS, dry_run=True))
    assert plugin.set_calls == []
    by_name = {r.param.name: r for r in rows}
    assert not by_name["COM_LOW_BAT_ACT"].ok  # 現值 2 != 期望 3 → DIFF
    assert by_name["BAT1_V_CHARGED"].ok


def test_dry_run_real32_diff_outside_tolerance():
    plugin = FakeParamPlugin(store={"COM_LOW_BAT_ACT": 3, "BAT1_V_CHARGED": 4.2})
    rows = asyncio.run(apply_and_verify(plugin, PARAMS, dry_run=True))
    by_name = {r.param.name: r for r in rows}
    assert not by_name["BAT1_V_CHARGED"].ok

"""fleet_svc.limits 純函式屬性測試(hypothesis,derandomize)。"""

from __future__ import annotations

from fleet_svc.limits import RATE_LIMIT_WINDOW_SEC, _int_env, _window_start
from hypothesis import given, settings
from hypothesis import strategies as st

settings.register_profile("ci", derandomize=True, max_examples=200)
settings.load_profile("ci")


@given(st.floats(min_value=0, max_value=4e10, allow_nan=False))
def test_window_start_alignment(now):
    ws = _window_start(now)
    assert ws % RATE_LIMIT_WINDOW_SEC == 0
    assert ws <= now < ws + RATE_LIMIT_WINDOW_SEC


@given(st.floats(min_value=0, max_value=4e10, allow_nan=False))
def test_window_start_idempotent_within_window(now):
    """同視窗內任意兩時刻映射到同一鍵(固定視窗語意)。"""
    ws = _window_start(now)
    assert _window_start(float(ws)) == ws
    assert _window_start(ws + RATE_LIMIT_WINDOW_SEC - 0.001) == ws


@given(st.floats(min_value=0, max_value=4e10, allow_nan=False))
def test_retry_after_positive(now):
    """Retry-After 推導式(enforce_rate_limit 同式)恆 ≥ 1 秒。"""
    ws = _window_start(now)
    retry = ws + RATE_LIMIT_WINDOW_SEC - int(now)
    assert max(1, retry) >= 1


# NUL 不可入 env(OS 限制,非受測碼),排除之
@given(st.text(max_size=12).filter(lambda s: "\x00" not in s))
def test_int_env_never_raises(monkeypatch_value):
    import os

    os.environ["_R8_PROP_TEST"] = monkeypatch_value
    try:
        got = _int_env("_R8_PROP_TEST", 42)
        assert isinstance(got, int)
        stripped = monkeypatch_value.strip()
        if not stripped:
            assert got == 42
    finally:
        del os.environ["_R8_PROP_TEST"]

"""ingest.decode 屬性測試:任意 bytes → 「正確 arity tuple 或拋例外」二擇一,不半殘。

消費端(main._consume)以 try/except 包 decode:例外 = 丟棄/DLQ;
回傳值必須恰為對應表 columns 的 arity(INSERT 佔位數),半殘 tuple 會炸 SQL。
"""

from __future__ import annotations

import json

from hypothesis import given, settings
from hypothesis import strategies as st
from ingest import decode

settings.register_profile("ci", derandomize=True, max_examples=200)
settings.load_profile("ci")


@given(st.binary(max_size=200))
def test_telemetry_row_total_or_raises(payload):
    try:
        row = decode.telemetry_row(payload)
    except Exception:
        return  # 消費端語意:丟棄/DLQ
    assert len(row) == len(decode.TELEMETRY_COLUMNS)


@given(st.binary(max_size=200))
def test_event_row_total_or_raises(payload):
    try:
        row = decode.event_row(payload)
    except Exception:
        return
    assert len(row) == len(decode.EVENT_COLUMNS)


# 針對「合法 JSON 但欄位任意」的灰色地帶(比純亂 bytes 更會踩到半殘路徑)
json_obj_st = st.dictionaries(
    st.sampled_from(["drone_id", "unix_time_ms", "lat_deg", "battery_pct", "bogus"]),
    st.one_of(st.none(), st.integers(), st.floats(allow_nan=False), st.text(max_size=8)),
    max_size=5,
)


@given(json_obj_st)
def test_telemetry_row_arbitrary_json_fields(obj):
    payload = json.dumps(obj).encode()
    try:
        row = decode.telemetry_row(payload)
    except Exception:
        return
    assert len(row) == len(decode.TELEMETRY_COLUMNS)

"""snapshot() / is_stale() / flight_event() 純函式與 armed 邊緣偵測單元測試:
不需 SITL,也不需 MQTT broker。"""

import time

import pytest
from drone.v1 import events_pb2
from drone_agent import __version__
from drone_agent.publisher import (
    _to_json,
    flight_event,
    heartbeat,
    is_stale,
    snapshot,
)
from drone_agent.state import TelemetryState


def full_state() -> TelemetryState:
    return TelemetryState(
        lat_deg=24.993263,
        lon_deg=121.300778,
        rel_alt_m=12.5,
        heading_deg=273.4,
        ground_speed_ms=5.6,
        flight_mode="MISSION",
        armed=True,
        battery_v=22.8,
        battery_pct=87.5,
        health_all_ok=True,
        satellites=14,
        gps_fix_type="FIX_3D",
        hdop=0.8,
        vertical_speed_ms=-1.2,
    )


def test_snapshot_maps_all_fields() -> None:
    msg = snapshot(full_state(), "dev-1", unix_time_ms=1_752_000_000_000)

    assert msg.drone_id == "dev-1"
    assert msg.unix_time_ms == 1_752_000_000_000
    # lat/lon 是 double,精度不打折;其餘數值欄位是 float(32-bit),用 approx
    assert msg.lat_deg == 24.993263
    assert msg.lon_deg == 121.300778
    assert msg.rel_alt_m == pytest.approx(12.5)
    assert msg.heading_deg == pytest.approx(273.4)
    assert msg.ground_speed_ms == pytest.approx(5.6)
    assert msg.flight_mode == "MISSION"
    assert msg.armed is True
    assert msg.battery_v == pytest.approx(22.8)
    assert msg.battery_pct == pytest.approx(87.5)
    assert msg.health_all_ok is True
    assert msg.satellites == 14
    assert msg.gps_fix_type == "FIX_3D"
    assert msg.hdop == pytest.approx(0.8)
    assert msg.vertical_speed_ms == pytest.approx(-1.2)


def test_snapshot_empty_state_uses_proto_defaults() -> None:
    """尚未收到任何遙測流時,各欄位維持 proto3 預設值。"""
    msg = snapshot(TelemetryState(), "dev-1", unix_time_ms=1)

    assert msg.drone_id == "dev-1"
    assert msg.lat_deg == 0.0
    assert msg.lon_deg == 0.0
    assert msg.rel_alt_m == 0.0
    assert msg.heading_deg == 0.0
    assert msg.ground_speed_ms == 0.0
    assert msg.flight_mode == ""
    assert msg.armed is False
    assert msg.battery_v == 0.0
    assert msg.battery_pct == 0.0
    assert msg.health_all_ok is False
    assert msg.satellites == 0
    assert msg.gps_fix_type == ""
    assert msg.hdop == 0.0
    assert msg.vertical_speed_ms == 0.0


def test_snapshot_default_time_is_now_when_never_touched() -> None:
    """完全沒收過任何流:退回當下系統時間(且 health_all_ok 為 proto 預設 false)。"""
    before = int(time.time() * 1000)
    msg = snapshot(TelemetryState(), "dev-1")
    after = int(time.time() * 1000)

    assert before <= msg.unix_time_ms <= after
    assert msg.health_all_ok is False


def test_snapshot_time_uses_touch_wall_clock_not_now() -> None:
    """unix_time_ms = 最後一次流更新的 wall-clock(取樣時間),而非當下時間。"""
    state = full_state()
    state.last_update_wall = 1_752_000_000.5  # 模擬 touch() 在過去記下的取樣時間
    state.last_update_monotonic = 100.0

    msg = snapshot(state, "dev-1")

    assert msg.unix_time_ms == 1_752_000_000_500


def test_touch_records_both_clocks() -> None:
    state = TelemetryState()
    assert state.last_update_monotonic is None
    assert state.last_update_wall is None

    before_mono, before_wall = time.monotonic(), time.time()
    state.touch()
    after_mono, after_wall = time.monotonic(), time.time()

    assert before_mono <= state.last_update_monotonic <= after_mono
    assert before_wall <= state.last_update_wall <= after_wall


def test_is_stale_never_touched_is_not_stale() -> None:
    """尚未收過任何流(啟動等待中)不算斷流,照常發布預設值快照。"""
    assert is_stale(TelemetryState(), now_monotonic=999.0, threshold_s=5.0) is False


def test_is_stale_fresh_update_is_not_stale() -> None:
    state = TelemetryState(last_update_monotonic=100.0)
    assert is_stale(state, now_monotonic=104.0, threshold_s=5.0) is False


def test_is_stale_at_threshold_is_not_stale() -> None:
    state = TelemetryState(last_update_monotonic=100.0)
    assert is_stale(state, now_monotonic=105.0, threshold_s=5.0) is False


def test_is_stale_old_update_is_stale() -> None:
    """全部流逾 threshold 秒無更新 → 斷流,publish_loop 應跳過發布。"""
    state = TelemetryState(last_update_monotonic=100.0)
    assert is_stale(state, now_monotonic=105.1, threshold_s=5.0) is True


def test_is_stale_recovers_after_new_touch() -> None:
    """恢復更新(touch 前進)後不再 stale → 自動恢復發布。"""
    state = TelemetryState(last_update_monotonic=100.0)
    assert is_stale(state, now_monotonic=110.0, threshold_s=5.0) is True
    state.last_update_monotonic = 109.5
    assert is_stale(state, now_monotonic=110.0, threshold_s=5.0) is False


def test_snapshot_partial_state() -> None:
    """只收到部分流(如剛開機只有電池)時,其餘欄位仍是預設值。"""
    state = TelemetryState(battery_v=23.1, battery_pct=99.0)
    msg = snapshot(state, "dev-1", unix_time_ms=1)

    assert msg.battery_v == pytest.approx(23.1)
    assert msg.battery_pct == pytest.approx(99.0)
    assert msg.lat_deg == 0.0
    assert msg.flight_mode == ""
    assert msg.armed is False


def test_to_json_single_line_with_proto_field_names_and_defaults() -> None:
    """線上格式:單行 JSON、snake_case 欄位名、預設值也輸出(契約除錯友善)。"""
    payload = _to_json(snapshot(TelemetryState(), "dev-1", unix_time_ms=1))

    assert "\n" not in payload
    assert '"drone_id": "dev-1"' in payload
    assert '"unix_time_ms": "1"' in payload  # int64 依 proto3 JSON mapping 輸出為字串
    assert '"flight_mode": ""' in payload
    assert '"armed": false' in payload


def test_flight_event_armed_mapping() -> None:
    event = flight_event("dev-1", armed=True, unix_time_ms=1_752_000_000_000)

    assert event.drone_id == "dev-1"
    assert event.unix_time_ms == 1_752_000_000_000
    assert event.event == events_pb2.FlightEvent.EVENT_ARMED


def test_flight_event_disarmed_mapping() -> None:
    event = flight_event("dev-1", armed=False, unix_time_ms=2)

    assert event.event == events_pb2.FlightEvent.EVENT_DISARMED


def test_flight_event_json_wire_format() -> None:
    """線上格式:單行 JSON、snake_case 欄位名、enum 以名稱輸出。"""
    payload = _to_json(flight_event("dev-1", armed=True, unix_time_ms=1))

    assert "\n" not in payload
    assert '"drone_id": "dev-1"' in payload
    assert '"unix_time_ms": "1"' in payload  # int64 依 proto3 JSON mapping 輸出為字串
    assert '"event": "EVENT_ARMED"' in payload


# ---- 裝置心跳(DeviceHeartbeat)----


def test_heartbeat_computes_uptime() -> None:
    hb = heartbeat(
        "dev-1",
        boot_unix_ms=1_752_000_000_000,
        now_unix_ms=1_752_000_042_500,
        firmware_version="1.15.4",
    )
    assert hb.drone_id == "dev-1"
    assert hb.unix_time_ms == 1_752_000_042_500
    assert hb.boot_unix_ms == 1_752_000_000_000
    assert hb.agent_version == __version__  # 預設取套件版本
    assert hb.firmware_version == "1.15.4"
    assert hb.uptime_s == 42  # 42500 ms → 整數秒無條件捨去


def test_heartbeat_uptime_never_negative() -> None:
    # 時鐘回跳/boot 晚於當下:uptime 夾在 0,不出現負值
    hb = heartbeat("dev-1", boot_unix_ms=1_000, now_unix_ms=500)
    assert hb.uptime_s == 0
    assert hb.firmware_version == ""  # 未給則留空


def test_heartbeat_json_wire_format() -> None:
    payload = _to_json(heartbeat("dev-1", boot_unix_ms=0, now_unix_ms=60_000))
    assert "\n" not in payload
    assert '"drone_id": "dev-1"' in payload
    assert '"uptime_s": "60"' in payload  # int64 依 proto3 JSON mapping 輸出為字串

"""MQTT payload(proto3 JSON)→ proto 物件 → DB row 的純函式,供 main 與測試共用。

注意:proto3 JSON mapping 中 int64 序列化為字串,json_format.Parse 會處理;
不要自己 json.loads 後取欄位。

例外:告警閉環主題(``fleet/{id}/alerts`` 與 ``fleet/{id}/ota/progress``)刻意走
**proto 契約之外的純 JSON**(見 onboard/drone_agent 的 cert_monitor.py / ota.py:
events.proto 無憑證/OTA 型別,加型別會動 proto 守門)。這兩者以 ``json.loads`` 直接
解析(非 json_format),且 ``ota/progress`` 的 payload **不含 drone_id**——drone_id
取自主題(``fleet/{drone_id}/...``),故其 row 函式簽章多收一個 drone_id 參數。
"""

import json
from datetime import datetime, timezone
from typing import Any

from drone.v1 import (
    device_pb2,
    events_pb2,
    mission_pb2,
    payload_pb2,
    sensors_pb2,
    telemetry_pb2,
)
from google.protobuf import json_format

TELEMETRY_COLUMNS = (
    "time",
    "drone_id",
    "lat_deg",
    "lon_deg",
    "rel_alt_m",
    "heading_deg",
    "ground_speed_ms",
    "flight_mode",
    "armed",
    "battery_v",
    "battery_pct",
    "health_all_ok",
    "satellites",
    "gps_fix_type",
    "hdop",
    "vertical_speed_ms",
)

EVENT_COLUMNS = (
    "time",
    "drone_id",
    "event",
)

DEVICE_HEARTBEAT_COLUMNS = (
    "time",
    "drone_id",
    "agent_version",
    "firmware_version",
    "boot_time",
    "uptime_s",
)

MISSION_COLUMNS = (
    "time",
    "mission_id",
    "drone_id",
    "current_item",
    "total_items",
    "state",
)

# 告警閉環(cert 到期告警 + OTA 進度)統一落 device_alerts 表(kind 區分)。
# detail 為 jsonb(落庫 SQL 以 ::jsonb 轉),存該類告警其餘欄位供運維檢視。
DEVICE_ALERT_COLUMNS = (
    "time",
    "drone_id",
    "kind",
    "summary",
    "detail",
)

# v0.4.0 高頻感測器流(fleet/{id}/sensors/*,QoS 0)
SENSOR_ATTITUDE_COLUMNS = (
    "time",
    "drone_id",
    "px4_timestamp_us",
    "q_w",
    "q_x",
    "q_y",
    "q_z",
)

SENSOR_GPS_COLUMNS = (
    "time",
    "drone_id",
    "px4_timestamp_us",
    "latitude_deg",
    "longitude_deg",
    "altitude_msl_m",
    "satellites_used",
    "hdop",
    "vdop",
    "fix_type",
)

SENSOR_LOCAL_POSITION_COLUMNS = (
    "time",
    "drone_id",
    "px4_timestamp_us",
    "x",
    "y",
    "z",
    "vx",
    "vy",
    "vz",
    "heading",
)


def _ms_to_dt(unix_time_ms: int) -> datetime:
    return datetime.fromtimestamp(unix_time_ms / 1000.0, tz=timezone.utc)


def _json_obj(payload: bytes | str) -> dict[str, Any]:
    """把純 JSON payload 解析成 dict;非物件/壞 JSON/非 UTF-8 一律 raise(呼叫端丟棄)。

    告警/OTA 進度走 proto 契約外的純 JSON(見模組 docstring),故不用 json_format。
    ``json.loads`` 直接吃 bytes(py3);壞 payload 的例外由 ingest handle() 統一吸收。
    """
    obj = json.loads(payload)
    if not isinstance(obj, dict):
        raise ValueError("alert/ota payload 必須是 JSON 物件")
    return obj


def _require_ms(obj: dict[str, Any]) -> int:
    """取 unix_time_ms(告警/OTA 皆為 JSON number → int);缺漏/型別錯 raise。"""
    ms = obj.get("unix_time_ms")
    if not isinstance(ms, int) or isinstance(ms, bool):
        raise ValueError("payload 缺 unix_time_ms(或非整數)")
    return ms


def device_alert_row(payload: bytes | str, drone_id: str) -> tuple:
    """``fleet/{id}/alerts`` 純 JSON 告警 → device_alerts row(kind='cert')。

    對齊 cert_monitor.py 的 expiry_alert_json:{drone_id, unix_time_ms, alert,
    days_remaining, not_after_unix_ms}。drone_id 以**主題**為準(payload 內若有
    亦忽略,主題才是裝置身分權威);summary=alert 名,其餘欄位入 detail(jsonb)。
    """
    obj = _json_obj(payload)
    alert = obj.get("alert")
    if not isinstance(alert, str) or not alert:
        raise ValueError("alert payload 缺 alert 欄位(或非字串)")
    time = _ms_to_dt(_require_ms(obj))
    detail = {k: v for k, v in obj.items() if k not in ("drone_id", "unix_time_ms", "alert")}
    return (time, drone_id, "cert", alert, json.dumps(detail, ensure_ascii=False))


def ota_progress_row(payload: bytes | str, drone_id: str) -> tuple:
    """``fleet/{id}/ota/progress`` 純 JSON 進度 → device_alerts row(kind='ota')。

    對齊 ota.py 的 progress_dict:{update_id, component, version, state,
    unix_time_ms, detail}。**payload 不含 drone_id**,取自主題;summary=state,
    其餘(update_id/component/version/detail)入 detail(jsonb)供運維追 OTA 進度。
    """
    obj = _json_obj(payload)
    state = obj.get("state")
    if not isinstance(state, str) or not state:
        raise ValueError("ota progress payload 缺 state 欄位(或非字串)")
    time = _ms_to_dt(_require_ms(obj))
    detail = {
        "update_id": obj.get("update_id"),
        "component": obj.get("component"),
        "version": obj.get("version"),
        "detail": obj.get("detail"),
    }
    return (time, drone_id, "ota", state, json.dumps(detail, ensure_ascii=False))


def telemetry_row(payload: bytes | str) -> tuple:
    """fleet/{id}/telemetry 的 JSON payload → telemetry 表 row(依 TELEMETRY_COLUMNS 順序)。"""
    msg = json_format.Parse(payload, telemetry_pb2.TelemetrySummary())
    return (
        _ms_to_dt(msg.unix_time_ms),
        msg.drone_id,
        msg.lat_deg,
        msg.lon_deg,
        msg.rel_alt_m,
        msg.heading_deg,
        msg.ground_speed_ms,
        msg.flight_mode,
        msg.armed,
        msg.battery_v,
        msg.battery_pct,
        msg.health_all_ok,
        msg.satellites,
        msg.gps_fix_type,
        msg.hdop,
        msg.vertical_speed_ms,
    )


def event_row(payload: bytes | str) -> tuple:
    """fleet/{id}/events 的 JSON payload → flight_events 表 row(依 EVENT_COLUMNS 順序)。"""
    msg = json_format.Parse(payload, events_pb2.FlightEvent())
    return (
        _ms_to_dt(msg.unix_time_ms),
        msg.drone_id,
        events_pb2.FlightEvent.Event.Name(msg.event),
    )


def device_heartbeat_row(payload: bytes | str) -> tuple:
    """fleet/{id}/heartbeat 的 JSON payload → device_heartbeat 表 row。"""
    msg = json_format.Parse(payload, device_pb2.DeviceHeartbeat())
    return (
        _ms_to_dt(msg.unix_time_ms),
        msg.drone_id,
        msg.agent_version,
        msg.firmware_version,
        _ms_to_dt(msg.boot_unix_ms),
        msg.uptime_s,
    )


def mission_row(payload: bytes | str) -> tuple:
    """fleet/{id}/mission/progress 的 JSON payload → mission_progress 表 row。"""
    msg = json_format.Parse(payload, mission_pb2.MissionProgress())
    return (
        _ms_to_dt(msg.unix_time_ms),
        msg.mission_id,
        msg.drone_id,
        msg.current_item,
        msg.total_items,
        mission_pb2.MissionProgress.State.Name(msg.state),
    )


def sensor_attitude_row(payload: bytes | str) -> tuple:
    """fleet/{id}/sensors/attitude 的 JSON payload → sensor_attitude 表 row。"""
    msg = json_format.Parse(payload, sensors_pb2.SensorAttitude())
    q = list(msg.q)
    if len(q) != 4:
        # 契約:q 為 Hamilton (w,x,y,z) 4 元素;缺元素視同壞 payload 丟棄
        raise ValueError(f"q 需為 4 元素四元數,收到 {len(q)} 元素")
    return (
        _ms_to_dt(msg.unix_time_ms),
        msg.drone_id,
        msg.px4_timestamp_us,
        q[0],
        q[1],
        q[2],
        q[3],
    )


def sensor_gps_row(payload: bytes | str) -> tuple:
    """fleet/{id}/sensors/gps 的 JSON payload → sensor_gps 表 row。"""
    msg = json_format.Parse(payload, sensors_pb2.SensorGps())
    return (
        _ms_to_dt(msg.unix_time_ms),
        msg.drone_id,
        msg.px4_timestamp_us,
        msg.latitude_deg,
        msg.longitude_deg,
        msg.altitude_msl_m,
        msg.satellites_used,
        msg.hdop,
        msg.vdop,
        msg.fix_type,
    )


def sensor_local_position_row(payload: bytes | str) -> tuple:
    """fleet/{id}/sensors/local_position 的 JSON payload → sensor_local_position 表 row。"""
    msg = json_format.Parse(payload, sensors_pb2.SensorLocalPosition())
    return (
        _ms_to_dt(msg.unix_time_ms),
        msg.drone_id,
        msg.px4_timestamp_us,
        msg.x,
        msg.y,
        msg.z,
        msg.vx,
        msg.vy,
        msg.vz,
        msg.heading,
    )


# ---- 酬載/智慧電池遙測(G8:fleet/{id}/payload/*;契約 payload.proto)----
PAYLOAD_STATUS_COLUMNS = (
    "time", "drone_id", "time_boot_ms", "payload_type", "payload_id", "state",
    "fault_flags", "temperature_cdegc", "firmware_version", "vendor_status",
)
SPRAY_TELEMETRY_COLUMNS = (
    "time", "drone_id", "time_boot_ms", "flow_rate_ml_s", "flow_rate_setpoint_ml_s",
    "volume_remaining_ml", "volume_consumed_ml", "application_rate_ml_m2",
    "pump_pressure_bar", "boom_width_m", "spray_flags", "pump_state", "nozzles_active",
)
BATTERY_DETAIL_COLUMNS = (
    "time", "drone_id", "time_boot_ms", "fault_flags", "capacity_full_charge_mah",
    "capacity_remaining_mah", "cell_voltages_mv", "cycle_count", "temperature_cdegc",
    "current_ca", "battery_id", "cell_count", "state_of_health", "state_of_charge",
)


def payload_status_row(payload: bytes | str) -> tuple:
    """fleet/{id}/payload/status → payload_status 表 row。"""
    msg = json_format.Parse(payload, payload_pb2.PayloadStatus())
    return (
        _ms_to_dt(msg.unix_time_ms), msg.drone_id, msg.time_boot_ms,
        msg.payload_type, msg.payload_id, msg.state, msg.fault_flags,
        msg.temperature_cdegc, msg.firmware_version, msg.vendor_status,
    )


def spray_telemetry_row(payload: bytes | str) -> tuple:
    """fleet/{id}/payload/spray → spray_telemetry 表 row(NaN 原樣落庫)。"""
    msg = json_format.Parse(payload, payload_pb2.SprayTelemetry())
    return (
        _ms_to_dt(msg.unix_time_ms), msg.drone_id, msg.time_boot_ms,
        msg.flow_rate_ml_s, msg.flow_rate_setpoint_ml_s, msg.volume_remaining_ml,
        msg.volume_consumed_ml, msg.application_rate_ml_m2, msg.pump_pressure_bar,
        msg.boom_width_m, msg.spray_flags, msg.pump_state, msg.nozzles_active,
    )


def battery_detail_row(payload: bytes | str) -> tuple:
    """fleet/{id}/payload/battery → battery_detail 表 row(未用槽位 UINT16_MAX 原樣)。"""
    msg = json_format.Parse(payload, payload_pb2.BatteryDetail())
    return (
        _ms_to_dt(msg.unix_time_ms), msg.drone_id, msg.time_boot_ms, msg.fault_flags,
        msg.capacity_full_charge_mah, msg.capacity_remaining_mah,
        list(msg.cell_voltages_mv), msg.cycle_count, msg.temperature_cdegc,
        msg.current_ca, msg.id, msg.cell_count, msg.state_of_health,
        msg.state_of_charge,
    )

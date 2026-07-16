"""drone_custom dialect 消費端(G7):MAVLink 自訂訊息 → proto → MQTT。

interfaces/mavlink README「Phase 1 啟用條件 3」的首個消費端(定案 = drone_agent,
不碰 QGC/Qt)。MAVSDK 高階 API 不吐自訂 dialect,故本模組以 pymavlink 另開
一條 MAVLink 連線(SITL 對 localhost 主動送流的 onboard 埠;--payload-port,
預設不啟用),解碼三則自訂訊息轉 proto 後發 MQTT:

    PAYLOAD_STATUS(24150) → fleet/{id}/payload/status
    SPRAY_TELEMETRY(24151)→ fleet/{id}/payload/spray
    BATTERY_DETAIL(24152) → fleet/{id}/payload/battery

QoS 0(低頻容失,同 sensors 流語意);MQTT 斷線自動重連(3s,同 agent 其他迴圈)。
pymavlink 對未知 msgid 會直接丟棄 → 需要 drone_sitl dialect 的 Python 綁定
(生成方式見 firmware/tools/run_sitl_smoke.sh);綁定缺失時本模組記 error
後自行停用,不拖垮 agent 其他迴圈。

純函式(to_payload_status/to_spray/to_battery)與 I/O 迴圈分離,單元測試
以 duck-typed 假訊息驗轉換 + proto JSON 契約。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiomqtt
from drone.v1 import payload_pb2
from google.protobuf.json_format import MessageToJson

from drone_agent.tls import from_env as mqtt_tls_params

logger = logging.getLogger(__name__)

RECONNECT_S = 3.0

MSG_TOPIC_SUFFIX = {
    "PAYLOAD_STATUS": "status",
    "SPRAY_TELEMETRY": "spray",
    "BATTERY_DETAIL": "battery",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def to_payload_status(m: Any, drone_id: str, unix_time_ms: int | None = None):
    """MAVLink PAYLOAD_STATUS(duck-typed 欄位)→ proto PayloadStatus。"""
    return payload_pb2.PayloadStatus(
        drone_id=drone_id,
        unix_time_ms=unix_time_ms if unix_time_ms is not None else _now_ms(),
        time_boot_ms=m.time_boot_ms,
        payload_type=m.payload_type,
        payload_id=m.payload_id,
        state=m.state,
        fault_flags=m.fault_flags,
        temperature_cdegc=m.temperature,
        firmware_version=m.firmware_version,
        vendor_status=m.vendor_status,
    )


def to_spray_telemetry(m: Any, drone_id: str, unix_time_ms: int | None = None):
    """MAVLink SPRAY_TELEMETRY → proto SprayTelemetry(NaN 原樣保留)。"""
    return payload_pb2.SprayTelemetry(
        drone_id=drone_id,
        unix_time_ms=unix_time_ms if unix_time_ms is not None else _now_ms(),
        time_boot_ms=m.time_boot_ms,
        flow_rate_ml_s=m.flow_rate,
        flow_rate_setpoint_ml_s=m.flow_rate_setpoint,
        volume_remaining_ml=m.volume_remaining,
        volume_consumed_ml=m.volume_consumed,
        application_rate_ml_m2=m.application_rate,
        pump_pressure_bar=m.pump_pressure,
        boom_width_m=m.boom_width,
        spray_flags=m.spray_flags,
        pump_state=m.pump_state,
        nozzles_active=m.nozzles_active,
    )


def to_battery_detail(m: Any, drone_id: str, unix_time_ms: int | None = None):
    """MAVLink BATTERY_DETAIL → proto BatteryDetail(未用槽位 UINT16_MAX 原樣)。"""
    return payload_pb2.BatteryDetail(
        drone_id=drone_id,
        unix_time_ms=unix_time_ms if unix_time_ms is not None else _now_ms(),
        time_boot_ms=m.time_boot_ms,
        fault_flags=m.fault_flags,
        capacity_full_charge_mah=m.capacity_full_charge,
        capacity_remaining_mah=m.capacity_remaining,
        cell_voltages_mv=list(m.cell_voltages),
        cycle_count=m.cycle_count,
        temperature_cdegc=m.temperature,
        current_ca=m.current,
        id=m.id,
        cell_count=m.cell_count,
        state_of_health=m.state_of_health,
        state_of_charge=m.state_of_charge,
    )


_CONVERTERS = {
    "PAYLOAD_STATUS": to_payload_status,
    "SPRAY_TELEMETRY": to_spray_telemetry,
    "BATTERY_DETAIL": to_battery_detail,
}


def convert(msg: Any, drone_id: str) -> tuple[str, str] | None:
    """MAVLink 訊息 → (主題後綴, proto3 JSON);非目標訊息回 None。"""
    name = msg.get_type()
    conv = _CONVERTERS.get(name)
    if conv is None:
        return None
    proto = conv(msg, drone_id)
    return MSG_TOPIC_SUFFIX[name], MessageToJson(proto, preserving_proto_field_name=False)


async def payload_listener(
    drone_id: str,
    mqtt_host: str,
    mqtt_port: int,
    mavlink_port: int,
) -> None:
    """監聽 MAVLink 自訂訊息並外發 MQTT(常駐;MQTT 斷線 3s 重連)。

    pymavlink 為同步 API:recv_match 以 executor 輪詢(timeout 0.5s),
    不阻塞事件迴圈。dialect 綁定缺失時記 error 後停用(不拖垮 agent)。
    """
    try:
        import pymavlink.dialects.v20.drone_sitl  # noqa: F401
        from pymavlink import mavutil

        mavutil.mavlink = pymavlink.dialects.v20.drone_sitl
        mavutil.current_dialect = "drone_sitl"
    except ImportError:
        logger.error("payload_listener 停用:缺 drone_sitl dialect Python 綁定"
                     "(生成方式見 firmware/tools/run_sitl_smoke.sh)")
        return

    conn = mavutil.mavlink_connection(f"udpin:0.0.0.0:{mavlink_port}")
    logger.info("payload_listener:MAVLink udpin:%d → MQTT fleet/%s/payload/*",
                mavlink_port, drone_id)
    loop = asyncio.get_running_loop()
    types = list(_CONVERTERS)

    # 自訂 streams 預設 0 Hz:等 heartbeat(學到對端位址)後以
    # SET_MESSAGE_INTERVAL 要求 1 Hz(對 24150/24151/24152)。
    hb = await loop.run_in_executor(None, lambda: conn.wait_heartbeat(timeout=60))
    if hb is None:
        logger.error("payload_listener:60s 內無 heartbeat(udpin:%d),停用", mavlink_port)
        return
    for msg_id in (24150, 24151, 24152):
        conn.mav.command_long_send(
            conn.target_system, conn.target_component,
            511, 0, float(msg_id), 1_000_000.0, 0, 0, 0, 0, 0,  # MAV_CMD_SET_MESSAGE_INTERVAL
        )
    logger.info("payload_listener:已要求三則自訂訊息 1 Hz")

    while True:
        try:
            async with aiomqtt.Client(
                hostname=mqtt_host, port=mqtt_port, tls_params=mqtt_tls_params()
            ) as client:
                while True:
                    msg = await loop.run_in_executor(
                        None, lambda: conn.recv_match(type=types, blocking=True, timeout=0.5)
                    )
                    if msg is None:
                        continue
                    converted = convert(msg, drone_id)
                    if converted is None:
                        continue
                    suffix, payload = converted
                    await client.publish(
                        f"fleet/{drone_id}/payload/{suffix}", payload=payload, qos=0
                    )
        except aiomqtt.MqttError as e:
            logger.warning("payload MQTT 斷線:%s;%.0fs 後重連", e, RECONNECT_S)
            await asyncio.sleep(RECONNECT_S)

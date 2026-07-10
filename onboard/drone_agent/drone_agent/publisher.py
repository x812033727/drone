"""遙測快照組包與 MQTT 上報迴圈。

snapshot() 是純函式(state → proto message),與 I/O 分離、可單測;
publish_loop() 每 1/rate 秒取一次快照,以 proto3 JSON mapping 發佈到
`fleet/{drone_id}/telemetry`(QoS 1)。MQTT 斷線自動重連;重連期間的
遙測直接丟棄,Phase 0 不做補傳。
"""

import asyncio
import logging
import time

import aiomqtt
from drone.v1 import telemetry_pb2
from google.protobuf.json_format import MessageToJson

from drone_agent.state import TelemetryState

logger = logging.getLogger(__name__)

RECONNECT_DELAY_S = 3.0

# TelemetryState 與 TelemetrySummary 同名欄位(逐欄映射)
_FIELDS = (
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
)


def snapshot(
    state: TelemetryState, drone_id: str, unix_time_ms: int | None = None
) -> telemetry_pb2.TelemetrySummary:
    """把當前狀態組成一筆 TelemetrySummary。

    尚未收到的流(state 欄位為 None)不設值,維持 proto3 預設
    (數值 0 / 字串空 / 布林 false)。unix_time_ms 未給時取系統時間。
    """
    msg = telemetry_pb2.TelemetrySummary()
    msg.drone_id = drone_id
    msg.unix_time_ms = int(time.time() * 1000) if unix_time_ms is None else unix_time_ms
    for field in _FIELDS:
        value = getattr(state, field)
        if value is not None:
            setattr(msg, field, value)
    return msg


def _to_json(msg: telemetry_pb2.TelemetrySummary) -> str:
    """proto3 JSON mapping,單行、保留 proto 欄位名、預設值也輸出(除錯友善)。"""
    return MessageToJson(
        msg,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=True,
        indent=None,
    )


async def publish_loop(
    state: TelemetryState,
    mqtt_host: str,
    mqtt_port: int,
    drone_id: str,
    rate: float = 1.0,
) -> None:
    """以 rate Hz 發佈遙測摘要;斷線自動重連(期間遙測丟棄)。"""
    topic = f"fleet/{drone_id}/telemetry"
    interval = 1.0 / rate
    while True:
        try:
            async with aiomqtt.Client(hostname=mqtt_host, port=mqtt_port) as client:
                logger.info("MQTT 已連線 %s:%d,主題 %s(%.1f Hz)", mqtt_host, mqtt_port, topic, rate)
                while True:
                    payload = _to_json(snapshot(state, drone_id))
                    await client.publish(topic, payload=payload, qos=1)
                    await asyncio.sleep(interval)
        except aiomqtt.MqttError as exc:
            logger.warning("MQTT 斷線:%s;%.0f 秒後重連(期間遙測丟棄)", exc, RECONNECT_DELAY_S)
            await asyncio.sleep(RECONNECT_DELAY_S)

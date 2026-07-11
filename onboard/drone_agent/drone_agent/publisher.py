"""遙測快照組包與 MQTT 上報迴圈。

snapshot() / is_stale() 是純函式,與 I/O 分離、可單測;
publish_loop() 每 1/rate 秒取一次快照,以 proto3 JSON mapping 發佈到
`fleet/{drone_id}/telemetry`(QoS 1)。MQTT 斷線自動重連;重連期間的
遙測直接丟棄,Phase 0 不做補傳。

斷流保護:MAVSDK 遙測流可能在飛控鏈路中斷後靜默(不結束、不拋錯),
若照常發布會變成「時間戳全新、內容凍結」的殭屍遙測,掩蓋墜機/失聯。
故所有流超過 stale_timeout 秒無更新時**跳過發布**(WARNING log,
狀態轉換時各記一次),恢復更新後自動恢復發布。
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
STALE_TIMEOUT_S = 5.0

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


def is_stale(state: TelemetryState, now_monotonic: float, threshold_s: float) -> bool:
    """判定遙測是否斷流:全部流超過 threshold_s 秒無任何更新。

    完全沒收過任何流(尚在啟動等待)不算 stale —— 此時照常發布
    proto3 預設值快照,health_all_ok 必為 false,雲端可辨識。
    """
    if state.last_update_monotonic is None:
        return False
    return now_monotonic - state.last_update_monotonic > threshold_s


def snapshot(
    state: TelemetryState, drone_id: str, unix_time_ms: int | None = None
) -> telemetry_pb2.TelemetrySummary:
    """把當前狀態組成一筆 TelemetrySummary。

    尚未收到的流(state 欄位為 None)不設值,維持 proto3 預設
    (數值 0 / 字串空 / 布林 false)。unix_time_ms 未給時取
    「最後一次任一流更新」的 wall-clock 時間(契約語意:取樣時間);
    完全沒收過任何流時退回當下系統時間(此時 health_all_ok 必為 false)。
    """
    msg = telemetry_pb2.TelemetrySummary()
    msg.drone_id = drone_id
    if unix_time_ms is not None:
        msg.unix_time_ms = unix_time_ms
    elif state.last_update_wall is not None:
        msg.unix_time_ms = int(state.last_update_wall * 1000)
    else:
        msg.unix_time_ms = int(time.time() * 1000)
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
    stale_timeout: float = STALE_TIMEOUT_S,
) -> None:
    """以 rate Hz 發佈遙測摘要;斷線自動重連(期間遙測丟棄)。

    遙測斷流(全部流逾 stale_timeout 秒無更新)時跳過發布,
    避免以舊快照配新時間戳的殭屍遙測掩蓋失聯;恢復後自動續傳。
    """
    topic = f"fleet/{drone_id}/telemetry"
    interval = 1.0 / rate
    was_stale = False  # 跨 MQTT 重連保留,log 只在狀態轉換時各記一次
    while True:
        try:
            async with aiomqtt.Client(hostname=mqtt_host, port=mqtt_port) as client:
                logger.info("MQTT 已連線 %s:%d,主題 %s(%.1f Hz)", mqtt_host, mqtt_port, topic, rate)
                while True:
                    stale = is_stale(state, time.monotonic(), stale_timeout)
                    if stale and not was_stale:
                        logger.warning(
                            "遙測流逾 %.1f 秒無更新(疑似飛控鏈路中斷),暫停上報;恢復後自動續傳",
                            stale_timeout,
                        )
                    elif was_stale and not stale:
                        logger.info("遙測流恢復更新,恢復上報")
                    was_stale = stale
                    if not stale:
                        payload = _to_json(snapshot(state, drone_id))
                        await client.publish(topic, payload=payload, qos=1)
                    await asyncio.sleep(interval)
        except aiomqtt.MqttError as exc:
            logger.warning("MQTT 斷線:%s;%.0f 秒後重連(期間遙測丟棄)", exc, RECONNECT_DELAY_S)
            await asyncio.sleep(RECONNECT_DELAY_S)

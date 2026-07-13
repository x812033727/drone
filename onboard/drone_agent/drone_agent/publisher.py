"""遙測快照組包與 MQTT 上報迴圈。

snapshot() / is_stale() / flight_event() 是純函式,與 I/O 分離、可單測;
publish_loop() 每 1/rate 秒取一次快照,以 proto3 JSON mapping 發佈到
`fleet/{drone_id}/telemetry`(QoS 1)。MQTT 斷線自動重連;重連期間的
遙測直接丟棄,Phase 0 不做補傳。

飛行事件:watch_armed 偵測到 armed 邊緣時把 (armed, unix_time_ms) 排入
state.pending_events;publish_loop 共用同一 MQTT 連線,每輪把佇列全數
以 FlightEvent 發佈到 `fleet/{drone_id}/events`(QoS 1)。事件不受斷流
跳發影響(armed 邊緣本身就是流有更新的證據);發佈失敗(斷線)時事件
留在佇列,重連後補發 —— 語意 at-least-once,消費端需容忍重複。

斷流保護:MAVSDK 遙測流可能在飛控鏈路中斷後靜默(不結束、不拋錯),
若照常發布會變成「時間戳全新、內容凍結」的殭屍遙測,掩蓋墜機/失聯。
故所有流超過 stale_timeout 秒無更新時**跳過發布**(WARNING log,
狀態轉換時各記一次),恢復更新後自動恢復發布。
"""

import asyncio
import logging
import time

import aiomqtt
from drone.v1 import events_pb2, telemetry_pb2
from google.protobuf.json_format import MessageToJson
from google.protobuf.message import Message

from drone_agent.state import TelemetryState
from drone_agent.tls import from_env as _mqtt_tls

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
    "satellites",
    "gps_fix_type",
    "hdop",
    "vertical_speed_ms",
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


def flight_event(drone_id: str, armed: bool, unix_time_ms: int) -> events_pb2.FlightEvent:
    """把一筆 armed 邊緣(state.pending_events 的元素)組成 FlightEvent。"""
    return events_pb2.FlightEvent(
        drone_id=drone_id,
        unix_time_ms=unix_time_ms,
        event=(
            events_pb2.FlightEvent.EVENT_ARMED if armed else events_pb2.FlightEvent.EVENT_DISARMED
        ),
    )


def _to_json(msg: Message) -> str:
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
    events_topic = f"fleet/{drone_id}/events"
    interval = 1.0 / rate
    was_stale = False  # 跨 MQTT 重連保留,log 只在狀態轉換時各記一次
    while True:
        try:
            async with aiomqtt.Client(
                hostname=mqtt_host, port=mqtt_port, tls_params=_mqtt_tls()
            ) as client:
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
                    # 飛行事件:每輪清空佇列(不受斷流跳發影響——armed 邊緣
                    # 本身就是流有更新的證據)。先發佈成功才 popleft:發佈
                    # 中途斷線時事件留在佇列,重連後補發(at-least-once)
                    while state.pending_events:
                        armed_val, event_ms = state.pending_events[0]
                        event = flight_event(drone_id, armed_val, event_ms)
                        await client.publish(events_topic, payload=_to_json(event), qos=1)
                        state.pending_events.popleft()
                        logger.info(
                            "已發布飛行事件 %s(%d)至 %s",
                            events_pb2.FlightEvent.Event.Name(event.event),
                            event_ms,
                            events_topic,
                        )
                    await asyncio.sleep(interval)
        except aiomqtt.MqttError as exc:
            logger.warning("MQTT 斷線:%s;%.0f 秒後重連(期間遙測丟棄)", exc, RECONNECT_DELAY_S)
            await asyncio.sleep(RECONNECT_DELAY_S)

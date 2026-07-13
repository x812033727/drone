"""遙測快照組包、離線緩衝與 MQTT 上報迴圈。

snapshot() / is_stale() / flight_event() / append_bounded() 是純函式,
與 I/O 分離、可單測。取樣與發佈刻意拆成兩個協程,以支援「離線緩衝
(store-and-forward)」:

- telemetry_producer():每 1/rate 秒取一次快照,存進**有界環形緩衝**
  `buffer`(上限 max_buffer,滿了丟最舊並計數)。取樣時就把 unix_time_ms
  鎖成「取樣時間」(見 snapshot),之後不論何時補發都保留原取樣時間。
- publish_loop():連上 broker 後,把 buffer 依序(FIFO)以 proto3 JSON
  mapping 發佈到 `fleet/{drone_id}/telemetry`(QoS 1);先發佈成功才 popleft,
  發佈中途斷線的那筆留在緩衝,重連後補發 —— 語意 at-least-once,消費端
  需容忍重複(與 pending_events 同模式)。MQTT 斷線期間 producer 照常取樣
  堆進緩衝,重連後一次補發完(G24;取代 Phase 0「斷線即丟棄」)。

飛行事件:watch_armed 偵測到 armed 邊緣時把 (armed, unix_time_ms) 排入
state.pending_events;publish_loop 共用同一 MQTT 連線,每輪把佇列全數
以 FlightEvent 發佈到 `fleet/{drone_id}/events`(QoS 1)。發佈失敗(斷線)時
事件留在佇列,重連後補發 —— 語意 at-least-once,消費端需容忍重複。

斷流保護(與離線緩衝是**兩件不同的事**):MAVSDK 遙測**源**可能在飛控
鏈路中斷後靜默(不結束、不拋錯),若照常取樣會變成「時間戳全新、內容
凍結」的殭屍遙測,掩蓋墜機/失聯。故 producer 在所有流超過 stale_timeout
秒無更新時**跳過取樣(不進緩衝)**(WARNING log,狀態轉換時各記一次),
恢復更新後自動恢復。離線緩衝處理的是「MQTT 斷線」情境(遙測源仍在更新、
只是傳不出去,故要緩衝補發);斷流處理的是「遙測源斷流」情境(源本身
沒新資料,緩衝也無意義,故跳過取樣)—— 兩者不可混為一談。
"""

import asyncio
import logging
import time
from collections import deque

import aiomqtt
from drone.v1 import device_pb2, events_pb2, telemetry_pb2
from google.protobuf.json_format import MessageToJson
from google.protobuf.message import Message

from drone_agent import __version__
from drone_agent.state import TelemetryState
from drone_agent.tls import from_env as _mqtt_tls

logger = logging.getLogger(__name__)

RECONNECT_DELAY_S = 3.0
STALE_TIMEOUT_S = 5.0
HEARTBEAT_INTERVAL_S = 30.0
#: 離線緩衝上限(筆數;env TELEMETRY_BUFFER_MAX 覆寫)。600 筆 ≈ 1 Hz 十分鐘
DEFAULT_TELEMETRY_BUFFER_MAX = 600

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


def append_bounded(buffer: deque, item: object, max_len: int) -> int:
    """把 item 追加進有界環形緩衝;超過 max_len 時丟**最舊**(左端)。

    回傳本次丟棄的筆數(0 或 1)。純函式(只動傳入的 deque),供離線緩衝
    入列使用:保留插入順序(FIFO),重連後由左而右補發即為原取樣順序。
    max_len <= 0 視為「不緩衝」——item 不入列,直接算作丟棄 1 筆。
    """
    if max_len <= 0:
        return 1
    dropped = 0
    while len(buffer) >= max_len:
        buffer.popleft()
        dropped += 1
    buffer.append(item)
    return dropped


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


def heartbeat(
    drone_id: str,
    boot_unix_ms: int,
    now_unix_ms: int,
    firmware_version: str = "",
    agent_version: str = __version__,
) -> device_pb2.DeviceHeartbeat:
    """組一筆裝置心跳。uptime_s 由 boot 與當下時間推導(不早於 0)。"""
    return device_pb2.DeviceHeartbeat(
        drone_id=drone_id,
        unix_time_ms=now_unix_ms,
        agent_version=agent_version,
        firmware_version=firmware_version,
        boot_unix_ms=boot_unix_ms,
        uptime_s=max(0, (now_unix_ms - boot_unix_ms) // 1000),
    )


def _to_json(msg: Message) -> str:
    """proto3 JSON mapping,單行、保留 proto 欄位名、預設值也輸出(除錯友善)。"""
    return MessageToJson(
        msg,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=True,
        indent=None,
    )


async def telemetry_producer(
    state: TelemetryState,
    buffer: deque,
    drone_id: str,
    max_buffer: int = DEFAULT_TELEMETRY_BUFFER_MAX,
    rate: float = 1.0,
    stale_timeout: float = STALE_TIMEOUT_S,
) -> None:
    """以 rate Hz 取樣快照存進離線緩衝(不論 MQTT 是否連線);斷流時跳過取樣。

    與 MQTT 連線狀態解耦:斷線期間 producer 照常把快照堆進 buffer,由
    publish_loop 重連後補發(store-and-forward)。遙測**源**斷流(全部流逾
    stale_timeout 秒無更新)時跳過取樣(不進緩衝),避免殭屍遙測占滿緩衝;
    恢復更新後自動續取。緩衝滿了丟最舊並累計丟棄數(狀態轉換/里程碑記 log)。
    """
    interval = 1.0 / rate
    was_stale = False
    dropped_total = 0
    while True:
        stale = is_stale(state, time.monotonic(), stale_timeout)
        if stale and not was_stale:
            logger.warning(
                "遙測流逾 %.1f 秒無更新(疑似飛控鏈路中斷),暫停取樣;恢復後自動續取",
                stale_timeout,
            )
        elif was_stale and not stale:
            logger.info("遙測流恢復更新,恢復取樣")
        was_stale = stale
        if not stale:
            dropped = append_bounded(buffer, snapshot(state, drone_id), max_buffer)
            if dropped:
                dropped_total += dropped
                # 緩衝溢位(離線過久)只在首筆與每 100 筆記一次,不逐筆刷 log
                if dropped_total == 1 or dropped_total % 100 == 0:
                    logger.warning(
                        "離線緩衝已滿(上限 %d),丟棄最舊遙測;累計丟棄 %d 筆",
                        max_buffer,
                        dropped_total,
                    )
        await asyncio.sleep(interval)


async def publish_loop(
    state: TelemetryState,
    buffer: deque,
    mqtt_host: str,
    mqtt_port: int,
    drone_id: str,
    rate: float = 1.0,
) -> None:
    """連上 broker 後把離線緩衝 FIFO 補發到遙測主題;斷線自動重連(緩衝保留)。

    每輪把 buffer 內既有快照依序發完(先發佈成功才 popleft;中途斷線的那筆
    留在緩衝,重連後補發 —— at-least-once),再清空飛行事件佇列,然後 sleep
    一個取樣週期。重連後首輪即把整段離線期堆積的快照一次補發完。
    """
    topic = f"fleet/{drone_id}/telemetry"
    events_topic = f"fleet/{drone_id}/events"
    interval = 1.0 / rate
    while True:
        try:
            async with aiomqtt.Client(
                hostname=mqtt_host, port=mqtt_port, tls_params=_mqtt_tls()
            ) as client:
                logger.info("MQTT 已連線 %s:%d,主題 %s(%.1f Hz)", mqtt_host, mqtt_port, topic, rate)
                while True:
                    # 遙測:把緩衝內既有快照依序補發(先發成功才 popleft;
                    # 只發本輪進入時已在緩衝的筆數,避免與 producer 競速空轉)
                    for _ in range(len(buffer)):
                        await client.publish(topic, payload=_to_json(buffer[0]), qos=1)
                        buffer.popleft()
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
            logger.warning(
                "MQTT 斷線:%s;%.0f 秒後重連(遙測續存離線緩衝,重連後補發)",
                exc,
                RECONNECT_DELAY_S,
            )
            await asyncio.sleep(RECONNECT_DELAY_S)


async def heartbeat_loop(
    mqtt_host: str,
    mqtt_port: int,
    drone_id: str,
    firmware_version: str = "",
    interval: float = HEARTBEAT_INTERVAL_S,
    boot_unix_ms: int | None = None,
) -> None:
    """定期發佈裝置心跳到 `fleet/{drone_id}/heartbeat`(QoS 1)。

    與遙測分開的獨立連線與迴圈:心跳證明 agent 程序存活,即使 MAVSDK
    遙測斷流(飛控鏈路中斷)也照發——雲端據此區分「機掛了」與「鏈路掛了」。
    斷線自動重連;boot_unix_ms 於首次進入時鎖定(agent 啟動時間近似)。
    """
    if boot_unix_ms is None:
        boot_unix_ms = int(time.time() * 1000)
    topic = f"fleet/{drone_id}/heartbeat"
    while True:
        try:
            async with aiomqtt.Client(hostname=mqtt_host, port=mqtt_port) as client:
                logger.info("MQTT 已連線,心跳主題 %s(每 %.0f 秒)", topic, interval)
                while True:
                    msg = heartbeat(
                        drone_id, boot_unix_ms, int(time.time() * 1000), firmware_version
                    )
                    await client.publish(topic, payload=_to_json(msg), qos=1)
                    await asyncio.sleep(interval)
        except aiomqtt.MqttError as exc:
            logger.warning("心跳 MQTT 斷線:%s;%.0f 秒後重連", exc, RECONNECT_DELAY_S)
            await asyncio.sleep(RECONNECT_DELAY_S)

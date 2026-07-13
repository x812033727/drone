"""Phase 0 遙測 ingest:訂閱 MQTT(proto3 JSON)→ 寫入 TimescaleDB。

Phase 0 雛形,Phase 1 由 Go gateway 取代(見 cloud/ingest/README.md)。
環境變數:MQTT_HOST / MQTT_PORT / PG_DSN。
"""

import asyncio
import logging
import os

import aiomqtt
import asyncpg

from ingest import decode, metrics

log = logging.getLogger("ingest")

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
# mTLS client 憑證(C2b):三者皆設則走 TLS(對 mqtt-tls 8883 監聽器);
# 未設則明文(向後相容)。ingest 用後端服務身分(backend 憑證,ACL 讀全機隊)。
MQTT_TLS_CA = os.environ.get("MQTT_TLS_CA")
MQTT_TLS_CERT = os.environ.get("MQTT_TLS_CERT")
MQTT_TLS_KEY = os.environ.get("MQTT_TLS_KEY")
PG_DSN = os.environ.get("PG_DSN", "postgresql://drone:dronedev@localhost:5432/drone")
RECONNECT_S = 5
PG_CONNECT_ATTEMPTS = 30  # 啟動時等 DB 就緒:最多 30 次、每 2 秒
PG_CONNECT_RETRY_S = 2
PG_COMMAND_TIMEOUT_S = 10  # DB black-hole 防護:單一指令逾時
MQTT_MAX_QUEUED_IN = 10_000  # 入站佇列上限,滿了丟新訊息,避免 DB 慢時記憶體無限成長

def _tls_from_env() -> "aiomqtt.TLSParameters | None":
    """MQTT_TLS_CA/CERT/KEY 三者皆設 → mTLS 參數;否則 None(明文,向後相容)。"""
    if MQTT_TLS_CA and MQTT_TLS_CERT and MQTT_TLS_KEY:
        return aiomqtt.TLSParameters(
            ca_certs=MQTT_TLS_CA, certfile=MQTT_TLS_CERT, keyfile=MQTT_TLS_KEY
        )
    return None


def _insert_sql(table: str, columns: tuple[str, ...]) -> str:
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(f'${i + 1}' for i in range(len(columns)))})"
    )


TELEMETRY_SQL = _insert_sql("telemetry", decode.TELEMETRY_COLUMNS)
MISSION_SQL = _insert_sql("mission_progress", decode.MISSION_COLUMNS)
EVENT_SQL = _insert_sql("flight_events", decode.EVENT_COLUMNS)
DEVICE_HEARTBEAT_SQL = _insert_sql("device_heartbeat", decode.DEVICE_HEARTBEAT_COLUMNS)
SENSOR_ATTITUDE_SQL = _insert_sql("sensor_attitude", decode.SENSOR_ATTITUDE_COLUMNS)
SENSOR_GPS_SQL = _insert_sql("sensor_gps", decode.SENSOR_GPS_COLUMNS)
SENSOR_LOCAL_POSITION_SQL = _insert_sql(
    "sensor_local_position", decode.SENSOR_LOCAL_POSITION_COLUMNS
)

# 主題路由:取主題「末兩段」查表,查不到再退回末一段(涵蓋既有主題,行為不變)。
# 末一段:fleet/{id}/telemetry、fleet/{id}/events(末兩段含 {id},查不到)
# 末兩段:fleet/{id}/mission/progress、fleet/{id}/sensors/*(v0.4.0 高頻流)
ROUTES: dict[str, tuple[str, object]] = {
    "telemetry": (TELEMETRY_SQL, decode.telemetry_row),
    "events": (EVENT_SQL, decode.event_row),
    "heartbeat": (DEVICE_HEARTBEAT_SQL, decode.device_heartbeat_row),
    "mission/progress": (MISSION_SQL, decode.mission_row),
    "sensors/attitude": (SENSOR_ATTITUDE_SQL, decode.sensor_attitude_row),
    "sensors/gps": (SENSOR_GPS_SQL, decode.sensor_gps_row),
    "sensors/local_position": (SENSOR_LOCAL_POSITION_SQL, decode.sensor_local_position_row),
}


async def handle(pool: asyncpg.Pool, message: aiomqtt.Message) -> None:
    metrics.messages_inflight.inc()
    try:
        await _handle(pool, message)
    finally:
        metrics.messages_inflight.dec()


async def _handle(pool: asyncpg.Pool, message: aiomqtt.Message) -> None:
    topic = message.topic.value
    parts = topic.split("/")
    key2 = "/".join(parts[-2:])
    route = ROUTES.get(key2) or ROUTES.get(parts[-1])
    # metrics 的 route 標籤:用有匹配到的主題末段,無匹配則 "unknown"(不含機隊 id,控基數)
    route_key = key2 if key2 in ROUTES else parts[-1] if parts[-1] in ROUTES else "unknown"
    if route is None:
        metrics.messages_total.labels(route="unknown", result="unknown_topic").inc()
        log.warning("未知主題,略過:%s", topic)
        return
    sql, to_row = route

    try:
        payload = bytes(message.payload)
        row = to_row(payload)
    except Exception:
        # 壞 payload(JSON 解析失敗、enum 超界、時間戳超界、非 UTF-8……)
        # 一律記錄後丟棄,不中斷訂閱迴圈
        metrics.messages_total.labels(route=route_key, result="decode_error").inc()
        raw = bytes(message.payload) if isinstance(message.payload, (bytes, bytearray)) else b""
        log.exception("payload 解析失敗,丟棄 topic=%s payload=%r", topic, raw[:200])
        return

    metrics.messages_total.labels(route=route_key, result="parsed").inc()
    try:
        await pool.execute(sql, *row)
        metrics.db_writes_total.labels(result="ok").inc()
    except (asyncpg.PostgresError, OSError):
        # Phase 0:DB 寫入失敗記錄後丟棄該筆,不做重試佇列(Phase 1 gateway 再補)
        metrics.db_writes_total.labels(result="error").inc()
        log.exception("DB 寫入失敗,丟棄該筆 topic=%s", topic)


async def _connect_pool() -> asyncpg.Pool:
    """啟動時建立連線池;DB 未就緒時重試,避免服務比 DB 早起就直接 crash。"""
    for attempt in range(1, PG_CONNECT_ATTEMPTS + 1):
        try:
            pool = await asyncpg.create_pool(
                PG_DSN, min_size=1, max_size=4, command_timeout=PG_COMMAND_TIMEOUT_S
            )
        except (asyncpg.PostgresError, OSError) as e:
            if attempt == PG_CONNECT_ATTEMPTS:
                raise
            log.warning(
                "PostgreSQL 連線失敗(%d/%d):%s;%d 秒後重試",
                attempt,
                PG_CONNECT_ATTEMPTS,
                e,
                PG_CONNECT_RETRY_S,
            )
            await asyncio.sleep(PG_CONNECT_RETRY_S)
        else:
            log.info("已連上 PostgreSQL")
            return pool
    raise RuntimeError("unreachable")


async def run() -> None:
    metrics.start_metrics_server()  # /metrics 埠(G13);失敗不影響消費迴圈
    pool = await _connect_pool()
    while True:
        try:
            async with aiomqtt.Client(
                MQTT_HOST,
                MQTT_PORT,
                identifier="ingest",
                max_queued_incoming_messages=MQTT_MAX_QUEUED_IN,
                tls_params=_tls_from_env(),
            ) as client:
                await client.subscribe("fleet/+/telemetry", qos=1)
                await client.subscribe("fleet/+/mission/progress", qos=1)
                await client.subscribe("fleet/+/events", qos=1)
                await client.subscribe("fleet/+/heartbeat", qos=1)
                # v0.4.0 高頻感測器流:QoS 0 容失(與 1 Hz 摘要 QoS 1 區隔)
                await client.subscribe("fleet/+/sensors/+", qos=0)
                log.info("已連上 MQTT %s:%s,開始收訊", MQTT_HOST, MQTT_PORT)
                async for message in client.messages:
                    await handle(pool, message)
        except aiomqtt.MqttError as e:
            log.warning("MQTT 連線中斷:%s;%s 秒後重連", e, RECONNECT_S)
            await asyncio.sleep(RECONNECT_S)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()

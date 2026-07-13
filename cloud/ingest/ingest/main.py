"""Phase 0 遙測 ingest:訂閱 MQTT(proto3 JSON)→ 寫入 TimescaleDB。

Phase 0 雛形,Phase 1 由 Go gateway 取代(見 cloud/ingest/README.md)。
環境變數:MQTT_HOST / MQTT_PORT / PG_DSN。
"""

import asyncio
import json
import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone

import aiomqtt
import asyncpg

from ingest import decode, health, metrics

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
# DB 寫入有限次重試(G21):吸收短暫斷線/重啟,不做無限佇列阻塞消費迴圈。
# 最壞額外延遲 = BASE*(1+2) ≈ 0.3s(3 次嘗試、指數退避),之後轉 DLQ。
DB_WRITE_ATTEMPTS = 3
DB_RETRY_BASE_S = 0.1
# 死信佇列(DLQ):重試耗盡的訊息落地成 JSONL,不靜默丟棄(at-least-once 精神)。
# 預設相對 cwd(容器內 /app,Dockerfile 已 chown 可寫);可用環境變數覆寫。
DLQ_PATH = os.environ.get("INGEST_DLQ_PATH", "ingest_dlq.jsonl")

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
# 告警閉環:detail 欄為 jsonb,需 ::jsonb 轉(payload 純 JSON,同 fleet_svc audit 慣例);
# 故不走 _insert_sql（那產無轉型的 $n），改手寫把最後一欄 cast 成 jsonb。
DEVICE_ALERT_SQL = (
    "INSERT INTO device_alerts (time, drone_id, kind, summary, detail) "
    "VALUES ($1, $2, $3, $4, $5::jsonb)"
)

# 主題路由:取主題「末兩段」查表,查不到再退回末一段(涵蓋既有主題,行為不變)。
# 末一段:fleet/{id}/telemetry、fleet/{id}/events(末兩段含 {id},查不到)
# 末兩段:fleet/{id}/mission/progress、fleet/{id}/sensors/*(v0.4.0 高頻流)
ROUTES: dict[str, tuple[str, Callable[[bytes | str], tuple]]] = {
    "telemetry": (TELEMETRY_SQL, decode.telemetry_row),
    "events": (EVENT_SQL, decode.event_row),
    "heartbeat": (DEVICE_HEARTBEAT_SQL, decode.device_heartbeat_row),
    "mission/progress": (MISSION_SQL, decode.mission_row),
    "sensors/attitude": (SENSOR_ATTITUDE_SQL, decode.sensor_attitude_row),
    "sensors/gps": (SENSOR_GPS_SQL, decode.sensor_gps_row),
    "sensors/local_position": (SENSOR_LOCAL_POSITION_SQL, decode.sensor_local_position_row),
}

# 告警閉環路由(proto 契約外的純 JSON;payload 可能不含 drone_id,故 row 函式多收
# 主題解出的 drone_id)。與 ROUTES 分開因簽章不同——ROUTES 的 row 只吃 payload,
# 這裡吃 (payload, drone_id)。查表鍵同樣走「末兩段」優先、退回末一段:
# fleet/{id}/alerts → 末一段 alerts;fleet/{id}/ota/progress → 末兩段 ota/progress。
TOPIC_ROUTES: dict[str, tuple[str, Callable[[bytes | str, str], tuple]]] = {
    "alerts": (DEVICE_ALERT_SQL, decode.device_alert_row),
    "ota/progress": (DEVICE_ALERT_SQL, decode.ota_progress_row),
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
    payload = bytes(message.payload)

    # 1) 告警閉環(payload 純 JSON,drone_id 取自主題 fleet/{drone_id}/...)。
    troute = TOPIC_ROUTES.get(key2) or TOPIC_ROUTES.get(parts[-1])
    if troute is not None:
        t_key = key2 if key2 in TOPIC_ROUTES else parts[-1]
        drone_id = parts[1] if len(parts) >= 3 else ""
        t_sql, t_row = troute
        await _decode_and_write(pool, t_sql, lambda: t_row(payload, drone_id), topic, t_key)
        return

    # 2) 既有 proto3 JSON 遙測/任務/事件/心跳/感測器路由(row 只吃 payload)。
    route = ROUTES.get(key2) or ROUTES.get(parts[-1])
    # metrics 的 route 標籤:用有匹配到的主題末段,無匹配則 "unknown"(不含機隊 id,控基數)
    route_key = key2 if key2 in ROUTES else parts[-1] if parts[-1] in ROUTES else "unknown"
    if route is None:
        metrics.messages_total.labels(route="unknown", result="unknown_topic").inc()
        log.warning("未知主題,略過:%s", topic)
        return
    sql, to_row = route
    await _decode_and_write(pool, sql, lambda: to_row(payload), topic, route_key)


async def _decode_and_write(
    pool: asyncpg.Pool,
    sql: str,
    make_row: Callable[[], tuple],
    topic: str,
    route_key: str,
) -> None:
    """解析 row(壞 payload 記錄後丟棄,不中斷迴圈)→ 落庫(含重試/DLQ)。

    解析與落庫的共用尾段;proto 路由與告警路由差別僅在 make_row 如何取得 row。
    """
    try:
        row = make_row()
    except Exception:
        # 壞 payload(JSON 解析失敗、enum 超界、時間戳超界、非 UTF-8、缺必要欄位……)
        # 一律記錄後丟棄,不中斷訂閱迴圈
        metrics.messages_total.labels(route=route_key, result="decode_error").inc()
        log.exception("payload 解析失敗,丟棄 topic=%s", topic)
        return
    metrics.messages_total.labels(route=route_key, result="parsed").inc()
    await _write_row(pool, sql, row, topic, route_key)


async def _write_row(
    pool: asyncpg.Pool, sql: str, row: tuple, topic: str, route_key: str
) -> None:
    """DB 寫入 + 有限次指數退避重試(G21);耗盡則落 DLQ,不靜默丟棄。"""
    delay = DB_RETRY_BASE_S
    last: Exception | None = None
    for attempt in range(1, DB_WRITE_ATTEMPTS + 1):
        try:
            await pool.execute(sql, *row)
            metrics.db_writes_total.labels(result="ok").inc()
            health.set_db(True)
            return
        except (asyncpg.PostgresError, OSError) as e:
            last = e
            if attempt < DB_WRITE_ATTEMPTS:
                log.warning(
                    "DB 寫入失敗(%d/%d)topic=%s:%s;%.2fs 後重試",
                    attempt, DB_WRITE_ATTEMPTS, topic, e, delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
    # 重試耗盡:記錄 + 落 DLQ(不靜默丟棄)。連線層失敗(OSError)標記 DB 未就緒,
    # 供 readiness 探針反映;約束/資料類(PostgresError)不代表 DB 掛,不動狀態。
    metrics.db_writes_total.labels(result="error").inc()
    if isinstance(last, OSError):
        health.set_db(False)
    log.error("DB 寫入重試 %d 次耗盡,轉入 DLQ topic=%s:%s", DB_WRITE_ATTEMPTS, topic, last)
    _write_dlq(topic, route_key, sql, row)


def _write_dlq(topic: str, route_key: str, sql: str, row: tuple) -> None:
    """把寫不進 DB 的訊息落地成 JSONL 死信;DLQ 本身失敗只記錄(訊息確實無處可存)。"""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "route": route_key,
        "sql": sql,
        "row": list(row),
    }
    try:
        parent = os.path.dirname(DLQ_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(DLQ_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        metrics.dlq_total.labels(route=route_key).inc()
    except OSError:
        log.exception("DLQ 落地失敗 topic=%s(訊息已無處可存)", topic)


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
    health.start_health_server()  # health 埠(G21);失敗不影響消費迴圈
    pool = await _connect_pool()
    health.set_db(True)  # pool 已建;之後由每筆寫入結果反映即時狀態
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
                # 告警閉環(proto 契約外純 JSON,QoS 1 at-least-once):
                # cert 到期告警(cert_monitor.py)+ OTA 進度(ota.py)——原雲端無訂閱者。
                await client.subscribe("fleet/+/alerts", qos=1)
                await client.subscribe("fleet/+/ota/progress", qos=1)
                log.info("已連上 MQTT %s:%s,開始收訊", MQTT_HOST, MQTT_PORT)
                health.set_mqtt(True)  # 訂閱完成 → readiness 就緒
                async for message in client.messages:
                    await handle(pool, message)
        except aiomqtt.MqttError as e:
            health.set_mqtt(False)  # 斷線 → readiness 不就緒(liveness /livez 仍 200)
            log.warning("MQTT 連線中斷:%s;%s 秒後重連", e, RECONNECT_S)
            await asyncio.sleep(RECONNECT_S)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()

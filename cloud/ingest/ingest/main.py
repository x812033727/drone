"""Phase 0 遙測 ingest:訂閱 MQTT(proto3 JSON)→ 寫入 TimescaleDB。

Phase 0 雛形,Phase 1 由 Go gateway 取代(見 cloud/ingest/README.md)。
環境變數:MQTT_HOST / MQTT_PORT / PG_DSN。
"""

import asyncio
import logging
import os

import aiomqtt
import asyncpg

from ingest import decode

log = logging.getLogger("ingest")

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
PG_DSN = os.environ.get("PG_DSN", "postgresql://drone:dronedev@localhost:5432/drone")
RECONNECT_S = 5
PG_CONNECT_ATTEMPTS = 30  # 啟動時等 DB 就緒:最多 30 次、每 2 秒
PG_CONNECT_RETRY_S = 2
PG_COMMAND_TIMEOUT_S = 10  # DB black-hole 防護:單一指令逾時
MQTT_MAX_QUEUED_IN = 10_000  # 入站佇列上限,滿了丟新訊息,避免 DB 慢時記憶體無限成長

TELEMETRY_SQL = (
    f"INSERT INTO telemetry ({', '.join(decode.TELEMETRY_COLUMNS)}) "
    f"VALUES ({', '.join(f'${i + 1}' for i in range(len(decode.TELEMETRY_COLUMNS)))})"
)
MISSION_SQL = (
    f"INSERT INTO mission_progress ({', '.join(decode.MISSION_COLUMNS)}) "
    f"VALUES ({', '.join(f'${i + 1}' for i in range(len(decode.MISSION_COLUMNS)))})"
)


async def handle(pool: asyncpg.Pool, message: aiomqtt.Message) -> None:
    topic = message.topic.value
    if topic.endswith("/telemetry"):
        sql, to_row = TELEMETRY_SQL, decode.telemetry_row
    elif topic.endswith("/mission/progress"):
        sql, to_row = MISSION_SQL, decode.mission_row
    else:
        log.warning("未知主題,略過:%s", topic)
        return

    try:
        payload = bytes(message.payload)
        row = to_row(payload)
    except Exception:
        # 壞 payload(JSON 解析失敗、enum 超界、時間戳超界、非 UTF-8……)
        # 一律記錄後丟棄,不中斷訂閱迴圈
        raw = bytes(message.payload) if isinstance(message.payload, (bytes, bytearray)) else b""
        log.exception("payload 解析失敗,丟棄 topic=%s payload=%r", topic, raw[:200])
        return

    try:
        await pool.execute(sql, *row)
    except (asyncpg.PostgresError, OSError):
        # Phase 0:DB 寫入失敗記錄後丟棄該筆,不做重試佇列(Phase 1 gateway 再補)
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
    pool = await _connect_pool()
    while True:
        try:
            async with aiomqtt.Client(
                MQTT_HOST,
                MQTT_PORT,
                identifier="ingest",
                max_queued_incoming_messages=MQTT_MAX_QUEUED_IN,
            ) as client:
                await client.subscribe("fleet/+/telemetry", qos=1)
                await client.subscribe("fleet/+/mission/progress", qos=1)
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

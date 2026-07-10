"""Phase 0 遙測 ingest:訂閱 MQTT(proto3 JSON)→ 寫入 TimescaleDB。

Phase 0 雛形,Phase 1 由 Go gateway 取代(見 cloud/ingest/README.md)。
環境變數:MQTT_HOST / MQTT_PORT / PG_DSN。
"""

import asyncio
import logging
import os

import aiomqtt
import asyncpg
from google.protobuf.json_format import ParseError

from ingest import decode

log = logging.getLogger("ingest")

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
PG_DSN = os.environ.get("PG_DSN", "postgresql://drone:dronedev@localhost:5432/drone")
RECONNECT_S = 5

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
    payload = bytes(message.payload)
    try:
        if topic.endswith("/telemetry"):
            await pool.execute(TELEMETRY_SQL, *decode.telemetry_row(payload))
        elif topic.endswith("/mission/progress"):
            await pool.execute(MISSION_SQL, *decode.mission_row(payload))
        else:
            log.warning("未知主題,略過:%s", topic)
    except ParseError:
        # 壞 payload 記錄後丟棄,不中斷訂閱迴圈
        log.exception("payload 解析失敗 topic=%s payload=%r", topic, payload[:200])


async def run() -> None:
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=4)
    log.info("已連上 PostgreSQL")
    while True:
        try:
            async with aiomqtt.Client(MQTT_HOST, MQTT_PORT, identifier="ingest") as client:
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

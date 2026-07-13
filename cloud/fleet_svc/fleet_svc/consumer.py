"""遙測消費者:訂閱 fleet/+/telemetry → upsert device_state + 餵 SSE 中樞。

沿用 cloud/ingest 的重連/壞 payload 丟棄範式。飛安不依賴雲端,遺失樣本無害。
"""

from __future__ import annotations

import asyncio
import logging

import aiomqtt
import asyncpg

from fleet_svc.hub import TelemetryHub
from fleet_svc.telemetry import parse_telemetry

log = logging.getLogger("fleet_svc.consumer")

RECONNECT_S = 5
MQTT_MAX_QUEUED_IN = 10_000

UPSERT_SQL = """
INSERT INTO fleet.device_state
    (drone_id, last_seen, lat_deg, lon_deg, rel_alt_m, battery_pct, flight_mode, armed)
VALUES ($1, now(), $2, $3, $4, $5, $6, $7)
ON CONFLICT (drone_id) DO UPDATE SET
    last_seen = now(), lat_deg = EXCLUDED.lat_deg, lon_deg = EXCLUDED.lon_deg,
    rel_alt_m = EXCLUDED.rel_alt_m, battery_pct = EXCLUDED.battery_pct,
    flight_mode = EXCLUDED.flight_mode, armed = EXCLUDED.armed
"""


async def _handle(pool: asyncpg.Pool, hub: TelemetryHub, message: aiomqtt.Message) -> None:
    try:
        data = parse_telemetry(bytes(message.payload))
    except Exception:
        raw = bytes(message.payload) if isinstance(message.payload, (bytes, bytearray)) else b""
        log.exception(
            "遙測 payload 解析失敗,丟棄 topic=%s payload=%r", message.topic.value, raw[:200]
        )
        return
    hub.publish(data)
    try:
        await pool.execute(
            UPSERT_SQL,
            data["drone_id"],
            data["lat_deg"],
            data["lon_deg"],
            data["rel_alt_m"],
            data["battery_pct"],
            data["flight_mode"],
            data["armed"],
        )
    except (asyncpg.PostgresError, OSError):
        # 監看用途,寫失敗記錄後丟棄該筆(SSE 已即時推送)
        log.exception("device_state upsert 失敗,丟棄 drone_id=%s", data.get("drone_id"))


async def run_consumer(
    pool: asyncpg.Pool, hub: TelemetryHub, mqtt_host: str, mqtt_port: int
) -> None:
    while True:
        try:
            async with aiomqtt.Client(
                mqtt_host,
                mqtt_port,
                identifier="fleet-svc-consumer",
                max_queued_incoming_messages=MQTT_MAX_QUEUED_IN,
            ) as client:
                await client.subscribe("fleet/+/telemetry", qos=1)
                log.info("消費者已連上 MQTT %s:%s", mqtt_host, mqtt_port)
                async for message in client.messages:
                    await _handle(pool, hub, message)
        except aiomqtt.MqttError as e:
            log.warning("消費者 MQTT 中斷:%s;%s 秒後重連", e, RECONNECT_S)
            await asyncio.sleep(RECONNECT_S)
        except asyncio.CancelledError:
            log.info("消費者停止")
            raise

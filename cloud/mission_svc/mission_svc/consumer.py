"""進度消費者:訂閱 fleet/+/mission/progress → 更新 mission 權威狀態(首個終態為準)。

沿用 ingest 的重連/壞 payload 丟棄範式。mission-svc 擁任務生命週期;
cloud/ingest 仍保留 TSDB 進度歷史供 Grafana(職責分離,不衝突)。
"""

from __future__ import annotations

import asyncio
import logging

import aiomqtt
import asyncpg
from drone.v1 import mission_pb2
from google.protobuf import json_format

from mission_svc import repo
from mission_svc.dispatch import PROGRESS_TO_STATUS, progress_state_name
from mission_svc.tls import from_env as _mqtt_tls

log = logging.getLogger("mission_svc.consumer")

RECONNECT_S = 5


async def _handle(pool: asyncpg.Pool, message: aiomqtt.Message) -> None:
    try:
        msg = json_format.Parse(bytes(message.payload), mission_pb2.MissionProgress())
    except Exception:
        log.exception("進度 payload 解析失敗,丟棄 topic=%s", message.topic.value)
        return
    status = PROGRESS_TO_STATUS.get(progress_state_name(msg.state))
    if status is None:
        return  # STATE_UNSPECIFIED 等,略過
    try:
        async with pool.acquire() as conn:
            await repo.apply_progress(
                conn, msg.mission_id, status, msg.current_item, msg.total_items
            )
    except (asyncpg.PostgresError, OSError):
        log.exception("進度更新失敗,丟棄 mission_id=%s", msg.mission_id)


async def run_consumer(pool: asyncpg.Pool, mqtt_host: str, mqtt_port: int) -> None:
    while True:
        try:
            async with aiomqtt.Client(
                mqtt_host, mqtt_port, identifier="mission-svc-consumer", tls_params=_mqtt_tls()
            ) as client:
                await client.subscribe("fleet/+/mission/progress", qos=1)
                log.info("進度消費者已連上 MQTT %s:%s", mqtt_host, mqtt_port)
                async for message in client.messages:
                    await _handle(pool, message)
        except aiomqtt.MqttError as e:
            log.warning("進度消費者 MQTT 中斷:%s;%s 秒後重連", e, RECONNECT_S)
            await asyncio.sleep(RECONNECT_S)
        except asyncio.CancelledError:
            log.info("進度消費者停止")
            raise

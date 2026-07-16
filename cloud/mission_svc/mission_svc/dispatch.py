"""派遣核心:MissionPlan/MissionCommand proto3 JSON 組裝 + MQTT 發布 + 進度狀態映射。

沿用 tools/dispatch_mission.py 的契約與 wire 慣例(proto3 JSON,QoS 1)。
純函式(JSON 組裝、狀態映射)可單測;MQTT 發布為短連線(派遣不頻繁)。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import aiomqtt
from drone.v1 import mission_pb2
from google.protobuf import json_format

from mission_svc.tls import from_env as _mqtt_tls

log = logging.getLogger("mission_svc.dispatch")

_STATE = mission_pb2.MissionProgress.State
_CMD = mission_pb2.MissionCommand

# MissionProgress.State 名稱 → mission.status
PROGRESS_TO_STATUS: dict[str, str] = {
    "STATE_RECEIVED": "received",
    "STATE_UPLOADED": "uploaded",
    "STATE_IN_PROGRESS": "in_progress",
    "STATE_PAUSED": "paused",
    "STATE_COMPLETED": "completed",
    "STATE_FAILED": "failed",
}
TERMINAL_STATUSES = frozenset({"completed", "failed"})

# API command 種類 → MissionCommand.Command
CTRL_COMMANDS = {
    "pause": _CMD.COMMAND_PAUSE,
    "resume": _CMD.COMMAND_RESUME,
    "abort": _CMD.COMMAND_ABORT,
}


def build_mission_plan_json(
    mission_id: str, waypoints: list[dict[str, Any]], rtl_after_last: bool
) -> str:
    """組 MissionPlan proto3 JSON(發到 fleet/{drone_id}/cmd/mission)。"""
    plan = mission_pb2.MissionPlan(mission_id=mission_id, rtl_after_last=rtl_after_last)
    for w in waypoints:
        plan.waypoints.add(
            lat_deg=w["lat_deg"],
            lon_deg=w["lon_deg"],
            rel_alt_m=w.get("rel_alt_m", 0.0),
            hold_s=w.get("hold_s", 0.0),
            speed_ms=w.get("speed_ms", 0.0),
        )
    return json_format.MessageToJson(plan, indent=None)


def build_mission_command_json(mission_id: str, command: str, unix_time_ms: int = 0) -> str:
    """組 MissionCommand proto3 JSON(發到 fleet/{drone_id}/cmd/mission_ctrl)。"""
    if command not in CTRL_COMMANDS:
        raise ValueError(f"未知命令:{command}")
    msg = mission_pb2.MissionCommand(
        mission_id=mission_id, command=CTRL_COMMANDS[command], unix_time_ms=unix_time_ms
    )
    return json_format.MessageToJson(msg, indent=None)


def progress_state_name(state_value: int) -> str:
    """MissionProgress.State enum 值 → 名稱(供消費者映射)。"""
    return _STATE.Name(state_value)


def _pub_identifier(prefix: str) -> str:
    """每次連線用唯一 client-id。派遣為短連線,固定 client-id 在並發時會互相
    踢線(MQTT broker 同 id 只留最新一條)→ QoS1 PUBACK 遺失 → publish 逾時 500。
    保留描述性前綴供 log/ACL 前綴辨識,尾綴唯一以避免踢線。"""
    return f"{prefix}-{uuid4().hex[:12]}"


async def _publish_once(
    host: str, port: int, identifier_prefix: str, topic: str, payload: str
) -> None:
    async with aiomqtt.Client(
        host, port, identifier=_pub_identifier(identifier_prefix), tls_params=_mqtt_tls()
    ) as client:
        await client.publish(topic, payload, qos=1)


async def publish_mission_plan(
    host: str, port: int, drone_id: str, plan_json: str
) -> None:
    await _publish_once(
        host, port, "mission-svc-pub", f"fleet/{drone_id}/cmd/mission", plan_json
    )
    log.info("已派遣任務至 fleet/%s/cmd/mission", drone_id)


async def publish_mission_command(
    host: str, port: int, drone_id: str, cmd_json: str
) -> None:
    await _publish_once(
        host, port, "mission-svc-ctrl", f"fleet/{drone_id}/cmd/mission_ctrl", cmd_json
    )
    log.info("已發送任務命令至 fleet/%s/cmd/mission_ctrl", drone_id)

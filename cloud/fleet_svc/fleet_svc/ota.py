"""OTA 觸發:cmd/ota JSON 組裝 + MQTT 發布(雲端發起端,原缺;對照 mission_svc.dispatch)。

onboard/drone_agent/drone_agent/ota.py 訂閱 ``fleet/{drone_id}/cmd/ota`` 並回報
``fleet/{drone_id}/ota/progress``,但雲端**無任何發起端**。本模組補上發起端:把
fleet-svc 的 DeviceOtaRequest 組成 ota.py parse_ota_command 期望的**純 JSON**(非 proto,
與 ota.py 同策略——events.proto 無 OTA 型別,刻意不動 proto),經短連線 aiomqtt 發布。

payload 欄位嚴格對齊 ota.py 的 OtaCommand:
- install:action/update_id/component/version/url/sha256/signature(+ 選填 size);
- pause/resume/rollback:action/update_id(rollback 可帶 component)。
純函式(JSON 組裝)可單測;MQTT 發布為短連線(觸發不頻繁,同 dispatch 慣例)。
"""

from __future__ import annotations

import json
import logging

import aiomqtt

from fleet_svc.models import DeviceOtaRequest, OtaAction
from fleet_svc.tls import from_env as _mqtt_tls

log = logging.getLogger("fleet_svc.ota")


def build_ota_command_json(req: DeviceOtaRequest) -> str:
    """把 DeviceOtaRequest 組成 cmd/ota 的純 JSON(對齊 ota.py parse_ota_command)。

    install 帶完整套件欄位(size 僅在有給時帶,對齊 ota.py 的選填語意);
    控制指令(pause/resume/rollback)只帶 action/update_id,rollback 另可帶 component。
    模型層(DeviceOtaRequest 的 model_validator)已保證 install 欄位齊備 + sha256 格式,
    故此處不再重驗,只負責序列化。
    """
    payload: dict[str, object] = {"action": req.action.value, "update_id": req.update_id}
    if req.action is OtaAction.install:
        payload["component"] = req.component.value if req.component else ""
        payload["version"] = req.version
        payload["url"] = req.url
        payload["sha256"] = req.sha256
        payload["signature"] = req.signature
        if req.size is not None:
            payload["size"] = req.size
    elif req.action is OtaAction.rollback and req.component is not None:
        payload["component"] = req.component.value
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


async def publish_ota_command(host: str, port: int, serial: str, cmd_json: str) -> None:
    """發布 cmd/ota 到 ``fleet/{serial}/cmd/ota``(QoS 1;短連線,對照 dispatch)。"""
    async with aiomqtt.Client(
        host, port, identifier="fleet-svc-ota", tls_params=_mqtt_tls()
    ) as client:
        await client.publish(f"fleet/{serial}/cmd/ota", cmd_json, qos=1)
    log.info("已觸發 OTA 至 fleet/%s/cmd/ota", serial)

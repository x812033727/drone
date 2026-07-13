"""雲端側 OTA 觸發 CLI:把 OTA 指令發到 ``fleet/{drone_id}/cmd/ota``(比照 dispatch_mission.py)。

機上 onboard/drone_agent/drone_agent/ota.py 訂閱 ``fleet/{drone_id}/cmd/ota`` 執行下載→
驗簽→A/B slot→健康檢查→回滾,並回報 ``fleet/{drone_id}/ota/progress``,但雲端**無發起端**。
本工具即為最小發起端(mission 有 dispatch_mission.py + mission_svc,OTA 對應補上此 CLI +
fleet_svc 端點 POST /devices/{id}/ota)。payload 為 ota.py 期望的**純 JSON**(非 proto;
events.proto 無 OTA 型別,刻意不動 proto,與 ota.py 同策略)。

用法:
    # 安裝(下載+驗簽+A/B slot 套用):需完整套件欄位
    python dispatch_ota.py --drone-id dev-1 --action install \
        --update-id ota-2026-07-13-01 --component onboard --version 1.4.0 \
        --url https://mirror.example/onboard-1.4.0.tar.gz \
        --sha256 <64-hex> --signature <base64> [--size 12345678] \
        [--mqtt-host broker.internal --mqtt-port 1883]

    # 控制(暫停/恢復/回退):只需 update-id(rollback 可帶 --component)
    python dispatch_ota.py --drone-id dev-1 --action pause  --update-id ota-2026-07-13-01
    python dispatch_ota.py --drone-id dev-1 --action rollback --update-id ota-2026-07-13-01

結束碼:0 = 發布成功;2 = 參數/欄位錯誤;4 = MQTT 連線失敗。fire-and-forget——
結果看 ``fleet/{drone_id}/ota/progress``(由 ingest 落 device_alerts,或 fleet-svc /alerts)。

安全註記(同 dispatch_mission.py):Phase 0 broker 為 anonymous、無 TLS/ACL,僅限開發內網;
Phase 1 起 mTLS + ACL 才對外。簽章私鑰存離線 HSM,本工具只轉發呼叫端提供的 sha256/signature。

依賴:pip install -r requirements.txt(aiomqtt)。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys

import aiomqtt

VALID_ACTIONS = ("install", "pause", "resume", "rollback")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def build_ota_payload(
    action: str,
    update_id: str,
    *,
    component: str | None = None,
    version: str | None = None,
    url: str | None = None,
    sha256: str | None = None,
    signature: str | None = None,
    size: int | None = None,
) -> dict:
    """組 cmd/ota 的 JSON dict,欄位嚴格對齊 ota.py parse_ota_command;不合法 raise ValueError。

    install 需 component/version/url/sha256/signature 齊備(size 選填),sha256 為 64-hex
    小寫;pause/resume/rollback 只需 action/update_id(rollback 可帶 component)。
    純函式(不碰 I/O),供 CLI 與單元測試(對 ota.py 做 round-trip)共用。
    """
    if action not in VALID_ACTIONS:
        raise ValueError(f"action 不合法:{action!r}(須為 {list(VALID_ACTIONS)})")
    if not update_id:
        raise ValueError("update_id 不可為空")
    payload: dict = {"action": action, "update_id": update_id}
    if action == "install":
        missing = [
            n
            for n, v in (
                ("component", component),
                ("version", version),
                ("url", url),
                ("sha256", sha256),
                ("signature", signature),
            )
            if not v
        ]
        if missing:
            raise ValueError(f"install 指令缺必要欄位:{', '.join(missing)}")
        assert sha256 is not None
        sha = sha256.lower()
        if not _SHA256_RE.match(sha):
            raise ValueError("sha256 需為 64 字元小寫 hex")
        payload.update(
            component=component, version=version, url=url, sha256=sha, signature=signature
        )
        if size is not None:
            if size < 0:
                raise ValueError("size 需為非負整數")
            payload["size"] = size
    elif action == "rollback" and component:
        payload["component"] = component
    return payload


async def _publish(host: str, port: int, drone_id: str, payload_json: str) -> None:
    async with aiomqtt.Client(hostname=host, port=port) as client:
        await client.publish(f"fleet/{drone_id}/cmd/ota", payload=payload_json, qos=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drone-id", required=True, help="目標機身識別碼(MQTT 主題用)")
    parser.add_argument(
        "--action", choices=VALID_ACTIONS, default="install", help="OTA 動作(預設 install)"
    )
    parser.add_argument("--update-id", required=True, help="本次更新工單 id(回報去重鍵)")
    parser.add_argument("--component", default=None, help="軟體元件名(install 必填;rollback 選填)")
    parser.add_argument("--version", default=None, help="目標版本 SemVer(install 必填)")
    parser.add_argument("--url", default=None, help="套件下載來源 HTTPS(install 必填)")
    parser.add_argument("--sha256", default=None, help="套件 SHA-256 小寫 hex(install 必填)")
    parser.add_argument(
        "--signature", default=None, help="對 SHA-256 摘要的 Ed25519 簽章 base64(install 必填)"
    )
    parser.add_argument("--size", type=int, default=None, help="套件位元組數(選填,斷點續傳提示)")
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT broker 主機")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker 埠(預設 1883)")
    args = parser.parse_args()

    try:
        payload = build_ota_payload(
            args.action,
            args.update_id,
            component=args.component,
            version=args.version,
            url=args.url,
            sha256=args.sha256,
            signature=args.signature,
            size=args.size,
        )
    except ValueError as e:
        print(f"參數錯誤:{e}", file=sys.stderr)
        sys.exit(2)

    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    try:
        asyncio.run(_publish(args.mqtt_host, args.mqtt_port, args.drone_id, payload_json))
    except aiomqtt.MqttError as e:
        print(f"MQTT 連線失敗:{e}", file=sys.stderr)
        sys.exit(4)
    except KeyboardInterrupt:
        print("\n中斷", file=sys.stderr)
        sys.exit(130)
    print(
        f"已觸發 OTA {args.action}(update_id={args.update_id})→ fleet/{args.drone_id}/cmd/ota",
        flush=True,
    )


if __name__ == "__main__":
    main()

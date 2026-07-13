"""機載 mTLS 裝置憑證到期偵測 + 輪換偵測(G22)。

純函式(notAfter 解析、剩餘天數、門檻判定、指紋)與 I/O 分離、可單測,
不需 SITL、不需 MQTT broker。憑證解析走**標準庫**(`ssl` + `hashlib`),
不新增依賴——`ssl._ssl._test_decode_cert` 直接由 PEM 檔解出 `notAfter`
(不需 TLS 連線),`ssl.cert_time_to_seconds` 轉 epoch 秒。

告警管道(**不動 proto 契約**):憑證剩餘天數低於門檻時
1. 記 WARNING log(機上一定看得到);
2. 最佳努力發一筆**純 JSON**(非 proto)警示到 `fleet/{drone_id}/alerts`,
   讓雲端可見「該機憑證將到期」。因 events.proto 的 FlightEvent 僅
   ARMED/DISARMED,加憑證事件型別會動到 proto 契約(觸發 contract 守門),
   故此告警刻意走 proto 契約**之外**的獨立主題+純 JSON,不碰 proto。

輪換偵測:憑證檔內容指紋(SHA-256)變化 → 記 INFO 提示「已換憑證,需重連
才會套用新憑證」。實際重連留待既有 reconnect 機制(publish/heartbeat 迴圈
斷線即重建連線會自動讀新檔);此處只負責偵測與提示(Phase 0 範圍)。

MQTT_TLS_CERT 未設(Phase 0 明文)時整個功能停用——main 不啟動本迴圈。
"""

import asyncio
import hashlib
import json
import logging
import ssl
import time

import aiomqtt

from drone_agent.tls import from_env as _mqtt_tls

logger = logging.getLogger(__name__)

#: 剩餘天數低於此值即告警(env CERT_EXPIRY_WARN_DAYS 覆寫,預設 30 天)
DEFAULT_WARN_DAYS = 30
#: 憑證檢查間隔秒數(憑證到期是「天」級事件,不需頻繁輪詢)
CERT_CHECK_INTERVAL_S = 3600.0
RECONNECT_DELAY_S = 3.0


def read_cert_not_after(cert_path: str) -> float | None:
    """由 PEM 憑證檔解出 notAfter 的 epoch 秒;失敗回 None(不拋)。

    走標準庫 `ssl`(不需 TLS 連線、不需第三方套件)。憑證讀不到/格式錯/
    解析失敗一律記 WARNING 並回 None——憑證監控是「盡力而為」的可觀測性,
    絕不能因解析失敗炸掉 agent 主流程。
    """
    try:
        decoded = ssl._ssl._test_decode_cert(cert_path)  # type: ignore[attr-defined]
        return ssl.cert_time_to_seconds(decoded["notAfter"])
    except Exception as exc:  # noqa: BLE001 - 盡力而為,任何解析錯都降級為 None
        logger.warning("憑證 notAfter 解析失敗(%s):%s", cert_path, exc)
        return None


def days_until_expiry(not_after_epoch: float, now_epoch: float) -> float:
    """剩餘天數(可為負,表示已過期)。純函式。"""
    return (not_after_epoch - now_epoch) / 86400.0


def should_warn(days_remaining: float, threshold_days: float) -> bool:
    """剩餘天數 <= 門檻(含已過期的負值)即該告警。純函式。"""
    return days_remaining <= threshold_days


def cert_fingerprint(cert_path: str) -> str | None:
    """憑證檔內容 SHA-256 十六進位摘要(輪換偵測用);讀不到回 None。

    以**內容** hash 而非 mtime 判定:原子換檔(rename)後 mtime 會變但
    偶有工具保留 mtime;內容 hash 對「憑證是否真的換了」最直接可靠。
    """
    try:
        with open(cert_path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError as exc:
        logger.warning("憑證指紋讀取失敗(%s):%s", cert_path, exc)
        return None


def expiry_alert_json(
    drone_id: str, days_remaining: float, not_after_epoch: float, now_unix_ms: int
) -> str:
    """組憑證到期告警的**純 JSON**(非 proto)payload。單行、snake_case。

    刻意不用 proto:events.proto 無憑證事件型別,加型別會動契約。此 payload
    走 `fleet/{id}/alerts`(契約外的運維告警主題),消費端以欄位名解讀即可。
    """
    return json.dumps(
        {
            "drone_id": drone_id,
            "unix_time_ms": now_unix_ms,
            "alert": "cert_expiring",
            "days_remaining": round(days_remaining, 2),
            "not_after_unix_ms": int(not_after_epoch * 1000),
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )


async def cert_monitor_loop(
    cert_path: str,
    mqtt_host: str,
    mqtt_port: int,
    drone_id: str,
    warn_days: float = DEFAULT_WARN_DAYS,
    interval: float = CERT_CHECK_INTERVAL_S,
) -> None:
    """定期檢查裝置憑證:近到期記 WARNING(+ 最佳努力發 JSON 告警);換憑證記 INFO。

    與遙測/心跳分開的獨立連線與迴圈(同 heartbeat_loop 模式):MQTT 斷線
    自動重連,期間僅影響「雲端告警發佈」——本機 WARNING log 一定照記。
    告警走 proto 契約**之外**的 `fleet/{id}/alerts` 純 JSON,不碰 proto。
    """
    alerts_topic = f"fleet/{drone_id}/alerts"
    last_fingerprint = cert_fingerprint(cert_path)
    logger.info(
        "憑證監控啟動:%s(門檻 %.0f 天,每 %.0f 秒檢查)", cert_path, warn_days, interval
    )
    while True:
        try:
            async with aiomqtt.Client(
                hostname=mqtt_host, port=mqtt_port, tls_params=_mqtt_tls()
            ) as client:
                while True:
                    # 輪換偵測:內容指紋變化 → 提示需重連套用(實際重連交給既有機制)
                    fingerprint = cert_fingerprint(cert_path)
                    if fingerprint is not None and fingerprint != last_fingerprint:
                        logger.info(
                            "偵測到憑證檔已更換(%s);重連後將自動套用新憑證", cert_path
                        )
                        last_fingerprint = fingerprint

                    not_after = read_cert_not_after(cert_path)
                    if not_after is not None:
                        days = days_until_expiry(not_after, time.time())
                        if should_warn(days, warn_days):
                            logger.warning(
                                "裝置憑證將於 %.1f 天後到期(門檻 %.0f 天),請儘速輪換/更新憑證",
                                days,
                                warn_days,
                            )
                            # 最佳努力發雲端告警;失敗(斷線)交由外層重連,不重試堆積
                            payload = expiry_alert_json(
                                drone_id, days, not_after, int(time.time() * 1000)
                            )
                            await client.publish(alerts_topic, payload=payload, qos=1)
                    await asyncio.sleep(interval)
        except aiomqtt.MqttError as exc:
            logger.warning("憑證告警 MQTT 斷線:%s;%.0f 秒後重連", exc, RECONNECT_DELAY_S)
            await asyncio.sleep(RECONNECT_DELAY_S)

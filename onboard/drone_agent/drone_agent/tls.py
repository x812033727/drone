"""機-雲 MQTT mTLS client 憑證(env 驅動;同 cloud/ingest 的 _tls_from_env)。

MQTT_TLS_CA / MQTT_TLS_CERT / MQTT_TLS_KEY 三者皆設 → 走 mTLS(對 mqtt-tls 8883
監聽器,裝置憑證 CN=機身序號);否則 None(明文,向後相容)。
憑證於出廠燒錄(Phase 1)/ SITL 開發用同一 CA 簽的 dev 憑證。
"""

import os

import aiomqtt


def from_env() -> "aiomqtt.TLSParameters | None":
    ca = os.environ.get("MQTT_TLS_CA")
    cert = os.environ.get("MQTT_TLS_CERT")
    key = os.environ.get("MQTT_TLS_KEY")
    if ca and cert and key:
        return aiomqtt.TLSParameters(ca_certs=ca, certfile=cert, keyfile=key)
    return None

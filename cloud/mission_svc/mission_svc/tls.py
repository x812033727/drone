"""MQTT mTLS client 憑證(env 驅動;同 cloud/ingest、drone_agent 的 pattern)。

MQTT_TLS_CA / MQTT_TLS_CERT / MQTT_TLS_KEY 三者皆設 → mTLS(對 8883 監聽器,
mission-svc 以 backend 服務憑證連線,ACL 讀全機隊);否則 None(明文,向後相容)。
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

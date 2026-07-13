"""fleet_svc.tls.from_env 純函式測試。"""

import aiomqtt
from fleet_svc import tls


def test_none_when_unset(monkeypatch):
    for k in ("MQTT_TLS_CA", "MQTT_TLS_CERT", "MQTT_TLS_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert tls.from_env() is None


def test_none_when_partial(monkeypatch):
    monkeypatch.setenv("MQTT_TLS_CA", "/ca.pem")
    monkeypatch.setenv("MQTT_TLS_CERT", "/cert.pem")
    monkeypatch.delenv("MQTT_TLS_KEY", raising=False)
    assert tls.from_env() is None


def test_params_when_all_set(monkeypatch):
    monkeypatch.setenv("MQTT_TLS_CA", "/ca.pem")
    monkeypatch.setenv("MQTT_TLS_CERT", "/cert.pem")
    monkeypatch.setenv("MQTT_TLS_KEY", "/key.pem")
    p = tls.from_env()
    assert isinstance(p, aiomqtt.TLSParameters)
    assert p.ca_certs == "/ca.pem" and p.certfile == "/cert.pem" and p.keyfile == "/key.pem"

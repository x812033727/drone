"""drone_agent.tls.from_env 純函式測試。"""

import aiomqtt
import pytest
from drone_agent import tls


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
    params = tls.from_env()
    assert isinstance(params, aiomqtt.TLSParameters)
    assert params.ca_certs == "/ca.pem"
    assert params.certfile == "/cert.pem"
    assert params.keyfile == "/key.pem"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

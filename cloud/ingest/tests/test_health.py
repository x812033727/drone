"""health 埠(G21):端點語意與狀態反映的行為測試。

起真的 stdlib server 在隨機埠(port 0),以 urllib 打各端點,驗證:
- /livez 恆 200(不看下游);
- /healthz 依 mqtt/db 兩狀態回 200/503,且 body 反映狀態。
"""

import json
import urllib.request
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest
from ingest import health


@pytest.fixture()
def server():
    # 每個測試把狀態歸零(模組級狀態跨測試共享)
    health.set_mqtt(False)
    health.set_db(False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), health._Handler)
    thread = Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    port = srv.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()


def _get(url: str):
    try:
        r = urllib.request.urlopen(url, timeout=3)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_livez_always_ok_even_when_down(server):
    status, body = _get(server + "/livez")
    assert status == 200
    assert body["status"] == "alive"


def test_healthz_503_until_both_up(server):
    status, body = _get(server + "/healthz")
    assert status == 503
    assert body["mqtt"] is False and body["db"] is False


def test_healthz_503_when_only_one_up(server):
    health.set_mqtt(True)  # db 仍 False
    status, _ = _get(server + "/healthz")
    assert status == 503


def test_healthz_200_when_both_up(server):
    health.set_mqtt(True)
    health.set_db(True)
    status, body = _get(server + "/healthz")
    assert status == 200
    assert body == {"status": "ok", "mqtt": True, "db": True}


def test_readyz_alias(server):
    health.set_mqtt(True)
    health.set_db(True)
    status, _ = _get(server + "/readyz")
    assert status == 200


def test_unknown_path_404(server):
    status, _ = _get(server + "/nope")
    assert status == 404

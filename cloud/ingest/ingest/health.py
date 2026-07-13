"""ingest 健康探針(G21):純 MQTT→PG 消費者無 HTTP 埠,以 stdlib http.server 另開
一個輕量 health 埠,供 Kubernetes/compose 用真 httpGet 探活(取代弱 exec 探針)。

metrics.py 已用 prometheus_client 另開 /metrics 埠(9090);health 埠與其獨立,埠號
由 ``HEALTH_PORT``(預設 8081,0 停用)控制。用 stdlib 而非在 prometheus WSGI server
上加路由,取最簡路徑(見 metrics.py 開頭說明)。

端點語意(對齊 K8s liveness/readiness 分工):
- ``/livez``   liveness:health server 存活即 200(僅證程序未整個死;不因 MQTT/DB
               短暫斷線就回 5xx,避免抖動觸發重啟)。
- ``/healthz`` / ``/readyz`` readiness:MQTT 連線與 DB pool 皆就緒才 200,否則 503
               (Body JSON 回報 mqtt/db 兩狀態)。未就緒時 K8s 不導流、compose 亦可據以等待。

狀態由消費迴圈(main.run)透過 set_mqtt()/set_db() 更新;health handler 只讀布林,
GIL 下讀寫單一布林為原子,毋須鎖。health 埠起不起來都不得拖垮消費迴圈
(見 start_health_server)。
"""

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("ingest")

HEALTH_PORT = int(os.environ.get("HEALTH_PORT", "8081"))  # 0 = 停用

# 消費迴圈維護的即時狀態(布林讀寫在 GIL 下為原子,毋須鎖)。
_state = {"mqtt_connected": False, "db_connected": False}


def set_mqtt(connected: bool) -> None:
    _state["mqtt_connected"] = connected


def set_db(connected: bool) -> None:
    _state["db_connected"] = connected


def snapshot() -> dict[str, bool]:
    return dict(_state)


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 (stdlib 介面命名)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/livez":
            # liveness:程序活著即可,不看下游連線狀態
            self._send(200, {"status": "alive"})
            return
        if path in ("/healthz", "/readyz"):
            st = snapshot()
            ready = st["mqtt_connected"] and st["db_connected"]
            self._send(
                200 if ready else 503,
                {
                    "status": "ok" if ready else "unavailable",
                    "mqtt": st["mqtt_connected"],
                    "db": st["db_connected"],
                },
            )
            return
        self._send(404, {"status": "not_found"})

    def log_message(self, *args) -> None:  # 靜音預設 stderr 存取日誌
        return


def start_health_server() -> None:
    """在 daemon thread 起 health 埠;失敗只記錄不拋出,不得拖垮消費迴圈。"""
    if HEALTH_PORT <= 0:
        log.info("HEALTH_PORT<=0,停用 health 埠")
        return
    try:
        server = ThreadingHTTPServer(("0.0.0.0", HEALTH_PORT), _Handler)
    except OSError as e:
        log.warning("health 埠啟動失敗(%s),續跑消費迴圈不受影響", e)
        return
    thread = threading.Thread(target=server.serve_forever, name="health", daemon=True)
    thread.start()
    log.info("health 埠已開:0.0.0.0:%d(/livez /healthz)", HEALTH_PORT)

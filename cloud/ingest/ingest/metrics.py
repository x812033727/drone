"""Prometheus 可觀測性(G13):ingest(MQTT consumer,無 HTTP server)。

ingest 不是 FastAPI 服務,改以 ``prometheus_client.start_http_server`` 在啟動時
另開一個 metrics HTTP 埠(預設 9090,可用環境變數 ``METRICS_PORT`` 覆寫;設為
0 則停用)。用獨立 ``CollectorRegistry``,與其他服務一致、且不動全域 REGISTRY。

指標:
- ``ingest_messages_total{route,result}``:已處理訊息數。result=parsed / decode_error
  / unknown_topic。route 用主題末段(telemetry、mission/progress……)不含機隊 id,
  避免高基數。
- ``ingest_db_writes_total{result}``:DB 寫入結果數。result=ok / error。
- ``ingest_messages_inflight``:目前處理中的入站訊息數(gauge;handle() 進出各 ±1)。
- 另含 ``process_*`` / ``python_gc_*`` 標準收集器。

埋點只遞增計數,不改變 handle() 既有解析/落庫/丟棄行為;metrics 埠起不起來
都不影響消費迴圈(見 start_metrics_server)。
"""

import logging
import os

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    GCCollector,
    PlatformCollector,
    ProcessCollector,
    start_http_server,
)

log = logging.getLogger("ingest")

METRICS_PORT = int(os.environ.get("METRICS_PORT", "9090"))  # 0 = 停用

registry = CollectorRegistry()
ProcessCollector(registry=registry)
PlatformCollector(registry=registry)
GCCollector(registry=registry)

messages_total = Counter(
    "ingest_messages_total",
    "已處理的 MQTT 訊息數(依主題末段 / 結果)",
    ["route", "result"],
    registry=registry,
)
db_writes_total = Counter(
    "ingest_db_writes_total",
    "遙測落庫的 DB 寫入結果數",
    ["result"],
    registry=registry,
)
messages_inflight = Gauge(
    "ingest_messages_inflight",
    "目前處理中的入站訊息數(handle() 進出各 ±1)",
    registry=registry,
)
dlq_total = Counter(
    "ingest_dlq_total",
    "DB 寫入重試耗盡後落入死信(DLQ)的訊息數(依主題末段)",
    ["route"],
    registry=registry,
)


def start_metrics_server() -> None:
    """啟動 metrics HTTP 埠;失敗只記錄不拋出,不得拖垮消費迴圈。"""
    if METRICS_PORT <= 0:
        log.info("METRICS_PORT<=0,停用 /metrics 埠")
        return
    try:
        start_http_server(METRICS_PORT, registry=registry)
        log.info("Prometheus metrics 埠已開:0.0.0.0:%d/metrics", METRICS_PORT)
    except OSError as e:
        log.warning("metrics 埠啟動失敗(%s),續跑消費迴圈不受影響", e)

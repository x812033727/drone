"""Prometheus 可觀測性(G13):/metrics 端點與 HTTP 指標埋點。

設計要點:
- 用獨立 ``CollectorRegistry``(非全域 REGISTRY),讓四個雲端服務在同一個
  pytest 行程內各自匯入時不會撞名(Duplicated timeseries in CollectorRegistry)。
- 程序/GC/平台收集器一併掛進本 registry,提供 ``process_*`` / ``python_gc_*``
  標準指標(記憶體、CPU、開檔數、GC)。
- 純 ASGI middleware(非 ``BaseHTTPMiddleware``):後者會緩衝回應、與串流
  端點相容性差;純 ASGI 版本不緩衝、與各服務範式一致(對齊 fleet-svc)。
- ``/metrics`` 端點失敗不得拖垮服務:埋點僅遞增計數、與請求處理解耦;
  端點為獨立路由,即使抓取端異常也不影響業務 API。
"""

import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from fastapi import FastAPI, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    GCCollector,
    Histogram,
    PlatformCollector,
    ProcessCollector,
    generate_latest,
)

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

# 每個服務一個獨立 registry:同行程多服務匯入不撞名,並隔離標準收集器。
registry = CollectorRegistry()
ProcessCollector(registry=registry)
PlatformCollector(registry=registry)
GCCollector(registry=registry)

http_requests_total = Counter(
    "http_requests_total",
    "HTTP 請求總數(依方法 / 路由樣板 / 狀態碼)",
    ["method", "path", "status"],
    registry=registry,
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP 請求處理延遲(秒,依方法 / 路由樣板)",
    ["method", "path"],
    registry=registry,
)


def _template_path(scope: Scope) -> str:
    """回傳路由樣板路徑(如 /api/v1/devices/{device_id}),避免 UUID 造成高基數。

    路由匹配後 starlette 會把 APIRoute 放進 scope["route"];未匹配(404)時
    退回原始路徑。/metrics 子掛載回傳 "/metrics",基數同樣可控。
    """
    route = scope.get("route")
    template = getattr(route, "path", None)
    return template or scope.get("path", "")


class PrometheusMiddleware:
    """純 ASGI middleware:記錄每個 HTTP 請求的計數與延遲。

    以 send 包裝抓取回應狀態碼;例外未產生 http.response.start 時記為 500。
    對非 http(lifespan / websocket)直接放行。
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = {"code": 500}

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            method = scope.get("method", "")
            path = _template_path(scope)
            http_requests_total.labels(method, path, str(status["code"])).inc()
            http_request_duration_seconds.labels(method, path).observe(elapsed)


async def _metrics_endpoint() -> Response:
    """/metrics:輸出本 registry 的 Prometheus 文字格式(直接路由,無尾斜線轉址)。"""
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


def instrument(app: FastAPI) -> None:
    """掛上 HTTP 指標 middleware 與 /metrics 端點(Prometheus 文字格式)。"""
    app.add_middleware(PrometheusMiddleware)
    app.add_api_route("/metrics", _metrics_endpoint, include_in_schema=False)

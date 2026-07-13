"""遙測即時廣播中樞(in-memory)。消費者 publish,SSE 訂閱者各持一個有界佇列。

飛安不依賴雲端:此中樞純為監看,遺失樣本無害(慢客戶端滿佇列即丟最舊)。
"""

from __future__ import annotations

import asyncio
from typing import Any


class TelemetryHub:
    def __init__(self, queue_maxsize: int = 100) -> None:
        self._latest: dict[str, dict[str, Any]] = {}
        self._subscribers: set[asyncio.Queue] = set()
        self._queue_maxsize = queue_maxsize

    def publish(self, data: dict[str, Any]) -> None:
        """更新該機最新狀態並推給所有訂閱者(佇列滿則丟最舊,不阻塞)。"""
        drone_id = data.get("drone_id")
        if drone_id:
            self._latest[drone_id] = data
        for q in self._subscribers:
            _offer(q, data)

    def snapshot(self) -> list[dict[str, Any]]:
        """目前所有機的最新狀態(SSE 連上時先送)。"""
        return list(self._latest.values())

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


def _offer(q: asyncio.Queue, data: dict[str, Any]) -> None:
    """非阻塞放入;滿則丟一個最舊再放(慢客戶端不拖垮發布)。"""
    try:
        q.put_nowait(data)
    except asyncio.QueueFull:
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass

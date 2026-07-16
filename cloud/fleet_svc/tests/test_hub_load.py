"""TelemetryHub in-process 壓測(決定性,無網路/docker;R2)。

驗的是慢消費者設計的三個不變量:publish 永不阻塞、每佇列有界(drop-oldest
保最新)、全退訂後歸零;外加 tracemalloc 記憶體有界斷言。
外部(真 HTTP/SSE)壓測見 tools/loadgen/sse_swarm.py,不在單元層重演。
"""

from __future__ import annotations

import asyncio
import time
import tracemalloc

from fleet_svc.hub import TelemetryHub

SUBSCRIBERS = 200
MESSAGES = 5_000
QUEUE_MAXSIZE = 100


def _msg(i: int) -> dict:
    return {"drone_id": f"d-{i % 20}", "seq": i, "battery_pct": 88.8}


def test_publish_never_blocks_with_slow_subscribers():
    """200 個全滿(無人消費)佇列下,publish 是純同步、不阻塞、時間有界。"""

    async def scenario():
        hub = TelemetryHub(queue_maxsize=QUEUE_MAXSIZE)
        queues = [hub.subscribe() for _ in range(SUBSCRIBERS)]
        t0 = time.perf_counter()
        for i in range(MESSAGES):
            hub.publish(_msg(i))
        elapsed = time.perf_counter() - t0
        # 5k 訊息 × 200 訂閱者 = 100 萬次 offer;純記憶體操作,秒級即有界。
        # 門檻放寬到 30s 只防「意外變成阻塞/O(n²)」,不量測絕對效能。
        assert elapsed < 30, f"publish 疑似阻塞:{elapsed:.1f}s"
        for q in queues:
            assert q.qsize() <= QUEUE_MAXSIZE
        return hub, queues

    hub, queues = asyncio.run(scenario())
    assert hub.subscriber_count == SUBSCRIBERS
    for q in queues:
        hub.unsubscribe(q)
    assert hub.subscriber_count == 0


def test_drop_oldest_keeps_latest_sample():
    """佇列滿時丟最舊:尾端必是最新樣本,佇列內容是最後 maxsize 筆。"""

    async def scenario():
        hub = TelemetryHub(queue_maxsize=QUEUE_MAXSIZE)
        q = hub.subscribe()
        total = QUEUE_MAXSIZE + 57
        for i in range(total):
            hub.publish(_msg(i))
        assert q.qsize() == QUEUE_MAXSIZE
        seqs = [q.get_nowait()["seq"] for _ in range(QUEUE_MAXSIZE)]
        assert seqs == list(range(total - QUEUE_MAXSIZE, total)), "應恰為最後 maxsize 筆"

    asyncio.run(scenario())


def test_memory_bounded_under_sustained_publish():
    """持續 publish 下記憶體有界(佇列 drop-oldest + _latest 以機為鍵)。"""

    async def scenario():
        hub = TelemetryHub(queue_maxsize=QUEUE_MAXSIZE)
        for _ in range(SUBSCRIBERS):
            hub.subscribe()
        tracemalloc.start()
        for i in range(MESSAGES):
            hub.publish(_msg(i))
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        # 上界推導:200 佇列 × 100 筆 × ~200B/dict ≈ 4 MB;取 10 倍餘裕防 flaky。
        assert peak < 40 * 1024 * 1024, f"記憶體疑似無界:peak={peak / 1e6:.1f} MB"

    asyncio.run(scenario())


def test_unsubscribe_all_returns_to_zero_and_stops_delivery():
    async def scenario():
        hub = TelemetryHub(queue_maxsize=QUEUE_MAXSIZE)
        queues = [hub.subscribe() for _ in range(50)]
        for q in queues:
            hub.unsubscribe(q)
        assert hub.subscriber_count == 0
        hub.publish(_msg(1))
        for q in queues:
            assert q.qsize() == 0, "退訂後不應再收到訊息"

    asyncio.run(scenario())

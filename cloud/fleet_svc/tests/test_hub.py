"""SSE 廣播中樞的純邏輯測試(不需事件迴圈的部分用同步斷言)。"""

import asyncio

from fleet_svc.hub import TelemetryHub


def test_publish_updates_latest_snapshot():
    hub = TelemetryHub()
    hub.publish({"drone_id": "A", "battery_pct": 90})
    hub.publish({"drone_id": "B", "battery_pct": 50})
    hub.publish({"drone_id": "A", "battery_pct": 88})  # 覆蓋 A
    snap = {d["drone_id"]: d for d in hub.snapshot()}
    assert snap["A"]["battery_pct"] == 88
    assert snap["B"]["battery_pct"] == 50


def test_subscriber_receives_published():
    async def scenario():
        hub = TelemetryHub()
        q = hub.subscribe()
        assert hub.subscriber_count == 1
        hub.publish({"drone_id": "A", "v": 1})
        got = await asyncio.wait_for(q.get(), timeout=1)
        assert got["v"] == 1
        hub.unsubscribe(q)
        assert hub.subscriber_count == 0

    asyncio.run(scenario())


def test_full_queue_drops_oldest_not_publisher():
    hub = TelemetryHub(queue_maxsize=2)
    q = hub.subscribe()
    for i in range(5):  # 發超過佇列容量,publish 不應阻塞/報錯
        hub.publish({"drone_id": "A", "seq": i})
    # 佇列滿時丟最舊:應留最後 2 筆
    items = [q.get_nowait() for _ in range(q.qsize())]
    seqs = [it["seq"] for it in items]
    assert seqs == [3, 4]

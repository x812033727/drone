"""TelemetryHub 不變量屬性測試(hypothesis,derandomize)。"""

from __future__ import annotations

import asyncio

from fleet_svc.hub import TelemetryHub
from hypothesis import given, settings
from hypothesis import strategies as st

settings.register_profile("ci", derandomize=True, max_examples=100)
settings.load_profile("ci")

# 任意 publish 序列:每筆事件 = (drone_id 或 None/空, 值)
events_st = st.lists(
    st.tuples(
        st.one_of(st.none(), st.sampled_from(["", "a", "b", "c", "d"])),
        st.integers(),
    ),
    max_size=300,
)


@given(events_st, st.integers(min_value=1, max_value=8))
def test_hub_invariants_under_arbitrary_publish(events, n_subs):
    async def scenario():
        hub = TelemetryHub(queue_maxsize=10)
        queues = [hub.subscribe() for _ in range(n_subs)]
        for drone_id, v in events:
            hub.publish({"drone_id": drone_id, "v": v})
        # 不變量 1:每佇列有界
        assert all(q.qsize() <= 10 for q in queues)
        # 不變量 2:_latest 鍵 = 見過的「真值」drone_id 集合(None/空不入鍵)
        seen = {d for d, _ in events if d}
        assert {s["drone_id"] for s in hub.snapshot()} == seen
        # 不變量 3:每機 snapshot 為該機最後一筆
        last = {}
        for d, v in events:
            if d:
                last[d] = v
        for s in hub.snapshot():
            assert s["v"] == last[s["drone_id"]]
        # 不變量 4:退訂全歸零
        for q in queues:
            hub.unsubscribe(q)
        assert hub.subscriber_count == 0

    asyncio.run(scenario())

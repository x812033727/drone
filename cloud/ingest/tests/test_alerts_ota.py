"""告警閉環 ingest 訂閱落庫:fleet/+/alerts(cert 到期)與 fleet/+/ota/progress(OTA 進度)。

沿用 test_handle.py 的 stub pool 範式(不需真 DB)。重點驗證:
- 兩主題路由到 device_alerts 表(DEVICE_ALERT_SQL),kind 正確('cert' / 'ota');
- OTA 進度 payload **不含 drone_id**,drone_id 取自主題;
- summary 對齊(cert=alert 名、ota=state),其餘欄位落 detail(JSON 字串);
- 壞 payload(缺 state / 缺 unix_time_ms / 非 UTF-8 / 非物件)一律丟棄,不落半筆。
"""

import asyncio
import json

from ingest import main


class _Topic:
    def __init__(self, value: str) -> None:
        self.value = value


class _Message:
    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = _Topic(topic)
        self.payload = payload


class _StubPool:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def execute(self, sql: str, *args) -> None:
        self.calls.append((sql, args))


def _run(pool, topic: str, payload: bytes) -> None:
    asyncio.run(main.handle(pool, _Message(topic, payload)))


# ---- cert 到期告警(fleet/{id}/alerts,對齊 cert_monitor.py expiry_alert_json)----
CERT_ALERT = json.dumps(
    {
        "drone_id": "dev-1",
        "unix_time_ms": 1783147200000,
        "alert": "cert_expiring",
        "days_remaining": 12.5,
        "not_after_unix_ms": 1785739200000,
    }
).encode()


def test_cert_alert_routes_to_device_alerts():
    pool = _StubPool()
    _run(pool, "fleet/dev-1/alerts", CERT_ALERT)
    assert len(pool.calls) == 1
    sql, args = pool.calls[0]
    assert sql == main.DEVICE_ALERT_SQL
    # (time, drone_id, kind, summary, detail_json)
    assert args[1] == "dev-1"
    assert args[2] == "cert"
    assert args[3] == "cert_expiring"
    detail = json.loads(args[4])
    assert detail["days_remaining"] == 12.5
    assert detail["not_after_unix_ms"] == 1785739200000
    # drone_id / unix_time_ms / alert 不重複進 detail
    assert "drone_id" not in detail and "alert" not in detail


def test_alert_missing_alert_field_dropped():
    pool = _StubPool()
    _run(pool, "fleet/dev-1/alerts", b'{"drone_id":"dev-1","unix_time_ms":1}')
    assert pool.calls == []


# ---- OTA 進度(fleet/{id}/ota/progress,對齊 ota.py progress_dict)----
OTA_PROGRESS = json.dumps(
    {
        # 注意:ota.py progress_dict 不含 drone_id——drone_id 取自主題
        "update_id": "ota-2026-07-13-01",
        "component": "onboard",
        "version": "1.4.0",
        "state": "DOWNLOADING",
        "unix_time_ms": 1783147200000,
        "detail": "",
    }
).encode()


def test_ota_progress_routes_and_takes_drone_id_from_topic():
    pool = _StubPool()
    _run(pool, "fleet/dev-9/ota/progress", OTA_PROGRESS)
    assert len(pool.calls) == 1
    sql, args = pool.calls[0]
    assert sql == main.DEVICE_ALERT_SQL
    assert args[1] == "dev-9"  # 來自主題,非 payload
    assert args[2] == "ota"
    assert args[3] == "DOWNLOADING"  # summary = state
    detail = json.loads(args[4])
    assert detail["update_id"] == "ota-2026-07-13-01"
    assert detail["component"] == "onboard"
    assert detail["version"] == "1.4.0"


def test_ota_progress_terminal_state_routes():
    pool = _StubPool()
    payload = json.dumps(
        {"update_id": "u1", "state": "COMPLETED", "unix_time_ms": 1783147200000}
    ).encode()
    _run(pool, "fleet/dev-1/ota/progress", payload)
    assert len(pool.calls) == 1
    assert pool.calls[0][1][2] == "ota" and pool.calls[0][1][3] == "COMPLETED"


def test_ota_progress_missing_state_dropped():
    pool = _StubPool()
    payload = json.dumps({"update_id": "u1", "unix_time_ms": 1}).encode()
    _run(pool, "fleet/dev-1/ota/progress", payload)
    assert pool.calls == []


def test_ota_progress_missing_time_dropped():
    pool = _StubPool()
    payload = json.dumps({"update_id": "u1", "state": "RECEIVED"}).encode()
    _run(pool, "fleet/dev-1/ota/progress", payload)
    assert pool.calls == []


def test_alert_non_utf8_dropped():
    pool = _StubPool()
    _run(pool, "fleet/dev-1/alerts", b"\xff\xfe\x00")
    assert pool.calls == []


def test_alert_non_object_dropped():
    pool = _StubPool()
    _run(pool, "fleet/dev-1/alerts", b"[1, 2, 3]")
    assert pool.calls == []

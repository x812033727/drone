"""handle() 的防護測試:壞 payload 與 DB 例外都不得讓例外冒出(服務不能因此 crash)。

pool 用 stub,不需真 DB;三種壞 payload 都是對抗驗證中實測會炸的案例:
1. mission state 給數字 enum 99 → State.Name() ValueError
2. unixTimeMs 超大 int64 → fromtimestamp "year out of range"
3. 非 UTF-8 bytes → UnicodeDecodeError
"""

import asyncio
import json

import asyncpg
import pytest
from ingest import main


class _Topic:
    def __init__(self, value: str) -> None:
        self.value = value


class _Message:
    """最小 aiomqtt.Message 替身:handle() 只用 topic.value 與 payload。"""

    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = _Topic(topic)
        self.payload = payload


class _StubPool:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc
        self.calls: list[tuple] = []

    async def execute(self, sql: str, *args) -> None:
        self.calls.append((sql, args))
        if self.exc is not None:
            raise self.exc


class _FlakyPool:
    """前 ``fail_times`` 次寫入拋例外,之後成功——驗證有限次重試會吸收短暫失敗。"""

    def __init__(self, fail_times: int, exc: Exception) -> None:
        self.fail_times = fail_times
        self.exc = exc
        self.calls: list[tuple] = []

    async def execute(self, sql: str, *args) -> None:
        self.calls.append((sql, args))
        if len(self.calls) <= self.fail_times:
            raise self.exc


@pytest.fixture(autouse=True)
def _fast_retry_and_tmp_dlq(monkeypatch, tmp_path):
    """重試不真的 sleep(測試快),DLQ 落到 tmp 檔(不污染 cwd)。"""
    monkeypatch.setattr(main, "DB_RETRY_BASE_S", 0.0)
    monkeypatch.setattr(main, "DLQ_PATH", str(tmp_path / "dlq.jsonl"))


def _run(pool, topic: str, payload: bytes) -> None:
    asyncio.run(main.handle(pool, _Message(topic, payload)))


GOOD_TELEMETRY = b'{"droneId": "dev-1", "unixTimeMs": "1783147200000", "latDeg": 25.0}'


def test_good_telemetry_inserts():
    pool = _StubPool()
    _run(pool, "fleet/dev-1/telemetry", GOOD_TELEMETRY)
    assert len(pool.calls) == 1
    assert pool.calls[0][0] == main.TELEMETRY_SQL


def test_numeric_enum_out_of_range_dropped():
    # proto3 開放 enum:Parse 接受未知數字 99,State.Name(99) 才炸 ValueError
    pool = _StubPool()
    payload = b'{"missionId": "m-1", "droneId": "dev-1", "state": 99, "unixTimeMs": "1783147200"}'
    _run(pool, "fleet/dev-1/mission/progress", payload)
    assert pool.calls == []


def test_huge_timestamp_dropped():
    # int64 上限 → datetime.fromtimestamp "year out of range"
    pool = _StubPool()
    payload = b'{"droneId": "dev-1", "unixTimeMs": "9223372036854775807"}'
    _run(pool, "fleet/dev-1/telemetry", payload)
    assert pool.calls == []


def test_non_utf8_payload_dropped():
    pool = _StubPool()
    _run(pool, "fleet/dev-1/telemetry", b"\xff\xfe\xfd\x00\x01")
    assert pool.calls == []


def test_unknown_topic_skipped():
    pool = _StubPool()
    _run(pool, "fleet/dev-1/other", GOOD_TELEMETRY)
    assert pool.calls == []


def test_db_error_retries_then_dlq():
    # 持續 DB 例外:重試 DB_WRITE_ATTEMPTS 次後轉 DLQ,例外不得冒出 handle()
    pool = _StubPool(exc=asyncpg.PostgresError("boom"))
    _run(pool, "fleet/dev-1/telemetry", GOOD_TELEMETRY)
    assert len(pool.calls) == main.DB_WRITE_ATTEMPTS  # 每次重試都嘗試寫入
    lines = open(main.DLQ_PATH, encoding="utf-8").read().splitlines()
    assert len(lines) == 1  # 落一筆死信
    rec = json.loads(lines[0])
    assert rec["topic"] == "fleet/dev-1/telemetry"
    assert rec["route"] == "telemetry"
    assert rec["sql"] == main.TELEMETRY_SQL


def test_db_oserror_retries_then_dlq():
    pool = _StubPool(exc=ConnectionResetError("db gone"))
    _run(pool, "fleet/dev-1/telemetry", GOOD_TELEMETRY)
    assert len(pool.calls) == main.DB_WRITE_ATTEMPTS
    assert len(open(main.DLQ_PATH, encoding="utf-8").read().splitlines()) == 1


def test_db_transient_error_recovers_no_dlq(tmp_path):
    # 前兩次失敗、第三次成功:不落 DLQ(有限次重試吸收短暫斷線)
    pool = _FlakyPool(fail_times=main.DB_WRITE_ATTEMPTS - 1, exc=ConnectionResetError("blip"))
    _run(pool, "fleet/dev-1/telemetry", GOOD_TELEMETRY)
    assert len(pool.calls) == main.DB_WRITE_ATTEMPTS  # 失敗兩次 + 成功一次
    import os
    assert not os.path.exists(main.DLQ_PATH)  # 未落 DLQ


def test_db_dlq_write_failure_does_not_crash(monkeypatch):
    # DLQ 落地本身失敗(路徑不可寫)也不得讓例外冒出 handle()
    monkeypatch.setattr(main, "DLQ_PATH", "/proc/nonexistent-dir/dlq.jsonl")
    pool = _StubPool(exc=asyncpg.PostgresError("boom"))
    _run(pool, "fleet/dev-1/telemetry", GOOD_TELEMETRY)  # 不得拋出
    assert len(pool.calls) == main.DB_WRITE_ATTEMPTS


GOOD_EVENT = b'{"drone_id": "dev-1", "unix_time_ms": "1783147200000", "event": "EVENT_ARMED"}'


def test_good_event_inserts():
    pool = _StubPool()
    _run(pool, "fleet/dev-1/events", GOOD_EVENT)
    assert len(pool.calls) == 1
    assert pool.calls[0][0] == main.EVENT_SQL
    assert pool.calls[0][1][1:] == ("dev-1", "EVENT_ARMED")


def test_event_numeric_enum_out_of_range_dropped():
    # proto3 開放 enum:Parse 接受未知數字 99,Event.Name(99) 才炸 ValueError
    pool = _StubPool()
    payload = b'{"drone_id": "dev-1", "unix_time_ms": "1783147200000", "event": 99}'
    _run(pool, "fleet/dev-1/events", payload)
    assert pool.calls == []


GOOD_HEARTBEAT = (
    b'{"drone_id": "dev-1", "unix_time_ms": "1783147200000", "agent_version": "0.1.0",'
    b' "firmware_version": "1.15.4", "boot_unix_ms": "1783147140000", "uptime_s": "60"}'
)


def test_good_heartbeat_inserts():
    pool = _StubPool()
    _run(pool, "fleet/dev-1/heartbeat", GOOD_HEARTBEAT)
    assert len(pool.calls) == 1
    assert pool.calls[0][0] == main.DEVICE_HEARTBEAT_SQL
    assert pool.calls[0][1][1] == "dev-1"
    assert pool.calls[0][1][2:4] == ("0.1.0", "1.15.4")


def test_heartbeat_huge_boot_timestamp_dropped():
    # boot_unix_ms 超大 → fromtimestamp 溢位,記錄後丟棄不落半筆
    pool = _StubPool()
    payload = (
        b'{"drone_id": "dev-1", "unix_time_ms": "1783147200000",'
        b' "boot_unix_ms": "9223372036854775807"}'
    )
    _run(pool, "fleet/dev-1/heartbeat", payload)
    assert pool.calls == []


# ---- v0.4.0 sensors 主題路由(取末兩段查表)----

GOOD_ATTITUDE = (
    b'{"drone_id": "dev-1", "unix_time_ms": "1783147200000",'
    b' "px4_timestamp_us": "123", "q": [1.0, 0.0, 0.0, 0.0]}'
)


def test_sensor_attitude_routes():
    pool = _StubPool()
    _run(pool, "fleet/dev-1/sensors/attitude", GOOD_ATTITUDE)
    assert len(pool.calls) == 1
    assert pool.calls[0][0] == main.SENSOR_ATTITUDE_SQL


def test_sensor_gps_routes():
    pool = _StubPool()
    payload = b'{"drone_id": "dev-1", "unix_time_ms": "1783147200000", "fix_type": "FIX_TYPE_3D"}'
    _run(pool, "fleet/dev-1/sensors/gps", payload)
    assert len(pool.calls) == 1
    assert pool.calls[0][0] == main.SENSOR_GPS_SQL


def test_sensor_local_position_routes():
    pool = _StubPool()
    payload = b'{"drone_id": "dev-1", "unix_time_ms": "1783147200000", "x": 1.0}'
    _run(pool, "fleet/dev-1/sensors/local_position", payload)
    assert len(pool.calls) == 1
    assert pool.calls[0][0] == main.SENSOR_LOCAL_POSITION_SQL


def test_sensor_attitude_bad_quaternion_dropped():
    # q 非 4 元素:decode raise → 記錄後丟棄,不得嘗試寫入
    pool = _StubPool()
    payload = b'{"drone_id": "dev-1", "unix_time_ms": "1783147200000", "q": [1.0]}'
    _run(pool, "fleet/dev-1/sensors/attitude", payload)
    assert pool.calls == []


def test_unknown_sensor_subtopic_skipped():
    pool = _StubPool()
    _run(pool, "fleet/dev-1/sensors/baro", GOOD_ATTITUDE)
    assert pool.calls == []

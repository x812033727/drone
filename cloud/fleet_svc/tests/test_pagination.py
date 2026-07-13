"""分頁(G12):repo list/count 的 SQL 與參數(不碰 DB,用 stub 連線記錄查詢)。

驗證:預設 limit=100 offset=0(向後相容——無參數不回全表而是首 100 筆);
帶參數時 LIMIT/OFFSET 綁定正確;有 fleet_id 過濾時參數位移正確;count 與過濾一致。
"""

import asyncio
from uuid import uuid4

from fleet_svc import repo


class _StubConn:
    def __init__(self) -> None:
        self.fetch_calls: list[tuple] = []
        self.fetchval_calls: list[tuple] = []

    async def fetch(self, sql: str, *args):
        self.fetch_calls.append((sql, args))
        return []

    async def fetchval(self, sql: str, *args):
        self.fetchval_calls.append((sql, args))
        return 0


def test_list_fleets_defaults_cap_100():
    conn = _StubConn()
    asyncio.run(repo.list_fleets(conn))
    sql, args = conn.fetch_calls[0]
    assert "LIMIT $1 OFFSET $2" in sql
    assert args == (100, 0)


def test_list_fleets_explicit_page():
    conn = _StubConn()
    asyncio.run(repo.list_fleets(conn, limit=25, offset=50))
    assert conn.fetch_calls[0][1] == (25, 50)


def test_count_fleets():
    conn = _StubConn()
    asyncio.run(repo.count_fleets(conn))
    assert "count(*)" in conn.fetchval_calls[0][0]


def test_list_devices_no_filter_indices():
    conn = _StubConn()
    asyncio.run(repo.list_devices(conn, limit=10, offset=5))
    sql, args = conn.fetch_calls[0]
    assert "LIMIT $1 OFFSET $2" in sql
    assert args == (10, 5)


def test_list_devices_with_fleet_filter_shifts_indices():
    conn = _StubConn()
    fid = uuid4()
    asyncio.run(repo.list_devices(conn, fleet_id=fid, limit=10, offset=5))
    sql, args = conn.fetch_calls[0]
    assert "WHERE fleet_id = $1" in sql
    assert "LIMIT $2 OFFSET $3" in sql
    assert args == (fid, 10, 5)


def test_count_devices_respects_filter():
    conn = _StubConn()
    fid = uuid4()
    asyncio.run(repo.count_devices(conn, fleet_id=fid))
    sql, args = conn.fetchval_calls[0]
    assert "WHERE fleet_id = $1" in sql
    assert args == (fid,)

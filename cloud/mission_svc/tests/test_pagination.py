"""分頁(G12):mission repo list/count 的 SQL 與參數(不碰 DB,用 stub 連線)。"""

import asyncio

from mission_svc import repo


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


def test_list_routes_defaults_cap_100():
    conn = _StubConn()
    asyncio.run(repo.list_routes(conn))
    sql, args = conn.fetch_calls[0]
    assert "LIMIT $1 OFFSET $2" in sql
    assert args == (100, 0)


def test_list_routes_explicit_page():
    conn = _StubConn()
    asyncio.run(repo.list_routes(conn, limit=20, offset=40))
    assert conn.fetch_calls[0][1] == (20, 40)


def test_list_missions_no_filter_indices():
    conn = _StubConn()
    asyncio.run(repo.list_missions(conn, limit=10, offset=5))
    sql, args = conn.fetch_calls[0]
    assert "LIMIT $1 OFFSET $2" in sql
    assert args == (10, 5)


def test_list_missions_with_drone_filter_shifts_indices():
    conn = _StubConn()
    asyncio.run(repo.list_missions(conn, drone_id="dev-1", limit=10, offset=5))
    sql, args = conn.fetch_calls[0]
    assert "WHERE drone_id = $1" in sql
    assert "LIMIT $2 OFFSET $3" in sql
    assert args == ("dev-1", 10, 5)


def test_count_missions_respects_filter():
    conn = _StubConn()
    asyncio.run(repo.count_missions(conn, drone_id="dev-1"))
    sql, args = conn.fetchval_calls[0]
    assert "WHERE drone_id = $1" in sql
    assert args == ("dev-1",)


def test_count_routes():
    conn = _StubConn()
    asyncio.run(repo.count_routes(conn))
    assert "count(*)" in conn.fetchval_calls[0][0]

"""mission-svc 資料存取(asyncpg)。waypoints 以 jsonb 存;純函式部分可單測。"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import asyncpg

from mission_svc.dispatch import TERMINAL_STATUSES
from mission_svc.models import AuditEntry, Mission, MissionCreate, Route, RouteCreate

_ROUTE_COLS = "id, name, org_id, waypoints, rtl_after_last, created_at"
_MISSION_COLS = (
    "id, mission_id, route_id, drone_id, status, waypoints, rtl_after_last, "
    "current_item, total_items, dispatched_at, finished_at, created_at"
)


def new_mission_id() -> str:
    """端到端追溯鍵(短、可讀、唯一)。"""
    return f"m-{uuid4().hex[:12]}"


def _route(r: asyncpg.Record) -> Route:
    d = dict(r)
    d["waypoints"] = json.loads(d["waypoints"])
    return Route.model_validate(d)


def _mission(r: asyncpg.Record) -> Mission:
    d = dict(r)
    d["waypoints"] = json.loads(d["waypoints"])
    return Mission.model_validate(d)


# ---- route ----
async def create_route(conn: asyncpg.Connection, body: RouteCreate) -> Route:
    wps = json.dumps([w.model_dump() for w in body.waypoints])
    r = await conn.fetchrow(
        "INSERT INTO mission.route (name, org_id, waypoints, rtl_after_last) "
        f"VALUES ($1, $2, $3::jsonb, $4) RETURNING {_ROUTE_COLS}",
        body.name,
        body.org_id,
        wps,
        body.rtl_after_last,
    )
    return _route(r)


async def list_routes(
    conn: asyncpg.Connection, limit: int = 100, offset: int = 0
) -> list[Route]:
    rows = await conn.fetch(
        f"SELECT {_ROUTE_COLS} FROM mission.route ORDER BY created_at DESC LIMIT $1 OFFSET $2",
        limit,
        offset,
    )
    return [_route(r) for r in rows]


async def count_routes(conn: asyncpg.Connection) -> int:
    return await conn.fetchval("SELECT count(*) FROM mission.route")


async def get_route(conn: asyncpg.Connection, route_id: UUID) -> Route | None:
    r = await conn.fetchrow(f"SELECT {_ROUTE_COLS} FROM mission.route WHERE id = $1", route_id)
    return _route(r) if r else None


# ---- mission ----
async def create_mission(conn: asyncpg.Connection, body: MissionCreate) -> Mission | None:
    """由 route 建任務:凍結 route 當下航點、產生 mission_id。route 不存在回 None。"""
    route = await get_route(conn, body.route_id)
    if route is None:
        return None
    wps = json.dumps([w.model_dump() for w in route.waypoints])
    r = await conn.fetchrow(
        "INSERT INTO mission.mission "
        "(mission_id, route_id, drone_id, waypoints, rtl_after_last, total_items) "
        f"VALUES ($1, $2, $3, $4::jsonb, $5, $6) RETURNING {_MISSION_COLS}",
        new_mission_id(),
        body.route_id,
        body.drone_id,
        wps,
        route.rtl_after_last,
        len(route.waypoints),
    )
    return _mission(r)


async def list_missions(
    conn: asyncpg.Connection, drone_id: str | None = None, limit: int = 100, offset: int = 0
) -> list[Mission]:
    if drone_id is not None:
        rows = await conn.fetch(
            f"SELECT {_MISSION_COLS} FROM mission.mission WHERE drone_id = $1 "
            "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            drone_id,
            limit,
            offset,
        )
    else:
        rows = await conn.fetch(
            f"SELECT {_MISSION_COLS} FROM mission.mission ORDER BY created_at DESC "
            "LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
    return [_mission(r) for r in rows]


async def count_missions(conn: asyncpg.Connection, drone_id: str | None = None) -> int:
    if drone_id is not None:
        return await conn.fetchval(
            "SELECT count(*) FROM mission.mission WHERE drone_id = $1", drone_id
        )
    return await conn.fetchval("SELECT count(*) FROM mission.mission")


async def get_mission(conn: asyncpg.Connection, mission_pk: UUID) -> Mission | None:
    r = await conn.fetchrow(
        f"SELECT {_MISSION_COLS} FROM mission.mission WHERE id = $1", mission_pk
    )
    return _mission(r) if r else None


async def get_mission_by_mission_id(conn: asyncpg.Connection, mission_id: str) -> Mission | None:
    r = await conn.fetchrow(
        f"SELECT {_MISSION_COLS} FROM mission.mission WHERE mission_id = $1", mission_id
    )
    return _mission(r) if r else None


async def mark_dispatched(conn: asyncpg.Connection, mission_pk: UUID) -> None:
    await conn.execute(
        "UPDATE mission.mission SET status = 'dispatched', dispatched_at = now() "
        "WHERE id = $1 AND status = 'created'",
        mission_pk,
    )


async def apply_progress(
    conn: asyncpg.Connection,
    mission_id: str,
    status: str,
    current_item: int | None,
    total_items: int | None,
) -> None:
    """依進度事件更新任務狀態。首個終態為準:已達終態者忽略後續(冪等去重)。"""
    finished = "now()" if status in TERMINAL_STATUSES else "finished_at"
    await conn.execute(
        f"UPDATE mission.mission SET status = $2, current_item = $3, total_items = "
        f"COALESCE($4, total_items), finished_at = {finished} "
        "WHERE mission_id = $1 AND status NOT IN ('completed', 'failed')",
        mission_id,
        status,
        current_item,
        total_items,
    )


# ---- audit(G14 稽核查詢;寫入在 mission_svc.audit) ----
_AUDIT_COLS = "id, at, actor, role, action, resource_type, resource_id, details, source_ip"


def _audit(r: asyncpg.Record) -> AuditEntry:
    d = dict(r)
    # jsonb 由 asyncpg 以字串回傳(未設 codec);轉回 dict 供模型
    if isinstance(d.get("details"), str):
        d["details"] = json.loads(d["details"])
    return AuditEntry.model_validate(d)


async def list_audit(
    conn: asyncpg.Connection,
    resource_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditEntry]:
    if resource_type is not None:
        rows = await conn.fetch(
            f"SELECT {_AUDIT_COLS} FROM mission.audit_log WHERE resource_type = $1 "
            "ORDER BY at DESC, id DESC LIMIT $2 OFFSET $3",
            resource_type,
            limit,
            offset,
        )
    else:
        rows = await conn.fetch(
            f"SELECT {_AUDIT_COLS} FROM mission.audit_log "
            "ORDER BY at DESC, id DESC LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
    return [_audit(r) for r in rows]


async def count_audit(conn: asyncpg.Connection, resource_type: str | None = None) -> int:
    if resource_type is not None:
        return await conn.fetchval(
            "SELECT count(*) FROM mission.audit_log WHERE resource_type = $1", resource_type
        )
    return await conn.fetchval("SELECT count(*) FROM mission.audit_log")

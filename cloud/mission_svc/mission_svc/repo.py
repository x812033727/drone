"""mission-svc 資料存取(asyncpg)。waypoints 以 jsonb 存;純函式部分可單測。"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from mission_svc.dispatch import TERMINAL_STATUSES
from mission_svc.models import AuditEntry, Mission, MissionCreate, Route, RouteCreate

_ROUTE_COLS = "id, name, org_id, waypoints, rtl_after_last, created_at"
_MISSION_COLS = (
    "id, mission_id, route_id, org_id, drone_id, status, waypoints, rtl_after_last, "
    "current_item, total_items, dispatched_at, finished_at, created_at"
)


# ---- 租戶(G11)過濾小工具 ----
# org 語義:None = 不加 org 過濾(admin 跨 org / 內部呼叫);字串 = WHERE org_id = 該值。
def _where(conds: list[str]) -> str:
    return (" WHERE " + " AND ".join(conds)) if conds else ""


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
async def create_route(conn: asyncpg.Connection, body: RouteCreate, org: str) -> Route:
    """建立航線。org 一律取自呼叫者 claim(不採信 client),寫入為租戶邊界。"""
    wps = json.dumps([w.model_dump() for w in body.waypoints])
    r = await conn.fetchrow(
        "INSERT INTO mission.route (name, org_id, waypoints, rtl_after_last) "
        f"VALUES ($1, $2, $3::jsonb, $4) RETURNING {_ROUTE_COLS}",
        body.name,
        org,
        wps,
        body.rtl_after_last,
    )
    return _route(r)


async def list_routes(
    conn: asyncpg.Connection, org: str | None = None, limit: int = 100, offset: int = 0
) -> list[Route]:
    conds: list[str] = []
    params: list[Any] = []
    if org is not None:
        params.append(org)
        conds.append(f"org_id = ${len(params)}")
    params.append(limit)
    lim = len(params)
    params.append(offset)
    off = len(params)
    rows = await conn.fetch(
        f"SELECT {_ROUTE_COLS} FROM mission.route{_where(conds)} "
        f"ORDER BY created_at DESC LIMIT ${lim} OFFSET ${off}",
        *params,
    )
    return [_route(r) for r in rows]


async def count_routes(conn: asyncpg.Connection, org: str | None = None) -> int:
    if org is not None:
        return await conn.fetchval("SELECT count(*) FROM mission.route WHERE org_id = $1", org)
    return await conn.fetchval("SELECT count(*) FROM mission.route")


async def get_route(
    conn: asyncpg.Connection, route_id: UUID, org: str | None = None
) -> Route | None:
    """依 id 取航線;org 指定時加租戶過濾(跨 org 回 None → 端點轉 404)。"""
    if org is not None:
        r = await conn.fetchrow(
            f"SELECT {_ROUTE_COLS} FROM mission.route WHERE id = $1 AND org_id = $2",
            route_id,
            org,
        )
    else:
        r = await conn.fetchrow(f"SELECT {_ROUTE_COLS} FROM mission.route WHERE id = $1", route_id)
    return _route(r) if r else None


# ---- mission ----
async def create_mission(
    conn: asyncpg.Connection, body: MissionCreate, org: str
) -> Mission | None:
    """由 route 建任務:凍結 route 當下航點、產生 mission_id。org 取自呼叫者 claim。

    route 以呼叫者 org 過濾查找:route 不存在或屬他 org 皆回 None(端點轉 404,
    杜絕跨 org 以他人 route 建任務)。mission.org_id 綁定呼叫者 org。
    """
    route = await get_route(conn, body.route_id, org)
    if route is None:
        return None
    wps = json.dumps([w.model_dump() for w in route.waypoints])
    r = await conn.fetchrow(
        "INSERT INTO mission.mission "
        "(mission_id, route_id, org_id, drone_id, waypoints, rtl_after_last, total_items) "
        f"VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7) RETURNING {_MISSION_COLS}",
        new_mission_id(),
        body.route_id,
        org,
        body.drone_id,
        wps,
        route.rtl_after_last,
        len(route.waypoints),
    )
    return _mission(r)


async def list_missions(
    conn: asyncpg.Connection,
    drone_id: str | None = None,
    org: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Mission]:
    conds: list[str] = []
    params: list[Any] = []
    if drone_id is not None:
        params.append(drone_id)
        conds.append(f"drone_id = ${len(params)}")
    if org is not None:
        params.append(org)
        conds.append(f"org_id = ${len(params)}")
    params.append(limit)
    lim = len(params)
    params.append(offset)
    off = len(params)
    rows = await conn.fetch(
        f"SELECT {_MISSION_COLS} FROM mission.mission{_where(conds)} "
        f"ORDER BY created_at DESC LIMIT ${lim} OFFSET ${off}",
        *params,
    )
    return [_mission(r) for r in rows]


async def count_missions(
    conn: asyncpg.Connection, drone_id: str | None = None, org: str | None = None
) -> int:
    conds: list[str] = []
    params: list[Any] = []
    if drone_id is not None:
        params.append(drone_id)
        conds.append(f"drone_id = ${len(params)}")
    if org is not None:
        params.append(org)
        conds.append(f"org_id = ${len(params)}")
    return await conn.fetchval(f"SELECT count(*) FROM mission.mission{_where(conds)}", *params)


async def get_mission(
    conn: asyncpg.Connection, mission_pk: UUID, org: str | None = None
) -> Mission | None:
    """依 id 取任務;org 指定時加租戶過濾(跨 org 回 None → 端點轉 404)。"""
    if org is not None:
        r = await conn.fetchrow(
            f"SELECT {_MISSION_COLS} FROM mission.mission WHERE id = $1 AND org_id = $2",
            mission_pk,
            org,
        )
    else:
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


# ---- 用量計量(G30):usage_counter 依 (org, metric, 日期) 原子遞增 ----
_USAGE_INC = """
INSERT INTO mission.usage_counter (org_id, metric, period, count)
VALUES ($1, $2, $3, 1)
ON CONFLICT (org_id, metric, period)
DO UPDATE SET count = mission.usage_counter.count + 1
"""


async def increment_usage(
    conn: asyncpg.Connection, org: str, metric: str, period: date
) -> None:
    """計費相關操作成功後 +1(org, metric, 當日)。period 由呼叫端傳入(UTC 日)。"""
    await conn.execute(_USAGE_INC, org, metric, period)


async def usage_count(conn: asyncpg.Connection, org: str, metric: str, period: date) -> int:
    """某租戶某日某 metric 的計數(每日量配額判定用);無列回 0。"""
    val = await conn.fetchval(
        "SELECT count FROM mission.usage_counter WHERE org_id = $1 AND metric = $2 AND period = $3",
        org,
        metric,
        period,
    )
    return int(val) if val is not None else 0


async def get_usage(conn: asyncpg.Connection, org: str, period: date) -> dict[str, int]:
    """某租戶某日各 metric 計數(GET /api/v1/usage 的當日 counters)。"""
    rows = await conn.fetch(
        "SELECT metric, count FROM mission.usage_counter WHERE org_id = $1 AND period = $2",
        org,
        period,
    )
    return {r["metric"]: int(r["count"]) for r in rows}


async def get_usage_totals(conn: asyncpg.Connection, org: str) -> dict[str, int]:
    """某租戶各 metric 的歷來累計(跨所有日期彙總)。"""
    rows = await conn.fetch(
        "SELECT metric, sum(count)::bigint AS total FROM mission.usage_counter "
        "WHERE org_id = $1 GROUP BY metric",
        org,
    )
    return {r["metric"]: int(r["total"]) for r in rows}


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

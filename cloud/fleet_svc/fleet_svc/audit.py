"""審計軌跡寫入(G14)。變更端點成功後旁路記一筆到 fleet.audit_log。

設計要點:
- **旁路 + best-effort**:audit 寫入失敗只記 log,絕不讓主操作失敗或改變其回應。
- actor/role 由 auth 依賴取得的 JWT claims 推導;dev 模式(認證停用)claims 為
  {"sub": "dev", "roles": ["admin"]},故 actor='dev'。
- SQL 寫在此(小 helper),查詢(list/count)走 repo.py,與分頁慣例一致。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import Request

from fleet_svc.auth import ROLE_ORDER, extract_roles, role_rank

log = logging.getLogger("fleet_svc.audit")

_RANK_TO_ROLE = {rank: name for name, rank in ROLE_ORDER.items()}

_INSERT = """
INSERT INTO fleet.audit_log
    (actor, role, action, resource_type, resource_id, details, source_ip)
VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
"""


def actor_of(claims: dict) -> tuple[str, str | None]:
    """從 JWT claims 推導 (actor, role)。無身分時 actor='anonymous'、role=None。"""
    actor = claims.get("sub") or claims.get("preferred_username") or claims.get("username")
    role = _RANK_TO_ROLE.get(role_rank(extract_roles(claims)))
    return (actor or "anonymous", role)


async def record(
    conn: asyncpg.Connection,
    *,
    claims: dict,
    action: str,
    resource_type: str,
    resource_id: Any | None = None,
    details: dict | None = None,
    request: Request | None = None,
) -> None:
    """記一筆審計(best-effort)。任何例外都吞掉並記 log——審計不可弄垮主操作。"""
    actor, role = actor_of(claims)
    source_ip = request.client.host if request is not None and request.client else None
    rid = str(resource_id) if isinstance(resource_id, UUID) else resource_id
    try:
        await conn.execute(
            _INSERT,
            actor,
            role,
            action,
            resource_type,
            rid,
            json.dumps(details or {}),
            source_ip,
        )
    except Exception as e:  # noqa: BLE001 — 審計為旁路,任何失敗都不得外溢
        log.warning(
            "審計寫入失敗(不影響主操作):action=%s resource=%s/%s err=%s",
            action,
            resource_type,
            rid,
            e,
        )

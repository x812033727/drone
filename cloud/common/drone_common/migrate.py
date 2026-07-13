"""共用輕量前向 SQL migration runner(asyncpg 原生)。schema 與 migrations 目錄由
呼叫端參數化——各服務(fleet=schema `fleet` / mission=schema `mission`)傳自己的
migrations/ 目錄與 schema。Wave 1 A1 去重(原 fleet_svc.migrate / mission_svc.migrate)。

契合本專案 SQL-first 風格,不引入 SQLAlchemy/psycopg。規則:
- migrations/*.sql 依檔名排序逐檔套用;版本 = 檔名(不含副檔名)。
- 已套用者記於 <schema>.schema_migrations,跳過;每檔在單一交易內套用(全成或全退)。
- 只前向、不 down;改 schema 一律新增檔案(不改既有已套用檔)。
"""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

log = logging.getLogger("drone_common.migrate")


def _ensure_table_sql(schema: str) -> str:
    return (
        f"CREATE SCHEMA IF NOT EXISTS {schema};\n"
        f"CREATE TABLE IF NOT EXISTS {schema}.schema_migrations (\n"
        f"    version    text PRIMARY KEY,\n"
        f"    applied_at timestamptz NOT NULL DEFAULT now()\n"
        f");\n"
    )


def _migration_files(migrations_dir: Path) -> list[Path]:
    """回傳依檔名排序的 .sql migration 檔清單。"""
    return sorted(migrations_dir.glob("*.sql"))


async def apply_migrations(
    conn: asyncpg.Connection, schema: str, migrations_dir: Path
) -> list[str]:
    """套用所有未套用的 migration,回傳本次實際套用的版本清單。"""
    await conn.execute(_ensure_table_sql(schema))
    applied: set[str] = {
        r["version"]
        for r in await conn.fetch(f"SELECT version FROM {schema}.schema_migrations")
    }
    newly: list[str] = []
    for path in _migration_files(migrations_dir):
        version = path.stem
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                f"INSERT INTO {schema}.schema_migrations (version) VALUES ($1)", version
            )
        log.info("已套用 migration:%s", version)
        newly.append(version)
    return newly


async def run_cli(schema: str, migrations_dir: Path) -> None:
    """CLI 入口:連 PG_DSN、套用 migration 後結束。供 Helm pre-upgrade hook Job 呼叫。

    DB 未就緒時重試(同 main.py 的等待策略),避免 hook 在 DB 剛起時誤判失敗。
    """
    import asyncio
    import os

    dsn = os.environ.get("PG_DSN", "postgresql://drone:dronedev@localhost:5432/drone")
    attempts, retry_s = 30, 2
    conn: asyncpg.Connection | None = None
    for attempt in range(1, attempts + 1):
        try:
            conn = await asyncpg.connect(dsn, command_timeout=30)
            break
        except (asyncpg.PostgresError, OSError) as e:
            if attempt == attempts:
                raise
            log.warning("PostgreSQL 連線失敗(%d/%d):%s;重試", attempt, attempts, e)
            await asyncio.sleep(retry_s)
    assert conn is not None
    try:
        applied = await apply_migrations(conn, schema, migrations_dir)
        log.info("migration 完成:本次套用 %d 檔:%s", len(applied), ", ".join(applied) or "(無)")
    finally:
        await conn.close()

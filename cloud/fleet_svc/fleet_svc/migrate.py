"""輕量前向 SQL migration runner(asyncpg 原生)。

契合本專案 SQL-first 風格,不引入 SQLAlchemy/psycopg。規則:
- migrations/*.sql 依檔名排序逐檔套用;版本 = 檔名(不含副檔名)。
- 已套用者記於 fleet.schema_migrations,跳過;每檔在單一交易內套用(全成或全退)。
- 只前向、不 down;改 schema 一律新增檔案(不改既有已套用檔)。
"""

import logging
from pathlib import Path

import asyncpg

log = logging.getLogger("fleet_svc.migrate")

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

_ENSURE_TABLE = """
CREATE SCHEMA IF NOT EXISTS fleet;
CREATE TABLE IF NOT EXISTS fleet.schema_migrations (
    version    text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
"""


def _migration_files(migrations_dir: Path) -> list[Path]:
    """回傳依檔名排序的 .sql migration 檔清單。"""
    return sorted(migrations_dir.glob("*.sql"))


async def apply_migrations(
    conn: asyncpg.Connection, migrations_dir: Path | None = None
) -> list[str]:
    """套用所有未套用的 migration,回傳本次實際套用的版本清單。"""
    migrations_dir = migrations_dir or MIGRATIONS_DIR
    await conn.execute(_ENSURE_TABLE)
    applied: set[str] = {
        r["version"] for r in await conn.fetch("SELECT version FROM fleet.schema_migrations")
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
                "INSERT INTO fleet.schema_migrations (version) VALUES ($1)", version
            )
        log.info("已套用 migration:%s", version)
        newly.append(version)
    return newly


async def _run_cli() -> None:
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
        applied = await apply_migrations(conn)
        log.info("migration 完成:本次套用 %d 檔:%s", len(applied), ", ".join(applied) or "(無)")
    finally:
        await conn.close()


def main() -> None:
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_run_cli())


if __name__ == "__main__":
    main()

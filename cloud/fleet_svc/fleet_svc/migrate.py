"""fleet-svc migration 進入點(schema=`fleet`)。runner 實作在 drone_common.migrate
(Wave 1 A1 去重)。保留 apply_migrations(conn) 簽名與 `python -m fleet_svc.migrate`
CLI(Helm pre-upgrade hook Job 呼叫)不變。
"""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg
from drone_common import migrate as _migrate

SCHEMA = "fleet"
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


async def apply_migrations(
    conn: asyncpg.Connection, migrations_dir: Path | None = None
) -> list[str]:
    """套用所有未套用的 migration,回傳本次實際套用的版本清單。"""
    return await _migrate.apply_migrations(conn, SCHEMA, migrations_dir or MIGRATIONS_DIR)


def main() -> None:
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_migrate.run_cli(SCHEMA, MIGRATIONS_DIR))


if __name__ == "__main__":
    main()

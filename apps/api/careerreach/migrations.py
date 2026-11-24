from __future__ import annotations

import asyncio
from pathlib import Path
from typing import LiteralString, cast

from psycopg import AsyncConnection
from psycopg.sql import SQL

from .config import get_settings

_MIGRATION_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "infrastructure" / "database" / "migrations"
)
_MIGRATION_LOCK_ID = 721041219


async def migrate() -> None:
    database_url = get_settings().database_url
    if database_url is None:
        raise RuntimeError("Set CAREERREACH_DATABASE_URL before applying database migrations.")
    migrations = sorted(_MIGRATION_DIRECTORY.glob("[0-9][0-9][0-9]_*.sql"))
    async with await AsyncConnection.connect(database_url) as connection:
        await connection.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK_ID,))
        await connection.commit()
        try:
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migration "
                "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await connection.commit()
            cursor = await connection.execute("SELECT version FROM schema_migration")
            applied = {row[0] for row in await cursor.fetchall()}
            for migration in migrations:
                version = migration.stem.split("_", maxsplit=1)[0]
                if version in applied:
                    continue
                migration_path = migration.resolve(strict=True)
                if migration.is_symlink() or not migration_path.is_relative_to(
                    _MIGRATION_DIRECTORY.resolve(strict=True)
                ):
                    raise RuntimeError("Database migration path escaped the migrations directory.")
                async with connection.transaction():
                    await connection.execute(
                        SQL(cast(LiteralString, migration_path.read_text(encoding="utf-8"))),
                        prepare=False,
                    )
                    await connection.execute(
                        "INSERT INTO schema_migration (version) VALUES (%s)", (version,)
                    )
        finally:
            await connection.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_ID,))
            await connection.commit()


def main() -> None:
    asyncio.run(migrate())


if __name__ == "__main__":
    main()

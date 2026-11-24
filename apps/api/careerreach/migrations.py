from __future__ import annotations

import asyncio
from pathlib import Path
from typing import LiteralString, cast

from psycopg import AsyncConnection
from psycopg.sql import SQL, Identifier, Literal

from .config import get_settings

_MIGRATION_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "infrastructure" / "database" / "migrations"
)
_MIGRATION_LOCK_ID = 721041219


async def migrate() -> None:
    settings = get_settings()
    database_url = settings.migration_database_url or settings.database_url
    if database_url is None:
        raise RuntimeError("Set CAREERREACH_DATABASE_URL before applying database migrations.")
    if (settings.runtime_database_user is None) != (settings.runtime_database_password is None):
        raise RuntimeError(
            "Set both CAREERREACH_RUNTIME_DATABASE_USER and "
            "CAREERREACH_RUNTIME_DATABASE_PASSWORD to provision the app database role."
        )
    migrations = sorted(_MIGRATION_DIRECTORY.glob("[0-9][0-9][0-9]_*.sql"))
    async with await AsyncConnection.connect(database_url) as connection:
        await connection.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK_ID,))
        await connection.commit()
        try:
            if settings.runtime_database_user is not None:
                runtime_password = settings.runtime_database_password
                if runtime_password is None:
                    raise RuntimeError("Runtime database credentials are incomplete.")
                cursor = await connection.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = %s",
                    (settings.runtime_database_user,),
                )
                role_exists = await cursor.fetchone() is not None
                role_command = (
                    SQL("ALTER ROLE {} LOGIN PASSWORD {}")
                    if role_exists
                    else SQL("CREATE ROLE {} LOGIN PASSWORD {}")
                )
                database_name = connection.info.dbname
                async with connection.transaction():
                    await connection.execute(
                        role_command.format(
                            Identifier(settings.runtime_database_user),
                            Literal(runtime_password.get_secret_value()),
                        )
                    )
                    await connection.execute(
                        SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                            Identifier(database_name),
                            Identifier(settings.runtime_database_user),
                        )
                    )
                    await connection.execute(
                        SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
                            Identifier(settings.runtime_database_user)
                        )
                    )
                    await connection.execute(
                        SQL(
                            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT "
                            "SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
                        ).format(Identifier(settings.runtime_database_user))
                    )
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

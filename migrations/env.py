import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Make src.* importable from apps/api/
sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "api"))

from src.models.base import Base  # noqa: E402
import src.models  # noqa: E402,F401 — registers all models on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return (
        os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url") or ""
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema="coach",
        include_schemas=True,
    )
    with context.begin_transaction():
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS coach"))
        connection.execute(text("SET search_path TO coach, public"))
        # Fail fast if another connection holds a lock (e.g. long-running query).
        # Transactional DDL rolls back cleanly on timeout.
        connection.execute(text("SET lock_timeout = '5s'"))
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = create_async_engine(
        _url(),
        connect_args={"prepared_statement_cache_size": 0},
    )
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

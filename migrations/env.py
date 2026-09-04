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


#: Emitted by the offline path so a database provisioned from ``--sql`` output is
#: byte-for-byte the database the online path builds. Batch 253 (CR236-08).
#: Alembic appends its own terminator, so these carry none.
_PREAMBLE = (
    "CREATE SCHEMA IF NOT EXISTS coach",
    "SET search_path TO coach, public",
    # Fail fast if another connection holds a lock (e.g. long-running query).
    # Transactional DDL rolls back cleanly on timeout.
    "SET lock_timeout = '5s'",
)


def run_migrations_offline() -> None:
    """Render the migrations as SQL without a database.

    Batch 253 (CR236-08): this path used to configure *none* of what the online
    path configures, so ``alembic upgrade base:head --sql`` — the offline
    validation route this project relies on when no Postgres is available —
    rendered ``CREATE TABLE alembic_version`` with **no schema qualifier**. It
    landed in whatever ``search_path`` resolved to (``public``) while the online
    path writes it to ``coach``. A database provisioned by piping that SQL was
    then invisible to ``alembic current``: the next online ``upgrade head`` saw an
    empty ``coach.alembic_version``, re-ran ``001``, and failed on the first
    ``CREATE TABLE`` that already existed. The offline SQL also silently omitted
    the 5s ``lock_timeout`` guard.
    """
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="coach",
        include_schemas=True,
    )
    with context.begin_transaction():
        for statement in _PREAMBLE:
            context.execute(statement)
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

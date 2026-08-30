from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.models.base import Base  # noqa: F401 — re-exported for callers

engine = create_async_engine(
    settings.database_url,
    # Batch 232.3: sized against the pooler's ceiling, not chosen freely. These
    # were a hardcoded 10 + 10, so the app would open up to 20 connections
    # against a session-mode pooler that grants 15 — see ``config.Settings`` for
    # the budget and the validator that enforces it.
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False,
    # All connections land in the coach schema; public is the fallback for
    # Supabase system functions (gen_random_uuid etc).
    # prepared_statement_cache_size=0: asyncpg's per-connection prepared-statement
    # cache is unsafe behind any Supavisor pooler, because a cached statement is
    # bound to one server connection the pooler is free to swap. Production is on
    # port **5432, session mode** — this comment used to claim port 6543,
    # transaction mode, which the app has never used (Batch 232.3). Keeping the
    # cache off costs nothing and is also the prerequisite for transaction mode,
    # deliberately not taken here; see DECISIONS.md.
    connect_args={
        "server_settings": {"search_path": "coach,public"},
        "prepared_statement_cache_size": 0,
    },
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

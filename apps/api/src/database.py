from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.models.base import Base  # noqa: F401 — re-exported for callers

engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False,
    # All connections land in the coach schema; public is the fallback for
    # Supabase system functions (gen_random_uuid etc).
    connect_args={"server_settings": {"search_path": "coach,public"}},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

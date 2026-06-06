from collections.abc import AsyncIterator
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from common.config import settings

_password = quote_plus(settings.PG_PASSWORD)
DATABASE_URL = (
    f"postgresql+asyncpg://{settings.PG_USER}:{_password}"
    f"@{settings.PG_HOST}:{settings.PG_PORT}/{settings.PG_DB}"
)

async_engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_pg_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session

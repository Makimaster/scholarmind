from collections.abc import AsyncIterator
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from common.config import settings

_password = quote_plus(settings.MYSQL_PASSWORD)
DATABASE_URL = (
    f"mysql+aiomysql://{settings.MYSQL_USER}:{_password}"
    f"@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DB}"
    "?charset=utf8mb4"
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


async def get_mysql_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session

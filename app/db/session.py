from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    str(settings.database_url),
    echo=settings.db_echo,
    pool_pre_ping=settings.pool_pre_ping,
    pool_size=settings.pool_size,
    max_overflow=settings.pool_max_overflow,
    pool_recycle=settings.pool_recycle,
)


async_session_maker = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session


DBSessionDep = Annotated[AsyncSession, Depends(get_session)]

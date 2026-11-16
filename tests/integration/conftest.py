from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, event, make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from app.core.config import settings
from app.db.session import get_session
from app.main import app
from app.models import Base
from app.storage.s3 import S3Storage, get_storage

dev_url = make_url(settings.database_url)
test_engine = create_async_engine(dev_url.set(database=f"{dev_url.database}_test"))
test_session_maker = async_sessionmaker(bind=test_engine, expire_on_commit=False)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "alembic"


def run_migrations(connection: Connection) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["connection"] = connection
    connection.execute(text("DROP SCHEMA public CASCADE"))
    connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.fixture(scope="session", autouse=True)
async def create_tables() -> AsyncIterator[None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(run_migrations)
    yield
    await test_engine.dispose()


@pytest.fixture(autouse=True)
async def clean_tables() -> AsyncIterator[None]:
    yield
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with test_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))


async def override_get_session() -> AsyncIterator[AsyncSession]:
    async with test_session_maker() as session:
        yield session


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with test_session_maker() as session:
        yield session


@pytest.fixture
def sql_statements() -> Iterator[list[str]]:
    statements: list[str] = []

    def record(*args: Any) -> None:
        statements.append(args[2])

    event.listen(test_engine.sync_engine, "before_cursor_execute", record)
    yield statements
    event.remove(test_engine.sync_engine, "before_cursor_execute", record)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_storage] = lambda: MagicMock(spec=S3Storage)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def make_auth_headers(client: AsyncClient) -> Callable[[str], Awaitable[dict[str, str]]]:
    async def _make(login: str) -> dict[str, str]:
        credentials = {"login": login, "password": "secret123"}
        await client.post("/auth", json={**credentials, "repeat_password": "secret123"})
        response = await client.post("/login", json=credentials)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _make


@pytest.fixture
async def auth_headers(
    make_auth_headers: Callable[[str], Awaitable[dict[str, str]]],
) -> dict[str, str]:
    return await make_auth_headers("owner")

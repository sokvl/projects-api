from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError
from app.models.user import User
from app.services.auth import AuthService


@pytest.fixture
def users() -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_login.return_value = None
    return repo


@pytest.fixture
def session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(users: AsyncMock, session: AsyncMock) -> AuthService:
    return AuthService(users, session)


async def test_register_creates_user(
    service: AuthService, users: AsyncMock, session: AsyncMock
) -> None:
    user = await service.register("marek", "secret123")

    assert user.login == "marek"
    assert user.password_hash != "secret123"
    assert user.password_hash.startswith("$argon2id$")
    users.add.assert_awaited_once_with(user)
    session.commit.assert_awaited_once()


async def test_register_existing_login_raises_conflict(
    service: AuthService, users: AsyncMock, session: AsyncMock
) -> None:
    users.get_by_login.return_value = User(login="marek", password_hash="x")

    with pytest.raises(ConflictError):
        await service.register("marek", "secret123")

    users.add.assert_not_awaited()
    session.commit.assert_not_awaited()


class FakeDriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate


async def test_register_concurrent_insert_raises_conflict(
    service: AuthService, users: AsyncMock, session: AsyncMock
) -> None:
    users.add.side_effect = IntegrityError("INSERT INTO users", {}, FakeDriverError("23505"))

    with pytest.raises(ConflictError):
        await service.register("marek", "secret123")

    session.commit.assert_not_awaited()


async def test_register_other_integrity_error_is_not_conflict(
    service: AuthService, users: AsyncMock, session: AsyncMock
) -> None:
    users.add.side_effect = IntegrityError("INSERT INTO users", {}, FakeDriverError("23502"))

    with pytest.raises(IntegrityError):
        await service.register("marek", "secret123")

    session.commit.assert_not_awaited()

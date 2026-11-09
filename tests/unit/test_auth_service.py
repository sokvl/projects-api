import uuid
from unittest.mock import AsyncMock

import jwt
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import JWT_ALGORITHM, password_hasher
from app.models.user import User
from app.services.auth import DUMMY_PASSWORD_HASH, AuthService
from tests.unit.fakes import FakeDriverError


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


@pytest.fixture
def existing_user() -> User:
    return User(id=uuid.uuid4(), login="marek", password_hash=password_hasher.hash("secret123"))


async def test_login_returns_token_with_user_id(
    service: AuthService, users: AsyncMock, existing_user: User
) -> None:
    users.get_by_login.return_value = existing_user

    token = await service.login("marek", "secret123")

    claims = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    assert claims["sub"] == str(existing_user.id)
    assert claims["exp"] - claims["iat"] == settings.jwt_expire_minutes * 60


async def test_login_wrong_password_and_unknown_login_give_same_error(
    service: AuthService, users: AsyncMock, existing_user: User
) -> None:
    users.get_by_login.return_value = existing_user
    with pytest.raises(UnauthorizedError) as wrong_password:
        await service.login("marek", "wrong-pass")

    users.get_by_login.return_value = None
    with pytest.raises(UnauthorizedError) as unknown_login:
        await service.login("nobody", "secret123")

    assert str(wrong_password.value) == str(unknown_login.value)


async def test_login_unknown_user_still_verifies_password(
    service: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    verify = AsyncMock(return_value=False)
    monkeypatch.setattr("app.services.auth.verify_password", verify)

    with pytest.raises(UnauthorizedError):
        await service.login("nobody", "secret123")

    verify.assert_awaited_once_with("secret123", DUMMY_PASSWORD_HASH)

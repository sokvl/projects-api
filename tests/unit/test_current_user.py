import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import get_current_user
from app.core.errors import UnauthorizedError
from app.core.security import create_access_token
from app.models.user import User


def bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


async def test_returns_user_for_valid_token() -> None:
    user = User(id=uuid.uuid4(), login="marek", password_hash="x")
    users = AsyncMock()
    users.get_by_id.return_value = user

    assert await get_current_user(users, bearer(create_access_token(user.id))) is user
    users.get_by_id.assert_awaited_once_with(user.id)


async def test_missing_credentials_raises_unauthorized() -> None:
    with pytest.raises(UnauthorizedError):
        await get_current_user(AsyncMock(), None)


async def test_deleted_user_raises_unauthorized() -> None:
    users = AsyncMock()
    users.get_by_id.return_value = None

    with pytest.raises(UnauthorizedError):
        await get_current_user(users, bearer(create_access_token(uuid.uuid4())))

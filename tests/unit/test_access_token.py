import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest

from app.core.config import settings
from app.core.errors import UnauthorizedError
from app.core.security import JWT_ALGORITHM, create_access_token, decode_access_token

USER_ID = uuid.uuid4()


def payload(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {"sub": str(USER_ID), "iat": now, "exp": now + timedelta(minutes=5)} | overrides


def sign(claims: dict[str, Any], secret: str = settings.jwt_secret) -> str:
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


def test_decode_returns_user_id_from_created_token() -> None:
    assert decode_access_token(create_access_token(USER_ID)) == USER_ID


INVALID_TOKENS = {
    "expired": sign(payload(exp=datetime.now(UTC) - timedelta(minutes=1))),
    "wrong_secret": sign(payload(), secret="another-secret-that-is-long-enough-123"),
    "alg_none": jwt.encode(payload(), "", algorithm="none"),
    "missing_exp": sign({k: v for k, v in payload().items() if k != "exp"}),
    "missing_sub": sign({k: v for k, v in payload().items() if k != "sub"}),
    "sub_not_uuid": sign(payload(sub="123")),
    "garbage": "not-a-jwt",
}


@pytest.mark.parametrize("token", INVALID_TOKENS.values(), ids=INVALID_TOKENS.keys())
def test_decode_rejects_invalid_token(token: str) -> None:
    with pytest.raises(UnauthorizedError):
        decode_access_token(token)

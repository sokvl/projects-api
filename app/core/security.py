import uuid
from datetime import UTC, datetime, timedelta

import jwt
from anyio import CapacityLimiter, to_thread
from pwdlib import PasswordHash

from app.core.config import settings
from app.core.errors import UnauthorizedError

JWT_ALGORITHM = "HS256"

password_hasher = PasswordHash.recommended()

# Sized for t3.micro (2 vCPU, 1 GiB): each argon2 hash holds 64 MiB, so 4 at once use 256 MiB
hash_limiter = CapacityLimiter(4)


async def hash_password(password: str) -> str:
    return await to_thread.run_sync(password_hasher.hash, password, limiter=hash_limiter)


async def verify_password(password: str, hashed_password: str) -> bool:
    return await to_thread.run_sync(
        password_hasher.verify, password, hashed_password, limiter=hash_limiter
    )


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
        return uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, ValueError) as err:
        raise UnauthorizedError("Invalid or expired token") from err

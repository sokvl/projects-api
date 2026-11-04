import uuid
from datetime import UTC, datetime, timedelta

import jwt
from anyio import CapacityLimiter, to_thread
from pwdlib import PasswordHash

from app.core.config import settings

JWT_ALGORITHM = "HS256"

password_hasher = PasswordHash.recommended()

# Might be tuned later or replaced by rate limiting.
hash_limiter = CapacityLimiter(20)

DUMMY_PASSWORD_HASH = password_hasher.hash("timing-attack-dummy")


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

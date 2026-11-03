from anyio import CapacityLimiter, to_thread
from pwdlib import PasswordHash

password_hasher = PasswordHash.recommended()

# Might be tuned later or replaced by rate limiting.
hash_limiter = CapacityLimiter(20)


async def hash_password(password: str) -> str:
    return await to_thread.run_sync(password_hasher.hash, password, limiter=hash_limiter)


async def verify_password(password: str, hashed_password: str) -> bool:
    return await to_thread.run_sync(
        password_hasher.verify, password, hashed_password, limiter=hash_limiter
    )

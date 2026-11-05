from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    hash_password,
    password_hasher,
    verify_password,
)
from app.db.errors import is_unique_violation
from app.models.user import User
from app.repositories.user import UserRepository

DUMMY_PASSWORD_HASH = password_hasher.hash("timing-attack-dummy")


# For now service handles sqlalchemy UoW, might refactor later
class AuthService:
    def __init__(self, users_repository: UserRepository, session: AsyncSession) -> None:
        self.users = users_repository
        self.session = session

    async def register(self, login: str, password: str) -> User:
        if await self.users.get_by_login(login):
            raise ConflictError("User already exists!")

        hashed_password = await hash_password(password)
        user_object = User(login=login, password_hash=hashed_password)
        try:
            await self.users.add(user_object)
        except IntegrityError as err:
            if not is_unique_violation(err):
                raise
            raise ConflictError("User already exists!") from err

        await self.session.commit()
        return user_object

    async def login(self, login: str, password: str) -> str:
        user = await self.users.get_by_login(login)
        if user is None:
            await verify_password(password, DUMMY_PASSWORD_HASH)
            raise UnauthorizedError("Invalid login or password")

        if not await verify_password(password, user.password_hash):
            raise UnauthorizedError("Invalid login or password")

        return create_access_token(user.id)

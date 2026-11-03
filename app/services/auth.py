from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.core.security import hash_password
from app.models.user import User
from app.repositories.user import UserRepository


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
            raise ConflictError("User already exists!") from err

        await self.session.commit()
        return user_object

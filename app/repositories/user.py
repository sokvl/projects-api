import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User as UserModel


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_login(self, login: str) -> UserModel | None:
        query = select(UserModel).where(UserModel.login == login)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> UserModel | None:
        return await self.session.get(UserModel, user_id)

    async def add(self, user: UserModel) -> UserModel:
        self.session.add(user)
        await self.session.flush()
        return user

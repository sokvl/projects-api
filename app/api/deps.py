from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import DBSessionDep
from app.models.user import User
from app.repositories.user import UserRepository
from app.storage.s3 import S3Storage, get_storage

bearer_scheme = HTTPBearer(auto_error=False)

S3StorageDep = Annotated[S3Storage, Depends(get_storage)]


async def get_user_repository(session: DBSessionDep) -> UserRepository:
    return UserRepository(session)


UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


async def get_current_user(
    users: UserRepositoryDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise UnauthorizedError("Not authenticated")

    user_id = decode_access_token(credentials.credentials)
    user = await users.get_by_id(user_id)
    if user is None:
        raise UnauthorizedError("Invalid or expired token")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]

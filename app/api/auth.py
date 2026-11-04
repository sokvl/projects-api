from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.db.session import DBSessionDep
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut
from app.services.auth import AuthService

router = APIRouter(tags=["auth"])


async def get_user_repository(session: DBSessionDep) -> UserRepository:
    return UserRepository(session)


UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


async def get_auth_service(users: UserRepositoryDep, session: DBSessionDep) -> AuthService:
    return AuthService(users, session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


@router.post("/auth", status_code=status.HTTP_201_CREATED, response_model=UserOut)
async def register(body: RegisterIn, service: AuthServiceDep) -> User:
    return await service.register(body.login, body.password)


@router.post("/login")
async def login(body: LoginIn, service: AuthServiceDep) -> TokenOut:
    token = await service.login(body.login, body.password)
    return TokenOut(access_token=token)

import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUserDep, S3StorageDep
from app.db.session import DBSessionDep
from app.models.project import Project, ProjectRole
from app.repositories.project import ProjectRepository
from app.repositories.user import UserRepository
from app.schemas.common import Login
from app.schemas.project import MemberOut, ProjectIn, ProjectOut, ProjectWithDocumentsOut
from app.services.project import ProjectService

router = APIRouter(tags=["projects"])


async def get_project_service(session: DBSessionDep, s3_storage: S3StorageDep) -> ProjectService:
    return ProjectService(ProjectRepository(session), UserRepository(session), s3_storage, session)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


@router.post("/projects", status_code=status.HTTP_201_CREATED, response_model=ProjectOut)
async def create_project(
    body: ProjectIn, user: CurrentUserDep, service: ProjectServiceDep
) -> Project:
    return await service.create(user, body.name, body.description)


@router.get("/projects", response_model=list[ProjectWithDocumentsOut])
async def list_projects(user: CurrentUserDep, service: ProjectServiceDep) -> Sequence[Project]:
    return await service.list_users_projects(user)


@router.get("/project/{project_id}/info", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID, user: CurrentUserDep, service: ProjectServiceDep
) -> Project:
    return await service.get(project_id, user)


@router.put("/project/{project_id}/info", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID, body: ProjectIn, user: CurrentUserDep, service: ProjectServiceDep
) -> Project:
    return await service.update(project_id, user, body.name, body.description)


@router.delete("/project/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID, user: CurrentUserDep, service: ProjectServiceDep
) -> None:
    await service.delete(project_id, user)


@router.post(
    "/project/{project_id}/invite", status_code=status.HTTP_201_CREATED, response_model=MemberOut
)
async def invite_to_project(
    project_id: uuid.UUID,
    user: Annotated[Login, Query()],
    owner: CurrentUserDep,
    service: ProjectServiceDep,
) -> MemberOut:
    member = await service.invite(project_id, owner, user)
    return MemberOut(login=user, role=ProjectRole(member.role))

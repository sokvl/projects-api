from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUserDep
from app.db.session import DBSessionDep
from app.models.project import Project
from app.repositories.project import ProjectRepository
from app.schemas.project import ProjectIn, ProjectOut, ProjectWithDocumentsOut
from app.services.project import ProjectService

router = APIRouter(tags=["projects"])


async def get_project_service(session: DBSessionDep) -> ProjectService:
    return ProjectService(ProjectRepository(session), session)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


@router.post("/projects", status_code=status.HTTP_201_CREATED, response_model=ProjectOut)
async def create_project(
    body: ProjectIn, user: CurrentUserDep, service: ProjectServiceDep
) -> Project:
    return await service.create(user, body.name, body.description)


@router.get("/projects", response_model=list[ProjectWithDocumentsOut])
async def list_projects(user: CurrentUserDep, service: ProjectServiceDep) -> Sequence[Project]:
    return await service.list_users_projects(user)

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.models.project import Project, ProjectMember, ProjectRole
from app.models.user import User
from app.repositories.project import ProjectRepository


class ProjectService:
    def __init__(self, projects_repository: ProjectRepository, session: AsyncSession) -> None:
        self.projects = projects_repository
        self.session = session

    async def create(self, owner: User, name: str, description: str | None) -> Project:
        project = Project(name=name, description=description)
        await self.projects.add(project)

        member = ProjectMember(user_id=owner.id, project_id=project.id, role=ProjectRole.OWNER)
        await self.projects.add_member(member)

        await self.session.commit()
        return project

    async def list_users_projects(self, user: User) -> Sequence[Project]:
        return await self.projects.list_users_projects(user.id)

    async def get(self, project_id: uuid.UUID, user: User) -> Project:
        return await self._get_accessible(project_id, user)

    async def update(
        self, project_id: uuid.UUID, user: User, name: str, description: str | None
    ) -> Project:
        project = await self._get_accessible(project_id, user)
        project.name = name
        project.description = description
        await self.session.commit()
        return project

    async def delete(self, project_id: uuid.UUID, user: User) -> None:
        member = await self.projects.get_member(project_id, user.id)
        if member is None:
            raise NotFoundError("Project not found")
        if member.role != ProjectRole.OWNER:
            raise ForbiddenError("Only the owner can delete the project")
        await self.projects.delete(project_id)
        await self.session.commit()

    async def _get_accessible(self, project_id: uuid.UUID, user: User) -> Project:
        project = await self.projects.get_for_member(project_id, user.id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

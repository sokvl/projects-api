from sqlalchemy.ext.asyncio import AsyncSession

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

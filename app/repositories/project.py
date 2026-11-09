import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Project, ProjectMember


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, project: Project) -> Project:
        self.session.add(project)
        await self.session.flush()
        return project

    async def add_member(self, member: ProjectMember) -> ProjectMember:
        self.session.add(member)
        await self.session.flush()
        return member

    async def list_users_projects(self, user_id: uuid.UUID) -> Sequence[Project]:
        query = (
            select(Project)
            .join(ProjectMember)
            .where(ProjectMember.user_id == user_id)
            .order_by(Project.created_at.desc())
            .options(selectinload(Project.documents))
        )
        result = (await self.session.scalars(query)).all()
        return result

    async def get_for_member(self, project_id: uuid.UUID, user_id: uuid.UUID) -> Project | None:
        query = (
            select(Project)
            .join(ProjectMember)
            .where(Project.id == project_id, ProjectMember.user_id == user_id)
        )
        return await self.session.scalar(query)

    async def get_member(self, project_id: uuid.UUID, user_id: uuid.UUID) -> ProjectMember | None:
        return await self.session.get(ProjectMember, (user_id, project_id))

    async def delete(self, project_id: uuid.UUID) -> None:
        await self.session.execute(delete(Project).where(Project.id == project_id))

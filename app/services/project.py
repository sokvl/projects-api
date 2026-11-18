import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.db.errors import is_unique_violation
from app.models.project import Project, ProjectMember, ProjectRole
from app.models.user import User
from app.repositories.project import ProjectRepository
from app.repositories.user import UserRepository
from app.services.access import require_project_ownership
from app.storage.s3 import S3Storage, StorageError, project_prefix

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(
        self,
        projects_repository: ProjectRepository,
        users_repository: UserRepository,
        s3_storage: S3Storage,
        session: AsyncSession,
    ) -> None:
        self.projects = projects_repository
        self.users = users_repository
        self.s3_storage = s3_storage
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
        await require_project_ownership(self.projects, project_id, user)
        await self.projects.delete(project_id)
        await self.session.commit()
        try:
            await self.s3_storage.delete_prefix(project_prefix(project_id))
        except StorageError:
            logger.exception("Could not delete objects of project %s", project_id)

    async def invite(self, project_id: uuid.UUID, owner: User, login: str) -> ProjectMember:
        await require_project_ownership(self.projects, project_id, owner)
        invitee = await self.users.get_by_login(login)
        if invitee is None:
            raise NotFoundError("User not found")
        member = ProjectMember(
            user_id=invitee.id, project_id=project_id, role=ProjectRole.PARTICIPANT
        )
        try:
            await self.projects.add_member(member)
        except IntegrityError as err:
            if not is_unique_violation(err):
                raise
            raise ConflictError("User already has access to the project") from err
        await self.session.commit()
        return member

    async def _get_accessible(self, project_id: uuid.UUID, user: User) -> Project:
        project = await self.projects.get_for_member(project_id, user.id)
        if project is None:
            raise NotFoundError("Project or member not found")
        return project

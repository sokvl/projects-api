import uuid

from app.core.errors import ForbiddenError, NotFoundError
from app.models.project import ProjectRole
from app.models.user import User
from app.repositories.project import ProjectRepository


async def require_project_ownership(
    projects: ProjectRepository, project_id: uuid.UUID, user: User
) -> None:
    member = await projects.get_member(project_id, user.id)
    if member is None:
        raise NotFoundError("Project or member not found")
    if member.role != ProjectRole.OWNER:
        raise ForbiddenError("Only the project owner can do this")

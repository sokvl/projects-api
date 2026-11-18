import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError, ServiceUnavailableError
from app.mail.ses import Mailer, MailError
from app.models.invitation import Invitation
from app.models.project import Project, ProjectRole
from app.models.user import User
from app.repositories.invitation import InvitationRepository
from app.repositories.project import ProjectRepository
from app.services.access import require_project_ownership

logger = logging.getLogger(__name__)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class InvitationService:
    def __init__(
        self,
        projects_repository: ProjectRepository,
        invitations_repository: InvitationRepository,
        mailer: Mailer,
        session: AsyncSession,
    ) -> None:
        self.projects = projects_repository
        self.invitations = invitations_repository
        self.mailer = mailer
        self.session = session

    async def share(self, project_id: uuid.UUID, owner: User, email: str) -> Invitation:
        await require_project_ownership(self.projects, project_id, owner)
        project = await self.projects.get_for_member(project_id, owner.id)
        if project is None:
            raise NotFoundError("Project or member not found")

        # drive-by cleaning
        await self.invitations.delete_expired()
        token = secrets.token_urlsafe(32)
        invitation = Invitation(
            project_id=project_id,
            email=email,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + timedelta(hours=settings.invitation_ttl_hours),
        )
        await self.invitations.add(invitation)
        await self.session.commit()

        try:
            await self.mailer.send(
                email,
                f"Invitation to {project.name}",
                self._body(project.name, token, invitation.expires_at),
            )
        except MailError as err:
            logger.exception("Could not send an invitation to project %s", project_id)
            raise ServiceUnavailableError("Could not send the invitation, try again later") from err
        return invitation

    async def join(self, token: str, user: User) -> Project:
        project_id = await self.invitations.burn(hash_token(token))
        if project_id is None:
            raise NotFoundError("Invitation not found or expired")
        # an existing member keeps their role, and joining again is not an error
        await self.projects.add_member(project_id, user.id, ProjectRole.PARTICIPANT)
        project = await self.projects.get_for_member(project_id, user.id)
        if project is None:
            raise NotFoundError("Invitation not found or expired")
        await self.session.commit()
        return project

    @staticmethod
    def _body(project_name: str, token: str, expires_at: datetime) -> str:
        join_url = f"{settings.frontend_url.rstrip('/')}/join?token={token}"
        return (
            f'You have been invited to the project "{project_name}".\n\n'
            f"Join it here: {join_url}\n\n"
            f"The link works once and expires on {expires_at:%Y-%m-%d %H:%M} UTC."
        )

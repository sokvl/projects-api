import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import EmailStr

from app.api.deps import CurrentUserDep, MailerDep
from app.db.session import DBSessionDep
from app.models.invitation import Invitation
from app.models.project import Project
from app.repositories.invitation import InvitationRepository
from app.repositories.project import ProjectRepository
from app.schemas.invitation import InvitationOut, JoinIn
from app.schemas.project import ProjectOut
from app.services.invitation import InvitationService

router = APIRouter(tags=["invitations"])


async def get_invitation_service(session: DBSessionDep, mailer: MailerDep) -> InvitationService:
    return InvitationService(
        ProjectRepository(session), InvitationRepository(session), mailer, session
    )


InvitationServiceDep = Annotated[InvitationService, Depends(get_invitation_service)]


@router.post(
    "/project/{project_id}/share",
    status_code=status.HTTP_201_CREATED,
    response_model=InvitationOut,
)
async def share_project(
    project_id: uuid.UUID,
    email: Annotated[EmailStr, Query(alias="with")],
    owner: CurrentUserDep,
    service: InvitationServiceDep,
) -> Invitation:
    return await service.share(project_id, owner, email)


@router.post("/join", response_model=ProjectOut)
async def join_project(
    body: JoinIn, user: CurrentUserDep, service: InvitationServiceDep
) -> Project:
    return await service.join(body.token, user)

import re
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.core.errors import ForbiddenError, NotFoundError, ServiceUnavailableError
from app.mail.ses import MailError
from app.models.project import Project, ProjectMember, ProjectRole
from app.models.user import User
from app.services.invitation import InvitationService, hash_token

PROJECT_ID = uuid.uuid4()
EMAIL = "anna@example.com"


@pytest.fixture
def owner() -> User:
    return User(id=uuid.uuid4(), login="marek", password_hash="x")


@pytest.fixture
def projects(owner: User) -> AsyncMock:
    repo = AsyncMock()
    repo.get_member.return_value = ProjectMember(
        user_id=owner.id, project_id=PROJECT_ID, role=ProjectRole.OWNER
    )
    repo.get_for_member.return_value = Project(id=PROJECT_ID, name="Office renovation")
    return repo


@pytest.fixture
def invitations() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mailer() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(
    projects: AsyncMock, invitations: AsyncMock, mailer: AsyncMock, session: AsyncMock
) -> InvitationService:
    return InvitationService(projects, invitations, mailer, session)


def sent_token(mailer: AsyncMock) -> str:
    body = mailer.send.await_args.args[2]
    match = re.search(r"/join\?token=(\S+)", body)
    assert match is not None
    return match.group(1)


async def test_share_stores_only_the_token_hash_and_mails_the_link(
    service: InvitationService, invitations: AsyncMock, mailer: AsyncMock, owner: User
) -> None:
    invitation = await service.share(PROJECT_ID, owner, EMAIL)

    invitations.add.assert_awaited_once_with(invitation)
    to, subject, body = mailer.send.await_args.args
    token = sent_token(mailer)
    assert to == EMAIL
    assert "Office renovation" in subject
    assert body.count(f"{settings.frontend_url}/join?token=") == 1
    assert invitation.token_hash == hash_token(token)
    assert invitation.project_id == PROJECT_ID
    assert invitation.email == EMAIL


async def test_share_sets_expiry_from_settings(service: InvitationService, owner: User) -> None:
    before = datetime.now(UTC)

    invitation = await service.share(PROJECT_ID, owner, EMAIL)

    ttl = timedelta(hours=settings.invitation_ttl_hours)
    assert before + ttl <= invitation.expires_at <= datetime.now(UTC) + ttl


async def test_share_gives_every_invitation_a_new_token(
    service: InvitationService, mailer: AsyncMock, owner: User
) -> None:
    await service.share(PROJECT_ID, owner, EMAIL)
    first = sent_token(mailer)
    await service.share(PROJECT_ID, owner, EMAIL)

    assert sent_token(mailer) != first


async def test_share_removes_expired_invitations_before_adding(
    service: InvitationService, invitations: AsyncMock, owner: User
) -> None:
    async def add(invitation: object) -> None:
        invitations.delete_expired.assert_awaited_once()

    invitations.add.side_effect = add

    await service.share(PROJECT_ID, owner, EMAIL)

    invitations.add.assert_awaited_once()


async def test_share_sends_the_mail_only_after_the_commit(
    service: InvitationService, session: AsyncMock, mailer: AsyncMock, owner: User
) -> None:
    async def commit() -> None:
        mailer.send.assert_not_awaited()

    session.commit.side_effect = commit

    await service.share(PROJECT_ID, owner, EMAIL)

    session.commit.assert_awaited_once()
    mailer.send.assert_awaited_once()


@pytest.mark.parametrize(
    ("role", "project_found", "error"),
    [
        (None, True, NotFoundError),
        (ProjectRole.PARTICIPANT, True, ForbiddenError),
        (ProjectRole.OWNER, False, NotFoundError),
    ],
    ids=["outsider", "participant", "project_deleted_meanwhile"],
)
async def test_refused_share_stores_and_sends_nothing(
    service: InvitationService,
    projects: AsyncMock,
    invitations: AsyncMock,
    mailer: AsyncMock,
    session: AsyncMock,
    owner: User,
    role: ProjectRole | None,
    project_found: bool,
    error: type[Exception],
) -> None:
    projects.get_member.return_value = (
        None if role is None else ProjectMember(user_id=owner.id, project_id=PROJECT_ID, role=role)
    )
    if not project_found:
        projects.get_for_member.return_value = None

    with pytest.raises(error):
        await service.share(PROJECT_ID, owner, EMAIL)

    invitations.add.assert_not_awaited()
    session.commit.assert_not_awaited()
    mailer.send.assert_not_awaited()


async def test_share_returns_503_when_ses_fails_and_keeps_the_invitation(
    service: InvitationService,
    session: AsyncMock,
    mailer: AsyncMock,
    owner: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mailer.send.side_effect = MailError("SES down")

    with pytest.raises(ServiceUnavailableError):
        await service.share(PROJECT_ID, owner, EMAIL)

    session.commit.assert_awaited_once()
    assert "Could not send an invitation" in caplog.text
    assert sent_token(mailer) not in caplog.text


async def test_join_burns_the_token_hash_and_adds_the_user(
    service: InvitationService,
    projects: AsyncMock,
    invitations: AsyncMock,
    session: AsyncMock,
    owner: User,
) -> None:
    invitations.burn.return_value = PROJECT_ID

    project = await service.join("the-token", owner)

    invitations.burn.assert_awaited_once_with(hash_token("the-token"))
    projects.add_member.assert_awaited_once_with(PROJECT_ID, owner.id, ProjectRole.PARTICIPANT)
    session.commit.assert_awaited_once()
    assert project is projects.get_for_member.return_value


@pytest.mark.parametrize(
    ("burned", "project_found"),
    [(None, True), (PROJECT_ID, False)],
    ids=["unknown_expired_or_used", "project_deleted_meanwhile"],
)
async def test_refused_join_commits_nothing(
    service: InvitationService,
    projects: AsyncMock,
    invitations: AsyncMock,
    session: AsyncMock,
    owner: User,
    burned: uuid.UUID | None,
    project_found: bool,
) -> None:
    invitations.burn.return_value = burned
    if not project_found:
        projects.get_for_member.return_value = None

    with pytest.raises(NotFoundError):
        await service.join("the-token", owner)

    session.commit.assert_not_awaited()

import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.ses import MailError
from app.models import Invitation, ProjectMember, User
from app.models.project import ProjectRole
from app.repositories.invitation import InvitationRepository
from app.services.invitation import hash_token
from tests.integration.conftest import test_session_maker as session_maker
from tests.integration.test_projects_api import (
    AuthHeadersFactory,
    add_participant,
    create_project,
)

SHARE = "/project/{}/share?with={}"


async def count_invitations(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Invitation)) or 0


async def test_owner_shares_a_project_by_email(
    client: AsyncClient,
    auth_headers: dict[str, str],
    mailer: MagicMock,
    db_session: AsyncSession,
) -> None:
    project_id = await create_project(client, "Office renovation", auth_headers)

    response = await client.post(SHARE.format(project_id, "Anna@Example.com"), headers=auth_headers)

    assert response.status_code == 201
    assert response.json()["email"] == "Anna@example.com"
    invitation = await db_session.scalar(select(Invitation))
    assert invitation is not None
    assert invitation.project_id == uuid.UUID(project_id)
    to, subject, body = mailer.send.await_args.args
    assert to == "Anna@example.com"
    assert "Office renovation" in subject
    match = re.search(r"/join\?token=(\S+)", body)
    assert match is not None
    assert invitation.token_hash == hash_token(match.group(1))


async def test_share_deletes_expired_invitations(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    project_id = await create_project(client, "p1", auth_headers)
    db_session.add(
        Invitation(
            project_id=uuid.UUID(project_id),
            email="old@example.com",
            token_hash="old",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    await db_session.commit()

    await client.post(SHARE.format(project_id, "anna@example.com"), headers=auth_headers)

    emails = (await db_session.scalars(select(Invitation.email))).all()
    assert emails == ["anna@example.com"]


@pytest.mark.parametrize(
    ("caller", "status"), [("john", 403), ("eve", 404)], ids=["participant", "outsider"]
)
async def test_only_the_owner_can_share(
    client: AsyncClient,
    auth_headers: dict[str, str],
    make_auth_headers: AuthHeadersFactory,
    mailer: MagicMock,
    db_session: AsyncSession,
    caller: str,
    status: int,
) -> None:
    project_id = await create_project(client, "p1", auth_headers)
    await make_auth_headers("john")
    await add_participant(db_session, project_id, "john")
    headers = await make_auth_headers(caller)

    response = await client.post(SHARE.format(project_id, "anna@example.com"), headers=headers)

    assert response.status_code == status
    assert await count_invitations(db_session) == 0
    mailer.send.assert_not_awaited()


@pytest.mark.parametrize("email", ["not-an-email", "anna@", ""])
async def test_share_rejects_an_invalid_email(
    client: AsyncClient, auth_headers: dict[str, str], mailer: MagicMock, email: str
) -> None:
    project_id = await create_project(client, "p1", auth_headers)

    response = await client.post(SHARE.format(project_id, email), headers=auth_headers)

    assert response.status_code == 422
    mailer.send.assert_not_awaited()


async def test_share_returns_503_when_ses_fails_and_keeps_the_invitation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    mailer: MagicMock,
    db_session: AsyncSession,
) -> None:
    project_id = await create_project(client, "p1", auth_headers)
    mailer.send.side_effect = MailError("SES down")

    response = await client.post(SHARE.format(project_id, "anna@example.com"), headers=auth_headers)

    assert response.status_code == 503
    assert await count_invitations(db_session) == 1


async def send_invitation(
    client: AsyncClient, project_id: str, headers: dict[str, str], mailer: MagicMock
) -> str:
    response = await client.post(SHARE.format(project_id, "anna@example.com"), headers=headers)
    assert response.status_code == 201
    match = re.search(r"/join\?token=(\S+)", mailer.send.await_args.args[2])
    assert match is not None
    return match.group(1)


async def test_join_adds_the_user_as_participant_once(
    client: AsyncClient,
    auth_headers: dict[str, str],
    make_auth_headers: AuthHeadersFactory,
    mailer: MagicMock,
    db_session: AsyncSession,
) -> None:
    project_id = await create_project(client, "Office renovation", auth_headers)
    token = await send_invitation(client, project_id, auth_headers, mailer)
    anna = await make_auth_headers("anna")

    response = await client.post("/join", json={"token": token}, headers=anna)

    assert response.status_code == 200
    assert response.json()["id"] == project_id
    assert response.json()["name"] == "Office renovation"
    role = await db_session.scalar(
        select(ProjectMember.role)
        .join(User)
        .where(User.login == "anna", ProjectMember.project_id == uuid.UUID(project_id))
    )
    assert role == ProjectRole.PARTICIPANT
    assert await count_invitations(db_session) == 0
    again = await client.post("/join", json={"token": token}, headers=anna)
    assert again.status_code == 404


async def test_join_keeps_the_role_of_an_existing_member(
    client: AsyncClient,
    auth_headers: dict[str, str],
    mailer: MagicMock,
    db_session: AsyncSession,
) -> None:
    project_id = await create_project(client, "p1", auth_headers)
    token = await send_invitation(client, project_id, auth_headers, mailer)

    response = await client.post("/join", json={"token": token}, headers=auth_headers)

    assert response.status_code == 200
    roles = (await db_session.scalars(select(ProjectMember.role))).all()
    assert roles == [ProjectRole.OWNER]
    assert await count_invitations(db_session) == 0


async def test_join_with_an_expired_token_returns_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
    make_auth_headers: AuthHeadersFactory,
    db_session: AsyncSession,
) -> None:
    project_id = await create_project(client, "p1", auth_headers)
    db_session.add(
        Invitation(
            project_id=uuid.UUID(project_id),
            email="anna@example.com",
            token_hash=hash_token("expired"),
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    await db_session.commit()

    response = await client.post(
        "/join", json={"token": "expired"}, headers=await make_auth_headers("anna")
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("body", "status"),
    [({"token": "unknown"}, 404), ({"token": ""}, 422), ({}, 422)],
    ids=["unknown", "empty", "missing"],
)
async def test_join_with_a_bad_token(
    client: AsyncClient, auth_headers: dict[str, str], body: dict[str, str], status: int
) -> None:
    response = await client.post("/join", json=body, headers=auth_headers)

    assert response.status_code == status


async def test_join_without_jwt_returns_401(client: AsyncClient) -> None:
    response = await client.post("/join", json={"token": "anything"})

    assert response.status_code == 401


async def test_a_token_burned_in_two_concurrent_transactions_returns_the_project_once(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    project_id = uuid.UUID(await create_project(client, "p1", auth_headers))
    db_session.add(
        Invitation(
            project_id=project_id,
            email="anna@example.com",
            token_hash=hash_token("t"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db_session.commit()

    async with session_maker() as first, session_maker() as second:
        burned_first = await InvitationRepository(first).burn(hash_token("t"))
        waiting = asyncio.create_task(InvitationRepository(second).burn(hash_token("t")))
        await asyncio.sleep(0.2)
        assert not waiting.done()
        await first.commit()
        burned_second = await waiting

    assert burned_first == project_id
    assert burned_second is None

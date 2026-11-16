import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.models.project import Project, ProjectMember, ProjectRole
from app.models.user import User
from app.services.project import ProjectService
from app.storage.s3 import StorageError
from tests.unit.fakes import FakeDriverError

PROJECT_ID = uuid.uuid4()


async def assign_id(project: Project) -> Project:
    project.id = PROJECT_ID
    return project


@pytest.fixture
def projects() -> AsyncMock:
    repo = AsyncMock()
    repo.add.side_effect = assign_id
    return repo


@pytest.fixture
def users() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def owner() -> User:
    return User(id=uuid.uuid4(), login="marek", password_hash="x")


async def test_create_adds_project_with_owner_membership(
    projects: AsyncMock, users: AsyncMock, session: AsyncMock, owner: User
) -> None:
    project = await ProjectService(projects, users, AsyncMock(), session).create(
        owner, "Mój projekt", None
    )

    projects.add.assert_awaited_once_with(project)
    member = projects.add_member.await_args.args[0]
    assert member.user_id == owner.id
    assert member.project_id == PROJECT_ID
    assert member.role == ProjectRole.OWNER
    session.commit.assert_awaited_once()


async def test_create_does_not_commit_when_membership_fails(
    projects: AsyncMock, users: AsyncMock, session: AsyncMock, owner: User
) -> None:
    projects.add_member.side_effect = RuntimeError("insert failed")

    with pytest.raises(RuntimeError):
        await ProjectService(projects, users, AsyncMock(), session).create(
            owner, "Mój projekt", None
        )

    session.commit.assert_not_awaited()


async def test_get_checks_access_for_the_current_user(
    projects: AsyncMock, users: AsyncMock, session: AsyncMock, owner: User
) -> None:
    await ProjectService(projects, users, AsyncMock(), session).get(PROJECT_ID, owner)

    projects.get_for_member.assert_awaited_once_with(PROJECT_ID, owner.id)


@pytest.mark.parametrize("method", ["get", "update"])
async def test_without_access_raises_not_found_and_does_not_commit(
    projects: AsyncMock, users: AsyncMock, session: AsyncMock, owner: User, method: str
) -> None:
    projects.get_for_member.return_value = None
    service = ProjectService(projects, users, AsyncMock(), session)
    call = (
        service.get(PROJECT_ID, owner)
        if method == "get"
        else service.update(PROJECT_ID, owner, "Nowa", None)
    )

    with pytest.raises(NotFoundError):
        await call

    session.commit.assert_not_awaited()


async def test_update_replaces_all_fields_and_commits(
    projects: AsyncMock, users: AsyncMock, session: AsyncMock, owner: User
) -> None:
    project = Project(id=PROJECT_ID, name="Stara", description="opis")
    projects.get_for_member.return_value = project

    result = await ProjectService(projects, users, AsyncMock(), session).update(
        PROJECT_ID, owner, "Nowa", None
    )

    assert result is project
    assert (project.name, project.description) == ("Nowa", None)
    session.commit.assert_awaited_once()


def membership(role: ProjectRole) -> ProjectMember:
    return ProjectMember(project_id=PROJECT_ID, user_id=uuid.uuid4(), role=role)


async def test_delete_without_membership_raises_not_found(
    projects: AsyncMock, users: AsyncMock, session: AsyncMock, owner: User
) -> None:
    projects.get_member.return_value = None

    with pytest.raises(NotFoundError):
        await ProjectService(projects, users, AsyncMock(), session).delete(PROJECT_ID, owner)

    projects.delete.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_delete_as_participant_raises_forbidden(
    projects: AsyncMock, users: AsyncMock, session: AsyncMock, owner: User
) -> None:
    projects.get_member.return_value = membership(ProjectRole.PARTICIPANT)

    with pytest.raises(ForbiddenError):
        await ProjectService(projects, users, AsyncMock(), session).delete(PROJECT_ID, owner)

    projects.delete.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_delete_as_owner_deletes_and_commits(
    projects: AsyncMock, users: AsyncMock, session: AsyncMock, owner: User
) -> None:
    projects.get_member.return_value = membership(ProjectRole.OWNER)

    await ProjectService(projects, users, AsyncMock(), session).delete(PROJECT_ID, owner)

    projects.get_member.assert_awaited_once_with(PROJECT_ID, owner.id)
    projects.delete.assert_awaited_once_with(PROJECT_ID)
    session.commit.assert_awaited_once()


async def test_invite_adds_participant_and_commits(
    projects: AsyncMock, users: AsyncMock, session: AsyncMock, owner: User
) -> None:
    invitee = User(id=uuid.uuid4(), login="kasia", password_hash="x")
    projects.get_member.return_value = membership(ProjectRole.OWNER)
    users.get_by_login.return_value = invitee

    member = await ProjectService(projects, users, AsyncMock(), session).invite(
        PROJECT_ID, owner, "kasia"
    )

    projects.add_member.assert_awaited_once_with(member)
    assert (member.user_id, member.project_id, member.role) == (
        invitee.id,
        PROJECT_ID,
        ProjectRole.PARTICIPANT,
    )
    session.commit.assert_awaited_once()


async def test_invite_as_participant_raises_forbidden_before_looking_up_user(
    projects: AsyncMock, users: AsyncMock, session: AsyncMock, owner: User
) -> None:
    projects.get_member.return_value = membership(ProjectRole.PARTICIPANT)

    with pytest.raises(ForbiddenError):
        await ProjectService(projects, users, AsyncMock(), session).invite(
            PROJECT_ID, owner, "kasia"
        )

    users.get_by_login.assert_not_awaited()
    projects.add_member.assert_not_awaited()


async def test_invite_unknown_user_raises_not_found(
    projects: AsyncMock, users: AsyncMock, session: AsyncMock, owner: User
) -> None:
    projects.get_member.return_value = membership(ProjectRole.OWNER)
    users.get_by_login.return_value = None

    with pytest.raises(NotFoundError):
        await ProjectService(projects, users, AsyncMock(), session).invite(
            PROJECT_ID, owner, "kasia"
        )

    projects.add_member.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_invite_existing_member_raises_conflict(
    projects: AsyncMock, users: AsyncMock, session: AsyncMock, owner: User
) -> None:
    projects.get_member.return_value = membership(ProjectRole.OWNER)
    users.get_by_login.return_value = User(id=uuid.uuid4(), login="kasia", password_hash="x")
    projects.add_member.side_effect = IntegrityError(
        "INSERT INTO project_members", {}, FakeDriverError("23505")
    )

    with pytest.raises(ConflictError):
        await ProjectService(projects, users, AsyncMock(), session).invite(
            PROJECT_ID, owner, "kasia"
        )

    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    ("s3_effect", "logged"),
    [(None, False), (StorageError("S3 down"), True)],
    ids=["s3-ok", "s3-fails-only-logged"],
)
async def test_delete_as_owner_removes_project_files_after_commit(
    projects: AsyncMock,
    users: AsyncMock,
    session: AsyncMock,
    owner: User,
    caplog: pytest.LogCaptureFixture,
    s3_effect: Exception | None,
    logged: bool,
) -> None:
    storage = AsyncMock()
    storage.delete_prefix.side_effect = s3_effect
    projects.get_member.return_value = membership(ProjectRole.OWNER)

    async def commit() -> None:
        storage.delete_prefix.assert_not_awaited()

    session.commit.side_effect = commit

    await ProjectService(projects, users, storage, session).delete(PROJECT_ID, owner)

    storage.delete_prefix.assert_awaited_once_with(f"projects/{PROJECT_ID}/")
    assert ("Could not delete objects of project" in caplog.text) is logged


@pytest.mark.parametrize("role", [None, ProjectRole.PARTICIPANT], ids=["outsider", "participant"])
async def test_refused_delete_leaves_project_files(
    projects: AsyncMock,
    users: AsyncMock,
    session: AsyncMock,
    owner: User,
    role: ProjectRole | None,
) -> None:
    storage = AsyncMock()
    projects.get_member.return_value = membership(role) if role else None

    with pytest.raises((NotFoundError, ForbiddenError)):
        await ProjectService(projects, users, storage, session).delete(PROJECT_ID, owner)

    storage.delete_prefix.assert_not_awaited()

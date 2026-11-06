import uuid
from unittest.mock import AsyncMock

import pytest

from app.models.project import Project, ProjectRole
from app.models.user import User
from app.services.project import ProjectService

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
def session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def owner() -> User:
    return User(id=uuid.uuid4(), login="marek", password_hash="x")


async def test_create_adds_project_with_owner_membership(
    projects: AsyncMock, session: AsyncMock, owner: User
) -> None:
    project = await ProjectService(projects, session).create(owner, "Mój projekt", None)

    projects.add.assert_awaited_once_with(project)
    member = projects.add_member.await_args.args[0]
    assert member.user_id == owner.id
    assert member.project_id == PROJECT_ID
    assert member.role == ProjectRole.OWNER
    session.commit.assert_awaited_once()


async def test_create_does_not_commit_when_membership_fails(
    projects: AsyncMock, session: AsyncMock, owner: User
) -> None:
    projects.add_member.side_effect = RuntimeError("insert failed")

    with pytest.raises(RuntimeError):
        await ProjectService(projects, session).create(owner, "Mój projekt", None)

    session.commit.assert_not_awaited()

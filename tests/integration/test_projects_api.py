import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, ProjectMember, User
from app.models.project import ProjectRole

AuthHeadersFactory = Callable[[str], Awaitable[dict[str, str]]]

PROJECT_ENDPOINTS = [
    ("GET", "/project/{}/info"),
    ("PUT", "/project/{}/info"),
    ("DELETE", "/project/{}"),
    ("POST", "/project/{}/invite?user=someone"),
    ("POST", "/project/{}/share?with=anna@example.com"),
]
PROJECT_ENDPOINT_IDS = ["get_info", "put_info", "delete", "invite", "share"]


async def create_project(client: AsyncClient, name: str, headers: dict[str, str]) -> str:
    response = await client.post("/projects", json={"name": name}, headers=headers)
    assert response.status_code == 201
    project_id: str = response.json()["id"]
    return project_id


async def add_document(session: AsyncSession, project_id: str, filename: str) -> None:
    session.add(
        Document(
            project_id=uuid.UUID(project_id),
            filename=filename,
            s3_key=f"{project_id}/{filename}",
            content_type="text/plain",
            size_bytes=10,
        )
    )
    await session.commit()


async def add_participant(session: AsyncSession, project_id: str, login: str) -> None:
    user_id = await session.scalar(select(User.id).where(User.login == login))
    session.add(
        ProjectMember(
            user_id=user_id, project_id=uuid.UUID(project_id), role=ProjectRole.PARTICIPANT
        )
    )
    await session.commit()


async def test_create_project_returns_201(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/projects", json={"name": "  Mój projekt ", "description": "opis"}, headers=auth_headers
    )

    assert response.status_code == 201
    body = response.json()
    assert body.keys() == {"id", "name", "description", "created_at", "updated_at"}
    assert body["name"] == "Mój projekt"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 101},
        {"name": "ok", "description": "x" * 2001},
    ],
    ids=["missing_name", "empty_name", "blank_name", "name_too_long", "description_too_long"],
)
async def test_create_project_invalid_body_returns_422(
    client: AsyncClient, auth_headers: dict[str, str], payload: dict[str, Any]
) -> None:
    response = await client.post("/projects", json=payload, headers=auth_headers)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer abc"}], ids=["no_token", "invalid_token"]
)
async def test_create_project_without_valid_token_returns_401(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.post("/projects", json={"name": "x"}, headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_list_users_projects_new_user_gets_empty_list(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/projects", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer abc"}], ids=["no_token", "invalid_token"]
)
async def test_list_users_projects_unauthenticated_returns_401(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.get("/projects", headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_list_users_projects_order_newest_first(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await create_project(client, "p1", auth_headers)
    await create_project(client, "p2", auth_headers)

    response = await client.get("/projects", headers=auth_headers)
    body = response.json()

    assert response.status_code == 200
    assert [item["name"] for item in body] == ["p2", "p1"]


async def test_list_users_projects_access_only_own_projects(
    client: AsyncClient, make_auth_headers: AuthHeadersFactory
) -> None:
    owner_headers = await make_auth_headers("john")
    other_headers = await make_auth_headers("doe")

    await create_project(client, "p1", owner_headers)
    await create_project(client, "p2", other_headers)

    response = await client.get("/projects", headers=owner_headers)
    body = response.json()

    assert response.status_code == 200
    assert [item["name"] for item in body] == ["p1"]


async def test_list_users_projects_includes_projects_as_participant(
    client: AsyncClient,
    make_auth_headers: AuthHeadersFactory,
    db_session: AsyncSession,
) -> None:
    owner_headers = await make_auth_headers("john")
    participant_headers = await make_auth_headers("doe")
    project_id = await create_project(client, "shared", owner_headers)
    await add_participant(db_session, project_id, "doe")

    response = await client.get("/projects", headers=participant_headers)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [project_id]


async def test_list_users_projects_returns_documents_under_their_project(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    with_doc_id = await create_project(client, "with doc", auth_headers)
    empty_id = await create_project(client, "empty", auth_headers)
    await add_document(db_session, with_doc_id, "notes.txt")

    response = await client.get("/projects", headers=auth_headers)

    assert response.status_code == 200
    documents = {item["id"]: item["documents"] for item in response.json()}
    assert documents[empty_id] == []
    assert len(documents[with_doc_id]) == 1
    document = documents[with_doc_id][0]
    assert document.keys() == {"id", "filename", "content_type", "size_bytes", "created_at"}
    assert document["filename"] == "notes.txt"


async def test_list_users_projects_query_count_does_not_grow_with_projects(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    sql_statements: list[str],
) -> None:
    async def count_list_queries() -> int:
        sql_statements.clear()
        response = await client.get("/projects", headers=auth_headers)
        assert response.status_code == 200
        return len(sql_statements)

    project_id = await create_project(client, "p0", auth_headers)
    await add_document(db_session, project_id, "doc.txt")
    queries_for_one = await count_list_queries()

    for i in range(1, 5):
        project_id = await create_project(client, f"p{i}", auth_headers)
        await add_document(db_session, project_id, "doc.txt")
    queries_for_five = await count_list_queries()

    assert queries_for_five == queries_for_one


async def test_get_project_as_owner_returns_200(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await create_project(client, "p1", auth_headers)

    response = await client.get(f"/project/{project_id}/info", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body.keys() == {"id", "name", "description", "created_at", "updated_at"}
    assert body["id"] == project_id


async def test_participant_can_get_and_update_project(
    client: AsyncClient, make_auth_headers: AuthHeadersFactory, db_session: AsyncSession
) -> None:
    owner_headers = await make_auth_headers("john")
    participant_headers = await make_auth_headers("doe")
    project_id = await create_project(client, "shared", owner_headers)
    await add_participant(db_session, project_id, "doe")

    get_response = await client.get(f"/project/{project_id}/info", headers=participant_headers)
    put_response = await client.put(
        f"/project/{project_id}/info", json={"name": "renamed"}, headers=participant_headers
    )

    assert get_response.status_code == 200
    assert put_response.status_code == 200
    assert put_response.json()["name"] == "renamed"


@pytest.mark.parametrize("method", ["GET", "PUT"])
async def test_project_of_other_user_looks_like_missing_project(
    client: AsyncClient, make_auth_headers: AuthHeadersFactory, method: str
) -> None:
    owner_headers = await make_auth_headers("john")
    outsider_headers = await make_auth_headers("doe")
    project_id = await create_project(client, "secret", owner_headers)

    foreign = await client.request(
        method, f"/project/{project_id}/info", json={"name": "x"}, headers=outsider_headers
    )
    missing = await client.request(
        method, f"/project/{uuid.uuid4()}/info", json={"name": "x"}, headers=outsider_headers
    )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


async def test_update_project_replaces_fields(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/projects", json={"name": "old", "description": "opis"}, headers=auth_headers
    )
    project_id = created.json()["id"]

    response = await client.put(
        f"/project/{project_id}/info", json={"name": "  new  "}, headers=auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["description"]) == ("new", None)
    assert body["updated_at"] > created.json()["updated_at"]
    stored = await client.get(f"/project/{project_id}/info", headers=auth_headers)
    assert stored.json() == body


async def test_update_project_invalid_body_returns_422_and_changes_nothing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await create_project(client, "old", auth_headers)

    response = await client.put(
        f"/project/{project_id}/info", json={"name": ""}, headers=auth_headers
    )

    assert response.status_code == 422
    stored = await client.get(f"/project/{project_id}/info", headers=auth_headers)
    assert stored.json()["name"] == "old"


@pytest.mark.parametrize(("method", "path"), PROJECT_ENDPOINTS, ids=PROJECT_ENDPOINT_IDS)
async def test_project_endpoint_with_invalid_uuid_returns_422(
    client: AsyncClient, auth_headers: dict[str, str], method: str, path: str
) -> None:
    response = await client.request(
        method, path.format("not-a-uuid"), json={"name": "x"}, headers=auth_headers
    )

    assert response.status_code == 422


@pytest.mark.parametrize(("method", "path"), PROJECT_ENDPOINTS, ids=PROJECT_ENDPOINT_IDS)
async def test_project_endpoint_without_token_returns_401(
    client: AsyncClient, auth_headers: dict[str, str], method: str, path: str
) -> None:
    project_id = await create_project(client, "p1", auth_headers)

    response = await client.request(method, path.format(project_id), json={"name": "x"})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_delete_project_as_owner_removes_project_members_and_documents(
    client: AsyncClient,
    make_auth_headers: AuthHeadersFactory,
    db_session: AsyncSession,
) -> None:
    owner_headers = await make_auth_headers("john")
    await make_auth_headers("doe")
    project_id = await create_project(client, "p1", owner_headers)
    await add_participant(db_session, project_id, "doe")
    await add_document(db_session, project_id, "notes.txt")

    response = await client.delete(f"/project/{project_id}", headers=owner_headers)

    assert response.status_code == 204
    assert response.content == b""
    after = await client.get(f"/project/{project_id}/info", headers=owner_headers)
    assert after.status_code == 404
    members = await db_session.scalar(select(func.count()).select_from(ProjectMember))
    documents = await db_session.scalar(select(func.count()).select_from(Document))
    assert (members, documents) == (0, 0)


async def test_delete_project_as_participant_returns_403_and_keeps_project(
    client: AsyncClient, make_auth_headers: AuthHeadersFactory, db_session: AsyncSession
) -> None:
    owner_headers = await make_auth_headers("john")
    participant_headers = await make_auth_headers("doe")
    project_id = await create_project(client, "p1", owner_headers)
    await add_participant(db_session, project_id, "doe")

    response = await client.delete(f"/project/{project_id}", headers=participant_headers)

    assert response.status_code == 403
    after = await client.get(f"/project/{project_id}/info", headers=owner_headers)
    assert after.status_code == 200


async def test_delete_project_of_other_user_looks_like_missing_project(
    client: AsyncClient, make_auth_headers: AuthHeadersFactory
) -> None:
    owner_headers = await make_auth_headers("john")
    outsider_headers = await make_auth_headers("doe")
    project_id = await create_project(client, "p1", owner_headers)

    foreign = await client.delete(f"/project/{project_id}", headers=outsider_headers)
    missing = await client.delete(f"/project/{uuid.uuid4()}", headers=outsider_headers)

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


async def test_invite_returns_201_and_invitee_sees_project(
    client: AsyncClient, make_auth_headers: AuthHeadersFactory
) -> None:
    owner_headers = await make_auth_headers("john")
    invitee_headers = await make_auth_headers("doe")
    project_id = await create_project(client, "shared", owner_headers)

    response = await client.post(f"/project/{project_id}/invite?user=DOE", headers=owner_headers)

    assert response.status_code == 201
    assert response.json() == {"login": "doe", "role": "participant"}
    listed = await client.get("/projects", headers=invitee_headers)
    assert [item["id"] for item in listed.json()] == [project_id]


@pytest.mark.parametrize("login", ["doe", "john"], ids=["already_participant", "owner_self"])
async def test_invite_user_with_access_returns_409(
    client: AsyncClient, make_auth_headers: AuthHeadersFactory, login: str
) -> None:
    owner_headers = await make_auth_headers("john")
    await make_auth_headers("doe")
    project_id = await create_project(client, "p1", owner_headers)
    await client.post(f"/project/{project_id}/invite?user=doe", headers=owner_headers)

    response = await client.post(
        f"/project/{project_id}/invite?user={login}", headers=owner_headers
    )

    assert response.status_code == 409


async def test_concurrent_invites_of_same_user_give_one_201_and_one_409(
    client: AsyncClient, make_auth_headers: AuthHeadersFactory
) -> None:
    owner_headers = await make_auth_headers("john")
    await make_auth_headers("doe")
    project_id = await create_project(client, "p1", owner_headers)
    url = f"/project/{project_id}/invite?user=doe"

    responses = await asyncio.gather(
        client.post(url, headers=owner_headers), client.post(url, headers=owner_headers)
    )

    assert sorted(response.status_code for response in responses) == [201, 409]


async def test_invite_unknown_user_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    project_id = await create_project(client, "p1", auth_headers)

    response = await client.post(f"/project/{project_id}/invite?user=nobody", headers=auth_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


async def test_invite_as_participant_returns_403_and_adds_nobody(
    client: AsyncClient, make_auth_headers: AuthHeadersFactory, db_session: AsyncSession
) -> None:
    owner_headers = await make_auth_headers("john")
    participant_headers = await make_auth_headers("doe")
    target_headers = await make_auth_headers("kasia")
    project_id = await create_project(client, "p1", owner_headers)
    await add_participant(db_session, project_id, "doe")

    response = await client.post(
        f"/project/{project_id}/invite?user=kasia", headers=participant_headers
    )

    assert response.status_code == 403
    listed = await client.get("/projects", headers=target_headers)
    assert listed.json() == []


async def test_invite_to_project_of_other_user_looks_like_missing_project(
    client: AsyncClient, make_auth_headers: AuthHeadersFactory
) -> None:
    owner_headers = await make_auth_headers("john")
    outsider_headers = await make_auth_headers("doe")
    project_id = await create_project(client, "p1", owner_headers)

    foreign = await client.post(f"/project/{project_id}/invite?user=john", headers=outsider_headers)
    missing = await client.post(
        f"/project/{uuid.uuid4()}/invite?user=john", headers=outsider_headers
    )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.parametrize(
    "query", ["?user=x", "?user=ma%C5%82y", ""], ids=["too_short", "non_ascii", "missing"]
)
async def test_invite_invalid_login_returns_422(
    client: AsyncClient, auth_headers: dict[str, str], query: str
) -> None:
    project_id = await create_project(client, "p1", auth_headers)

    response = await client.post(f"/project/{project_id}/invite{query}", headers=auth_headers)

    assert response.status_code == 422

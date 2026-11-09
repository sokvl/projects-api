import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, ProjectMember, User
from app.models.project import ProjectRole

AuthHeadersFactory = Callable[[str], Awaitable[dict[str, str]]]


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


@pytest.mark.parametrize("method", ["GET", "PUT"])
async def test_project_info_with_invalid_uuid_returns_422(
    client: AsyncClient, auth_headers: dict[str, str], method: str
) -> None:
    response = await client.request(
        method, "/project/not-a-uuid/info", json={"name": "x"}, headers=auth_headers
    )

    assert response.status_code == 422


@pytest.mark.parametrize("method", ["GET", "PUT"])
async def test_project_info_without_token_returns_401(
    client: AsyncClient, auth_headers: dict[str, str], method: str
) -> None:
    project_id = await create_project(client, "p1", auth_headers)

    response = await client.request(method, f"/project/{project_id}/info", json={"name": "x"})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"

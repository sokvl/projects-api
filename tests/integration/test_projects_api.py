from typing import Any

import pytest
from httpx import AsyncClient


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

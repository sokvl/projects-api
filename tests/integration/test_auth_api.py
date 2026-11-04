import pytest
from httpx import AsyncClient

REGISTER = {"login": "marek", "password": "secret123", "repeat_password": "secret123"}
LOGIN = {"login": "marek", "password": "secret123"}


async def test_register_returns_user_without_secrets(client: AsyncClient) -> None:
    response = await client.post("/auth", json=REGISTER)

    assert response.status_code == 201
    assert response.json().keys() == {"login", "created_at"}
    assert response.json()["login"] == "marek"


async def test_register_duplicate_login_returns_409(client: AsyncClient) -> None:
    await client.post("/auth", json=REGISTER)

    response = await client.post("/auth", json={**REGISTER, "login": "MAREK"})

    assert response.status_code == 409


async def test_register_mismatch_does_not_echo_passwords(client: AsyncClient) -> None:
    response = await client.post("/auth", json={**REGISTER, "repeat_password": "different1"})

    assert response.status_code == 422
    assert "secret123" not in response.text


async def test_login_returns_bearer_token(client: AsyncClient) -> None:
    await client.post("/auth", json=REGISTER)

    response = await client.post("/login", json=LOGIN)

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


@pytest.mark.parametrize(
    "credentials",
    [{**LOGIN, "password": "wrongpass1"}, {**LOGIN, "login": "nobody"}],
    ids=["wrong_password", "unknown_login"],
)
async def test_login_invalid_credentials_returns_401(
    client: AsyncClient, credentials: dict[str, str]
) -> None:
    await client.post("/auth", json=REGISTER)

    response = await client.post("/login", json=credentials)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid login or password"}

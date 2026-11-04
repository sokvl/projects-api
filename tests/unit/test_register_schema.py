from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.auth import RegisterIn

VALID: dict[str, Any] = {"login": "marek", "password": "secret123", "repeat_password": "secret123"}


def test_valid_data_normalizes_login() -> None:
    body = RegisterIn(**{**VALID, "login": "  Marek1 "})

    assert body.login == "marek1"


@pytest.mark.parametrize(
    "override",
    [
        {"repeat_password": "different123"},
        {"password": "short", "repeat_password": "short"},
        {"password": "x" * 129, "repeat_password": "x" * 129},
        {"login": "ab"},
        {"login": "x" * 51},
        {"login": "marek@x.pl"},
        {"login": "łukasz"},
        {"repeat_password": None},
    ],
    ids=[
        "passwords_mismatch",
        "password_too_short",
        "password_too_long",
        "login_too_short",
        "login_too_long",
        "login_special_char",
        "login_non_ascii",
        "repeat_password_null",
    ],
)
def test_invalid_data_is_rejected(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RegisterIn(**{**VALID, **override})


@pytest.mark.parametrize("field", ["login", "password", "repeat_password"])
def test_missing_field_is_rejected(field: str) -> None:
    data = {key: value for key, value in VALID.items() if key != field}

    with pytest.raises(ValidationError):
        RegisterIn(**data)

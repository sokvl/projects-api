import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginIn


@pytest.mark.parametrize("password", ["", "short"], ids=["empty", "shorter_than_policy"])
def test_password_below_policy_is_accepted(password: str) -> None:
    body = LoginIn(login="marek", password=password)

    assert body.password == password


def test_password_too_long_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LoginIn(login="marek", password="x" * 129)

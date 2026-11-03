import pytest
from pydantic import TypeAdapter

from app.schemas.common import Login, normalize_login


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("marek", "marek"),
        ("Marek", "marek"),
        ("MAREK@X.PL", "marek@x.pl"),
        ("  marek  ", "marek"),
        ("\tMarek\n", "marek"),
    ],
)
def test_normalize_login(raw: str, expected: str) -> None:
    assert normalize_login(raw) == expected


def test_login_type_normalizes_on_validation() -> None:
    assert TypeAdapter(Login).validate_python("  Marek ") == "marek"

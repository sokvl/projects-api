from typing import Annotated

from pydantic import AfterValidator, Field


def normalize_login(value: str) -> str:
    return value.strip().lower()


Login = Annotated[
    str,
    AfterValidator(normalize_login),
    Field(min_length=3, max_length=50, pattern=r"^[a-z0-9]+$"),
]

Password = Annotated[str, Field(min_length=8, max_length=128)]

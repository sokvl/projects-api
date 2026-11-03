from typing import Annotated

from pydantic import AfterValidator


def normalize_login(value: str) -> str:
    return value.strip().lower()


Login = Annotated[str, AfterValidator(normalize_login)]

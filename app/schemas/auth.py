from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import Login


class RegisterIn(BaseModel):
    login: Login
    password: str = Field(min_length=8, max_length=128)
    repeat_password: str

    @model_validator(mode="after")
    def passwords_match(self) -> Self:
        if self.password != self.repeat_password:
            raise ValueError("Passwords do not match")
        return self


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    login: str
    created_at: datetime

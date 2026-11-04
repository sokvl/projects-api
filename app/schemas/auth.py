from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import Login, Password


class RegisterIn(BaseModel):
    login: Login
    password: Password
    repeat_password: str

    @model_validator(mode="after")
    def passwords_match(self) -> Self:
        if self.password != self.repeat_password:
            raise ValueError("Passwords do not match")
        return self


class LoginIn(BaseModel):
    login: Login
    password: str = Field(max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    login: str
    created_at: datetime

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JoinIn(BaseModel):
    token: str = Field(min_length=1, max_length=100)


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email: str
    expires_at: datetime

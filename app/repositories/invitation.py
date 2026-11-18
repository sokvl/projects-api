import uuid

from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invitation import Invitation


class InvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, invitation: Invitation) -> Invitation:
        self.session.add(invitation)
        await self.session.flush()
        return invitation

    async def burn(self, token_hash: str) -> uuid.UUID | None:
        query = (
            delete(Invitation)
            .where(Invitation.token_hash == token_hash, Invitation.expires_at > func.now())
            .returning(Invitation.project_id)
        )
        return await self.session.scalar(query)

    async def delete_expired(self) -> None:
        await self.session.execute(delete(Invitation).where(Invitation.expires_at <= func.now()))

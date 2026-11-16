import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.project import ProjectMember


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_all(self, documents: list[Document]) -> list[Document]:
        self.session.add_all(documents)
        await self.session.flush()
        return documents

    async def delete(self, document_id: uuid.UUID) -> None:
        await self.session.execute(delete(Document).where(Document.id == document_id))

    async def get_project_files_total_size_bytes(self, project_id: uuid.UUID) -> int:
        query = select(func.coalesce(func.sum(Document.size_bytes), 0)).where(
            Document.project_id == project_id
        )
        return int(await self.session.scalar(query) or 0)

    async def list_for_project(self, project_id: uuid.UUID) -> Sequence[Document]:
        query = (
            select(Document)
            .where(Document.project_id == project_id)
            # now() is the transaction start, so files from one upload share created_at
            .order_by(Document.created_at.desc(), Document.id)
        )
        return (await self.session.scalars(query)).all()

    async def get_for_member(self, document_id: uuid.UUID, user_id: uuid.UUID) -> Document | None:
        query = (
            select(Document)
            .join(ProjectMember, ProjectMember.project_id == Document.project_id)
            .where(Document.id == document_id, ProjectMember.user_id == user_id)
        )
        return await self.session.scalar(query)

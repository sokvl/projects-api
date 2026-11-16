import logging
import uuid
from collections.abc import Sequence

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import FileTooLargeError, NotFoundError
from app.models.document import Document
from app.models.user import User
from app.repositories.document import DocumentRepository
from app.repositories.project import ProjectRepository
from app.services.file_types import HEADER_BYTES, PDF, detect_content_type
from app.storage.s3 import S3Storage, StorageError, project_prefix

logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(
        self,
        projects_repository: ProjectRepository,
        documents_repository: DocumentRepository,
        s3_storage: S3Storage,
        session: AsyncSession,
    ) -> None:
        self.session = session
        self.documents = documents_repository
        self.projects = projects_repository
        self.s3_storage = s3_storage

    async def upload(
        self, project_id: uuid.UUID, user: User, files: list[UploadFile]
    ) -> list[Document]:
        if await self.projects.get_for_member(project_id, user.id, lock=True) is None:
            raise NotFoundError("Project or member not found")

        documents = [await self._prepare(project_id, file) for file in files]
        await self._ensure_fits(project_id, sum(document.size_bytes for document in documents))

        uploaded_keys: list[str] = []
        try:
            for file, document in zip(files, documents, strict=True):
                await self.s3_storage.upload_file(document.s3_key, file.file, document.content_type)
                uploaded_keys.append(document.s3_key)
            await self.documents.add_all(documents)
            await self.session.commit()
        except Exception:
            await self._delete_objects(uploaded_keys)
            raise

        return documents

    async def replace(self, document_id: uuid.UUID, user: User, file: UploadFile) -> Document:
        document = await self.documents.get_for_member(document_id, user.id)
        if document is None:
            raise NotFoundError("Document not found")
        if await self.projects.get_for_member(document.project_id, user.id, lock=True) is None:
            raise NotFoundError("Document not found")

        new = await self._prepare(document.project_id, file)
        await self._ensure_fits(document.project_id, new.size_bytes - document.size_bytes)

        old_key = document.s3_key
        await self.s3_storage.upload_file(new.s3_key, file.file, new.content_type)
        try:
            document.filename = new.filename
            document.content_type = new.content_type
            document.size_bytes = new.size_bytes
            document.s3_key = new.s3_key
            await self.session.commit()
        except Exception:
            await self._delete_objects([new.s3_key])
            raise

        await self._delete_objects([old_key])
        return document

    async def delete(self, document_id: uuid.UUID, user: User) -> None:
        document = await self.documents.get_for_member(document_id, user.id)
        if document is None:
            raise NotFoundError("Document not found")
        await self.documents.delete(document_id)
        await self.session.commit()
        await self._delete_objects([document.s3_key])

    async def list_for_project(self, project_id: uuid.UUID, user: User) -> Sequence[Document]:
        if await self.projects.get_for_member(project_id, user.id) is None:
            raise NotFoundError("Project or member not found")
        return await self.documents.list_for_project(project_id)

    async def get_download_url(self, document_id: uuid.UUID, user: User) -> str:
        document = await self.documents.get_for_member(document_id, user.id)
        if document is None:
            raise NotFoundError("Document not found")
        return self.s3_storage.generate_presigned_download_url(
            document.s3_key, document.filename, inline=document.content_type == PDF
        )

    async def _prepare(self, project_id: uuid.UUID, file: UploadFile) -> Document:
        content_type = detect_content_type(await file.read(HEADER_BYTES))
        await file.seek(0)
        document_id = uuid.uuid4()
        return Document(
            id=document_id,
            project_id=project_id,
            filename=(file.filename or "unnamed")[:255],
            s3_key=f"{project_prefix(project_id)}{document_id}",
            content_type=content_type,
            size_bytes=self._size(file),
        )

    @staticmethod
    def _size(file: UploadFile) -> int:
        if file.size is None:
            raise ValueError("Upload size unknown")
        return file.size

    async def _ensure_fits(self, project_id: uuid.UUID, added_bytes: int) -> None:
        used = await self.documents.get_project_files_total_size_bytes(project_id)
        if used + added_bytes > settings.project_size_limit_bytes:
            raise FileTooLargeError("Total project file size exceeds the project limit")

    async def _delete_objects(self, keys: list[str]) -> None:
        for key in keys:
            try:
                await self.s3_storage.delete_file(key)
            except StorageError:
                logger.exception("Could not delete orphaned object %s", key)

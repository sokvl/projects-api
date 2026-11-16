import logging
import uuid
from collections.abc import Sequence

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import FileTooLargeError, NotFoundError
from app.models.document import Document
from app.models.user import User
from app.repositories.document import DocumentRepository
from app.repositories.project import ProjectRepository
from app.services.file_types import PDF, detect_content_type
from app.storage.s3 import S3Storage, StorageError

logger = logging.getLogger(__name__)

PROJECT_SIZE_LIMIT = 50 * 1024 * 1024
TYPE_HEADER_BYTES = 8


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

        used = await self.documents.get_project_files_total_size_bytes(project_id)
        if used + sum(document.size_bytes for document in documents) > PROJECT_SIZE_LIMIT:
            raise FileTooLargeError("Total project file size exceeds the 50 MB limit")

        uploaded_keys: list[str] = []
        try:
            for file, document in zip(files, documents, strict=True):
                await self.s3_storage.upload_file(document.s3_key, file.file, document.content_type)
                uploaded_keys.append(document.s3_key)
            await self.documents.add_all(documents)
            await self.session.commit()
        except Exception:
            await self._delete_uploaded(uploaded_keys)
            raise

        return documents

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
        content_type = detect_content_type(await file.read(TYPE_HEADER_BYTES))
        await file.seek(0)
        document_id = uuid.uuid4()
        return Document(
            id=document_id,
            project_id=project_id,
            filename=(file.filename or "unnamed")[:255],
            s3_key=f"projects/{project_id}/{document_id}",
            content_type=content_type,
            size_bytes=self._size(file),
        )

    @staticmethod
    def _size(file: UploadFile) -> int:
        if file.size is None:
            raise ValueError("Upload size unknown")
        return file.size

    async def _delete_uploaded(self, keys: list[str]) -> None:
        for key in keys:
            try:
                await self.s3_storage.delete_file(key)
            except StorageError:
                logger.exception("Could not delete orphaned object %s", key)

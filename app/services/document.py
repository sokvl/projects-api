import logging
import uuid

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

FILE_LIMIT = 50 * 1024 * 1024  # 50 MB


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
        if await self.projects.get_for_member(project_id, user.id) is None:
            raise NotFoundError("Project or member not found")

        documents: list[Document] = []
        uploaded_keys: list[str] = []

        curr_size = await self.documents.get_project_files_total_size_bytes(project_id)
        files_size = sum(file.size or 0 for file in files)
        if files_size + curr_size > FILE_LIMIT:
            raise FileTooLargeError("Total project file size exceeds the 50 MB limit")

        try:
            for file in files:
                doc_id = uuid.uuid4()
                key = f"projects/{project_id}/{doc_id}"
                data = await file.read()
                content_type = detect_content_type(data)
                await self.s3_storage.upload_file(key=key, data=data, content_type=content_type)
                uploaded_keys.append(key)
                documents.append(
                    Document(
                        id=doc_id,
                        project_id=project_id,
                        filename=file.filename or "unnamed",
                        s3_key=key,
                        content_type=content_type,
                        size_bytes=len(data),
                    )
                )

            await self.documents.add_all(documents)
            await self.session.commit()
        except Exception:
            await self._delete_uploaded(uploaded_keys)
            raise

        return documents

    async def get_download_url(self, document_id: uuid.UUID, user: User) -> str:
        document = await self.documents.get_for_member(document_id, user.id)
        if document is None:
            raise NotFoundError("Document not found")
        return self.s3_storage.generate_presigned_download_url(
            document.s3_key, document.filename, inline=document.content_type == PDF
        )

    async def _delete_uploaded(self, keys: list[str]) -> None:
        for key in keys:
            try:
                await self.s3_storage.delete_file(key)
            except StorageError:
                logger.exception("Could not delete orphaned object %s", key)

import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile, status
from fastapi.responses import RedirectResponse

from app.api.deps import CurrentUserDep, S3StorageDep
from app.db.session import DBSessionDep
from app.models.document import Document
from app.repositories.document import DocumentRepository
from app.repositories.project import ProjectRepository
from app.schemas.document import DocumentOut
from app.services.document import DocumentService

router = APIRouter(tags=["documents"])


async def get_document_service(s3_storage: S3StorageDep, session: DBSessionDep) -> DocumentService:
    return DocumentService(
        ProjectRepository(session), DocumentRepository(session), s3_storage, session
    )


DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]


@router.post(
    "/project/{project_id}/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=list[DocumentOut],
)
async def upload_documents(
    project_id: uuid.UUID,
    files: list[UploadFile],
    user: CurrentUserDep,
    service: DocumentServiceDep,
) -> list[Document]:
    return await service.upload(project_id, user, files)


@router.get("/project/{project_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    project_id: uuid.UUID, user: CurrentUserDep, service: DocumentServiceDep
) -> Sequence[Document]:
    return await service.list_for_project(project_id, user)


@router.get("/document/{document_id}", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
async def download_document(
    document_id: uuid.UUID, user: CurrentUserDep, service: DocumentServiceDep
) -> RedirectResponse:
    url = await service.get_download_url(document_id, user)
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

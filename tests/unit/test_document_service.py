import uuid
from io import BytesIO
from typing import BinaryIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from app.core.errors import FileTooLargeError, InvalidFileTypeError, NotFoundError
from app.models.document import Document
from app.models.project import Project
from app.models.user import User
from app.services.document import PROJECT_SIZE_LIMIT, DocumentService
from app.services.file_types import DOCX, PDF
from app.storage.s3 import StorageError

PROJECT_ID = uuid.uuid4()
PDF_BYTES = b"%PDF-1.7 content"
DOCX_BYTES = b"PK\x03\x04 content"
HALF = PROJECT_SIZE_LIMIT // 2


def upload(data: bytes = PDF_BYTES, filename: str | None = "a.pdf", size: int = -1) -> UploadFile:
    return UploadFile(BytesIO(data), size=len(data) if size == -1 else size, filename=filename)


@pytest.fixture
def projects() -> AsyncMock:
    repo = AsyncMock()
    repo.get_for_member.return_value = Project(id=PROJECT_ID, name="p")
    return repo


@pytest.fixture
def documents() -> AsyncMock:
    repo = AsyncMock()
    repo.get_project_files_total_size_bytes.return_value = 0
    return repo


@pytest.fixture
def storage() -> AsyncMock:
    storage = AsyncMock()
    storage.generate_presigned_download_url = MagicMock(return_value="https://s3/signed")
    return storage


@pytest.fixture
def session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(
    projects: AsyncMock, documents: AsyncMock, storage: AsyncMock, session: AsyncMock
) -> DocumentService:
    return DocumentService(projects, documents, storage, session)


@pytest.fixture
def user() -> User:
    return User(id=uuid.uuid4(), login="marek", password_hash="x")


async def test_upload_without_access_raises_not_found_before_touching_files(
    service: DocumentService,
    projects: AsyncMock,
    documents: AsyncMock,
    storage: AsyncMock,
    user: User,
) -> None:
    projects.get_for_member.return_value = None

    with pytest.raises(NotFoundError):
        await service.upload(PROJECT_ID, user, [upload(b"not a pdf")])

    projects.get_for_member.assert_awaited_once_with(PROJECT_ID, user.id, lock=True)
    documents.get_project_files_total_size_bytes.assert_not_awaited()
    storage.upload_file.assert_not_awaited()


async def test_upload_stores_every_file_and_commits(
    service: DocumentService,
    projects: AsyncMock,
    documents: AsyncMock,
    storage: AsyncMock,
    session: AsyncMock,
    user: User,
) -> None:
    stored: dict[str, bytes] = {}

    async def read_body(key: str, data: BinaryIO, content_type: str) -> None:
        stored[key] = data.read()

    storage.upload_file.side_effect = read_body

    result = await service.upload(
        PROJECT_ID, user, [upload(PDF_BYTES, "a.pdf"), upload(DOCX_BYTES, "b.docx")]
    )

    projects.get_for_member.assert_awaited_once_with(PROJECT_ID, user.id, lock=True)
    assert [(d.filename, d.content_type, d.size_bytes) for d in result] == [
        ("a.pdf", PDF, len(PDF_BYTES)),
        ("b.docx", DOCX, len(DOCX_BYTES)),
    ]
    assert [d.s3_key for d in result] == [f"projects/{PROJECT_ID}/{d.id}" for d in result]
    # the type check reads the first bytes; S3 must still get the whole file
    assert list(stored.values()) == [PDF_BYTES, DOCX_BYTES]
    documents.add_all.assert_awaited_once_with(result)
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    ("files", "used", "error"),
    [
        ([upload(), upload(b"plain text", "notes.txt")], 0, InvalidFileTypeError),
        ([upload(b"")], 0, InvalidFileTypeError),
        ([upload(size=11)], PROJECT_SIZE_LIMIT - 10, FileTooLargeError),
        ([upload(size=PROJECT_SIZE_LIMIT + 1)], 0, FileTooLargeError),
        ([upload(size=HALF), upload(size=HALF + 1)], 0, FileTooLargeError),
        ([UploadFile(BytesIO(PDF_BYTES), filename="a.pdf")], 0, ValueError),
    ],
    ids=[
        "one-invalid-in-batch",
        "empty-file",
        "existing-plus-new-over-limit",
        "single-file-over-limit",
        "batch-sum-over-limit",
        "unknown-size",
    ],
)
async def test_rejected_upload_sends_nothing_to_s3(
    service: DocumentService,
    documents: AsyncMock,
    storage: AsyncMock,
    session: AsyncMock,
    user: User,
    files: list[UploadFile],
    used: int,
    error: type[Exception],
) -> None:
    documents.get_project_files_total_size_bytes.return_value = used

    with pytest.raises(error):
        await service.upload(PROJECT_ID, user, files)

    storage.upload_file.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    ("files", "used", "expected_filename"),
    [
        ([upload(size=10)], PROJECT_SIZE_LIMIT - 10, "a.pdf"),
        ([upload(filename="x" * 300 + ".pdf")], 0, "x" * 255),
        ([upload(filename=None)], 0, "unnamed"),
    ],
    ids=["exactly-at-limit", "filename-cut-to-255", "missing-filename"],
)
async def test_accepted_upload_edge_cases(
    service: DocumentService,
    documents: AsyncMock,
    session: AsyncMock,
    user: User,
    files: list[UploadFile],
    used: int,
    expected_filename: str,
) -> None:
    documents.get_project_files_total_size_bytes.return_value = used

    [document] = await service.upload(PROJECT_ID, user, files)

    assert document.filename == expected_filename
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    ("upload_effects", "commit_effect", "reached_s3"),
    [
        ([None, None], RuntimeError("commit failed"), 2),
        ([None, StorageError("S3 down")], None, 1),
    ],
    ids=["commit-fails", "second-upload-fails"],
)
async def test_failed_upload_deletes_only_objects_that_reached_s3(
    service: DocumentService,
    storage: AsyncMock,
    session: AsyncMock,
    user: User,
    upload_effects: list[Exception | None],
    commit_effect: Exception | None,
    reached_s3: int,
) -> None:
    storage.upload_file.side_effect = upload_effects
    session.commit.side_effect = commit_effect

    with pytest.raises((RuntimeError, StorageError)):
        await service.upload(PROJECT_ID, user, [upload(), upload()])

    sent = [c.args[0] for c in storage.upload_file.await_args_list]
    deleted = [c.args[0] for c in storage.delete_file.await_args_list]
    assert deleted == sent[:reached_s3]


async def test_failed_cleanup_is_logged_and_the_original_error_wins(
    service: DocumentService,
    storage: AsyncMock,
    session: AsyncMock,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session.commit.side_effect = RuntimeError("commit failed")
    storage.delete_file.side_effect = StorageError("S3 down")

    with pytest.raises(RuntimeError, match="commit failed"):
        await service.upload(PROJECT_ID, user, [upload()])

    assert "Could not delete orphaned object" in caplog.text


async def test_list_checks_access_without_locking_and_returns_documents(
    service: DocumentService, projects: AsyncMock, documents: AsyncMock, user: User
) -> None:
    result = await service.list_for_project(PROJECT_ID, user)

    projects.get_for_member.assert_awaited_once_with(PROJECT_ID, user.id)
    documents.list_for_project.assert_awaited_once_with(PROJECT_ID)
    assert result is documents.list_for_project.return_value


async def test_list_without_access_raises_not_found(
    service: DocumentService, projects: AsyncMock, documents: AsyncMock, user: User
) -> None:
    projects.get_for_member.return_value = None

    with pytest.raises(NotFoundError):
        await service.list_for_project(PROJECT_ID, user)

    documents.list_for_project.assert_not_awaited()


async def test_download_url_without_access_raises_not_found(
    service: DocumentService, documents: AsyncMock, storage: AsyncMock, user: User
) -> None:
    documents.get_for_member.return_value = None
    document_id = uuid.uuid4()

    with pytest.raises(NotFoundError):
        await service.get_download_url(document_id, user)

    documents.get_for_member.assert_awaited_once_with(document_id, user.id)
    storage.generate_presigned_download_url.assert_not_called()


@pytest.mark.parametrize(
    ("content_type", "inline"), [(PDF, True), (DOCX, False)], ids=["pdf", "docx"]
)
async def test_download_url_opens_pdf_inline_and_downloads_docx(
    service: DocumentService,
    documents: AsyncMock,
    storage: AsyncMock,
    user: User,
    content_type: str,
    inline: bool,
) -> None:
    documents.get_for_member.return_value = Document(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        filename="raport.pdf",
        s3_key="projects/p/d",
        content_type=content_type,
        size_bytes=1,
    )

    url = await service.get_download_url(uuid.uuid4(), user)

    assert url == "https://s3/signed"
    storage.generate_presigned_download_url.assert_called_once_with(
        "projects/p/d", "raport.pdf", inline=inline
    )

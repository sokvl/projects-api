import pytest

from app.core.errors import InvalidFileTypeError
from app.services.file_types import DOCX, PDF, detect_content_type


@pytest.mark.parametrize(
    ("header", "expected"),
    [(b"%PDF-1.7", PDF), (b"PK\x03\x04\x14\x00", DOCX)],
    ids=["pdf", "docx"],
)
def test_detects_type_from_magic_bytes(header: bytes, expected: str) -> None:
    assert detect_content_type(header) == expected


@pytest.mark.parametrize(
    "header",
    [b"", b"hello", b"%PD", b"MZ\x90\x00", b"PK\x05\x06"],
    ids=["empty", "text", "truncated-pdf", "exe", "empty-zip"],
)
def test_rejects_other_content(header: bytes) -> None:
    with pytest.raises(InvalidFileTypeError):
        detect_content_type(header)

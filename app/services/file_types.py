from app.core.errors import InvalidFileTypeError

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

SIGNATURES = {
    b"%PDF": PDF,
    b"PK\x03\x04": DOCX,
}


def detect_content_type(data: bytes) -> str:
    for signature, content_type in SIGNATURES.items():
        if data.startswith(signature):
            return content_type
    raise InvalidFileTypeError("Only PDF and DOCX files are allowed")

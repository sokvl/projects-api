from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import (
    ConflictError,
    DomainError,
    FileTooLargeError,
    ForbiddenError,
    InvalidFileTypeError,
    NotFoundError,
    UnauthorizedError,
)

STATUS_CODES: dict[type[DomainError], int] = {
    UnauthorizedError: status.HTTP_401_UNAUTHORIZED,
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ForbiddenError: status.HTTP_403_FORBIDDEN,
    ConflictError: status.HTTP_409_CONFLICT,
    FileTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    InvalidFileTypeError: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
}


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    code = next(c for cls, c in STATUS_CODES.items() if isinstance(exc, cls))
    headers = {"WWW-Authenticate": "Bearer"} if code == status.HTTP_401_UNAUTHORIZED else None
    return JSONResponse(status_code=code, content={"detail": str(exc)}, headers=headers)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": errors}
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.errors import ConflictError, DomainError, ForbiddenError, NotFoundError

STATUS_CODES: dict[type[DomainError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ForbiddenError: status.HTTP_403_FORBIDDEN,
    ConflictError: status.HTTP_409_CONFLICT,
}


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    code = next(c for cls, c in STATUS_CODES.items() if isinstance(exc, cls))
    return JSONResponse(status_code=code, content={"detail": str(exc)})


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from app.api import auth, documents, invitations, projects
from app.core.config import settings
from app.core.handlers import register_exception_handlers
from app.core.middleware import BodySizeLimitMiddleware
from app.db.session import DBSessionDep, engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    yield
    await engine.dispose()


MULTIPART_OVERHEAD_BYTES = 1024 * 1024

app = FastAPI(title="Projects API", lifespan=lifespan)
app.add_middleware(
    BodySizeLimitMiddleware,
    max_body_bytes=settings.project_size_limit_bytes + MULTIPART_OVERHEAD_BYTES,
)
register_exception_handlers(app)
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(documents.router)
app.include_router(invitations.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db")
async def health_db(
    session: DBSessionDep,
) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as err:
        raise HTTPException(status_code=503, detail="Database unavailable") from err

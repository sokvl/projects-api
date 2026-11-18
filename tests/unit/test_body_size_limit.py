from unittest.mock import AsyncMock

import pytest
from starlette.types import Message

from app.core.middleware import BodySizeLimitMiddleware

LIMIT = 100


def http_scope(headers: list[tuple[bytes, bytes]]) -> dict[str, object]:
    return {"type": "http", "method": "POST", "path": "/", "headers": headers}


async def call(scope: dict[str, object]) -> tuple[AsyncMock, list[Message]]:
    app = AsyncMock()
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await BodySizeLimitMiddleware(app, max_body_bytes=LIMIT)(scope, AsyncMock(), send)
    return app, sent


async def test_rejects_a_declared_body_over_the_limit_without_calling_the_app() -> None:
    app, sent = await call(http_scope([(b"content-length", str(LIMIT + 1).encode())]))

    app.assert_not_awaited()
    assert sent[0]["status"] == 413
    assert b"Request body too large" in sent[1]["body"]


@pytest.mark.parametrize(
    "headers",
    [
        [(b"content-length", str(LIMIT).encode())],
        [],
        [(b"content-length", b"not-a-number")],
    ],
    ids=["at_the_limit", "no_content_length", "invalid_content_length"],
)
async def test_passes_other_requests_to_the_app(headers: list[tuple[bytes, bytes]]) -> None:
    app, sent = await call(http_scope(headers))

    app.assert_awaited_once()
    assert sent == []


async def test_ignores_non_http_scopes() -> None:
    app, _ = await call({"type": "lifespan"})

    app.assert_awaited_once()

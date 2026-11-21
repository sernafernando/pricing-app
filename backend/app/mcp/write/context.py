"""Who writes (WriteContext), the errors a write order can end in, and DB access outside FastAPI dependencies."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, TypeVar

import anyio
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.mcp import loopback

ORIGEN_MCP = "mcp"
ORIGEN_APP = "app"

T = TypeVar("T")


@dataclass(frozen=True)
class WriteContext:
    """The person behind a write order. `scopes` is None for the app (logged in, no OAuth token)."""

    usuario_id: int
    username: str
    connection_id: int | None
    cliente: str
    origen: str
    scopes: tuple[str, ...] | None = None


class WriteError(Exception):
    """A write order refused as a whole. `code` is what the AI / the app sees first; `http_status` is the app's."""

    def __init__(self, code: str, message: str, http_status: int = 422, result: Any = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.http_status = http_status
        self.result = result


@contextlib.contextmanager
def db_session() -> Iterator[Session]:
    """The same session factory the endpoints get (honours dependency overrides, e.g. in tests)."""
    provider = loopback.bound_app().dependency_overrides.get(get_db, get_db)
    generator = provider()
    try:
        yield next(generator)
    finally:
        generator.close()


async def in_db(fn: Callable[..., T], *args: Any) -> T:
    """Run `fn(db, *args)` in a worker thread with its own session (never block the event loop on the DB)."""

    def run() -> T:
        with db_session() as db:
            return fn(db, *args)

    return await anyio.to_thread.run_sync(run)

"""In-process calls from an MCP tool to the app's own HTTP endpoints, as the connected user.

Every tool runs the real endpoint (route, dependencies, permission gates, brand scoping, masking) through the
ASGI app itself, authenticated with a 60-second app token minted for that user. The token never leaves the
process. This is what makes the MCP inherit the user's permissions exactly (overrides included) without
duplicating a single permission check.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

import httpx
from fastapi import FastAPI

from app.core.config import settings
from app.core.security import create_access_token

IDENTITY_TTL = timedelta(seconds=60)
# The caller address the app sees: never a localhost one, which some dependencies trust without a login
# (`get_user_or_localhost`, for scripts and crons).
LOOPBACK_CLIENT = ("mcp-loopback", 0)

_app_getter: Callable[[], FastAPI] | None = None


def bind_app(getter: Callable[[], FastAPI]) -> None:
    """Called once by app.main so this module never imports it (no import cycle)."""
    global _app_getter
    _app_getter = getter


def identity_headers(username: str) -> dict[str, str]:
    token = create_access_token({"sub": username, "via": "mcp"}, expires_delta=IDENTITY_TTL)
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


async def send_request(path: str, params: dict[str, Any], headers: dict[str, str]) -> tuple[int, bytes]:
    """GET `path` on the app in process. Read-only by construction: delivery 1 only issues GETs."""
    if _app_getter is None:
        raise RuntimeError("loopback app not bound")
    transport = httpx.ASGITransport(app=_app_getter(), client=LOOPBACK_CLIENT)
    async with httpx.AsyncClient(transport=transport, base_url=settings.MCP_PUBLIC_BASE_URL or "http://localhost") as c:
        response = await c.get(path, params=params, headers=headers)
    return response.status_code, response.content

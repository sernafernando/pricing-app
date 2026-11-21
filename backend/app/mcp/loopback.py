"""In-process calls from an MCP tool to the app's own HTTP endpoints, as the connected user.

Every tool runs the real endpoint (route, dependencies, permission gates, brand scoping, masking) through the
ASGI app itself, authenticated with a 60-second app token minted for that user. The token never leaves the
process. This is what makes the MCP inherit the user's permissions exactly (overrides included) without
duplicating a single permission check.
"""

from __future__ import annotations

import re
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


def bound_app() -> FastAPI:
    if _app_getter is None:
        raise RuntimeError("loopback app not bound")
    return _app_getter()


# The only app routes a write tool may call (delivery 2): anything else is refused before reaching the app.
WRITE_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("POST", re.compile(r"^/api/promociones/item/[^/]+$")),
    ("DELETE", re.compile(r"^/api/promociones/item/[^/]+$")),
    ("POST", re.compile(r"^/api/ml-publications/items/[^/]+/status$")),
    ("POST", re.compile(r"^/api/precios/(set-rapido|set-cuota|aplicar-markup-masivo)$")),
    ("PATCH", re.compile(r"^/api/pxq/[^/]+/tiers/\d+$")),
    ("POST", re.compile(r"^/api/pxq/[^/]+/sync$")),
)


def write_allowed(method: str, path: str) -> bool:
    return any(method == m and pattern.match(path) for m, pattern in WRITE_ROUTES)


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


async def send_write(
    method: str, path: str, params: dict[str, Any], body: Any, headers: dict[str, str]
) -> tuple[int, bytes]:
    """POST/PATCH/DELETE `path` on the app in process, only for the allowlisted write routes (`WRITE_ROUTES`)."""
    if not write_allowed(method, path):
        raise ValueError(f"write route not allowed: {method} {path}")
    transport = httpx.ASGITransport(app=bound_app(), client=LOOPBACK_CLIENT)
    async with httpx.AsyncClient(transport=transport, base_url=settings.MCP_PUBLIC_BASE_URL or "http://localhost") as c:
        response = await c.request(method, path, params=params, json=body, headers=headers)
    return response.status_code, response.content

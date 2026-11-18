"""The MCP endpoint (`/api/mcp`, streamable HTTP, stateless) mounted inside the FastAPI app.

- Auth: the official SDK's bearer middleware with our `TokenVerifier` (opaque tokens from app.mcp.store, bound
  to this resource). Missing/invalid token -> 401 with `WWW-Authenticate: Bearer resource_metadata=...`.
- Tools: app.mcp.tools, listed with schemas derived from the backing endpoints and executed as the user.
- Every call is rate limited per user and written to `mcp_tool_calls`.
- Off (404) while `MCP_PUBLIC_BASE_URL` is unset.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any
from urllib.parse import urlsplit

import anyio
from fastapi import FastAPI
from limits import parse as parse_rate_limit
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.mcp import store, tools
from app.models.mcp_oauth import McpToolCall

logger = logging.getLogger(__name__)

PERMISO_VER_COSTOS = "productos.ver_costos"
_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


class McpRuntime:
    """Owns the SDK server for one app lifespan (the SDK session manager runs once per instance)."""

    def __init__(self, app_getter: Callable[[], FastAPI]) -> None:
        self._app_getter = app_getter
        self._asgi: Any = None
        # Route-level middleware (slowapi) names the endpoint by these.
        self.__name__ = "mcp_endpoint"
        self.__module__ = __name__

    # ------------------------------------------------------------ DB access outside FastAPI dependencies

    @contextlib.contextmanager
    def db_session(self) -> Iterator[Session]:
        """The same session factory the endpoints get (honours dependency overrides, e.g. in tests)."""
        provider = self._app_getter().dependency_overrides.get(get_db, get_db)
        generator = provider()
        try:
            yield next(generator)
        finally:
            generator.close()

    # ------------------------------------------------------------ lifecycle

    @contextlib.asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        base = settings.MCP_PUBLIC_BASE_URL
        if not base:
            yield
            return
        base = base.rstrip("/")
        try:
            catalog = tools.build_catalog(self._app_getter().openapi())
        except Exception:  # noqa: BLE001 - a broken catalog must not take the app down; MCP stays off (404)
            logger.exception("MCP disabled: the tool catalog could not be built")
            yield
            return
        server = _PricingMcpServer(self, catalog, base)
        self._asgi = server.streamable_http_app(
            streamable_http_path="/api/mcp",
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[urlsplit(base).netloc],
                allowed_origins=[base, "https://chatgpt.com"],
            ),
        )
        try:
            async with server.session_manager.run():
                yield
        finally:
            self._asgi = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._asgi is None:
            await JSONResponse({"detail": "Not Found"}, status_code=404)(scope, receive, send)
            return
        await self._asgi(scope, receive, send)

    # ------------------------------------------------------------ token verification

    def verify(self, raw: str) -> store.AccessGrant | None:
        with self.db_session() as db:
            return store.resolve_access_token(db, raw)

    # ------------------------------------------------------------ tool calls

    def _rate_limited(self, usuario_id: int) -> bool:
        try:
            return not limiter.limiter.hit(parse_rate_limit(settings.MCP_RATE_LIMIT), "mcp-tools", str(usuario_id))
        except Exception:  # noqa: BLE001 - fail open like the login limiter (storage outage)
            logger.warning("MCP rate-limit storage unavailable: fail-open")
            return False

    def _can_see_costs(self, usuario_id: int) -> bool:
        with self.db_session() as db:
            usuario = store.load_user(db, usuario_id)
            return bool(usuario and store.has_permission(db, usuario, PERMISO_VER_COSTOS))

    def _log(
        self, grant: dict[str, Any], tool: str, arguments: dict[str, Any], status: str, size: int, ms: int
    ) -> None:
        with self.db_session() as db:
            db.add(
                McpToolCall(
                    usuario_id=grant["usuario_id"],
                    connection_id=grant["connection_id"],
                    tool=tool[:64],
                    args_summary=tools.summarize_arguments(arguments),
                    status=status,
                    result_bytes=size,
                    duration_ms=ms,
                    created_at=store.now(),
                )
            )
            db.commit()

    async def call(self, catalog: dict[str, tools.BuiltTool], name: str, arguments: dict[str, Any]) -> CallToolResult:
        token = get_access_token()
        claims = (token.claims or {}) if token else {}
        if not claims.get("usuario_id"):
            raise ToolError("Sesión inválida")
        grant = {"usuario_id": claims["usuario_id"], "connection_id": claims["connection_id"]}
        started = time.monotonic()
        status, text = "ok", ""
        try:
            tool = catalog.get(name)
            if tool is None:
                raise tools.ToolCallError(f"Tool desconocida: {name}")
            if await anyio.to_thread.run_sync(self._rate_limited, grant["usuario_id"]):
                raise tools.ToolCallError("Demasiadas consultas: esperá un minuto", status="limited")
            can_see_costs = tool.spec.strip_costs and await anyio.to_thread.run_sync(
                self._can_see_costs, grant["usuario_id"]
            )
            result = await tools.run_tool(tool, arguments, claims["username"], bool(can_see_costs))
            text = json.dumps(result, ensure_ascii=False, default=str)
        except tools.ToolCallError as exc:
            status, text = exc.status, str(exc)
        except Exception:  # noqa: BLE001 - never leak internals to the client; the log has the trace
            logger.exception("MCP tool %s failed", name)
            status, text = "error", "Error interno al ejecutar la consulta"
        elapsed = int((time.monotonic() - started) * 1000)
        await anyio.to_thread.run_sync(
            self._log, grant, name, arguments, status, len(text.encode("utf-8")) if status == "ok" else 0, elapsed
        )
        return CallToolResult(content=[TextContent(type="text", text=text)], is_error=status != "ok")


class _TokenVerifier:
    def __init__(self, runtime: McpRuntime) -> None:
        self._runtime = runtime

    async def verify_token(self, token: str) -> AccessToken | None:
        grant = await anyio.to_thread.run_sync(self._runtime.verify, token)
        if grant is None:
            return None
        return AccessToken(
            token=token,
            client_id=grant.client_id,
            scopes=grant.scope.split(),
            expires_at=int(grant.expires_at.timestamp()),
            resource=grant.resource,
            subject=str(grant.usuario_id),
            claims={
                "usuario_id": grant.usuario_id,
                "connection_id": grant.connection_id,
                "username": grant.username,
            },
        )


class _PricingMcpServer(MCPServer):
    """Tools come from the endpoint catalog (derived schemas), not from Python function signatures."""

    def __init__(self, runtime: McpRuntime, catalog: dict[str, tools.BuiltTool], base: str) -> None:
        super().__init__(
            name="pricing",
            instructions=(
                "Pricing app data (Publicaciones ML, Métricas ML, promos, ventas) with the permissions of the "
                "connected user. Read-only. Amounts follow the app; ask before assuming a PM when a name is ambiguous."
            ),
            token_verifier=_TokenVerifier(runtime),
            auth=AuthSettings(
                issuer_url=f"{base}/api/oauth",
                resource_server_url=f"{base}/api/mcp",
                required_scopes=[store.SCOPE_READ],
                validate_token_resource=True,
            ),
        )
        self._runtime = runtime
        self._catalog = catalog

    async def list_tools(self) -> list[Tool]:
        return [
            Tool(
                name=t.spec.name,
                title=t.spec.title,
                description=t.spec.description,
                input_schema=t.input_schema,
                annotations=_READ_ONLY,
            )
            for t in self._catalog.values()
        ]

    def _tool_input_schema(self, name: str) -> dict[str, Any] | None:
        tool = self._catalog.get(name)
        return None if tool is None else tool.input_schema

    async def call_tool(self, name: str, arguments: dict[str, Any], context: Any = None) -> CallToolResult:
        return await self._runtime.call(self._catalog, name, arguments)

"""Allowed OAuth clients of the MCP authorization server (L4).

Adding a client is configuration: one entry in `settings.MCP_OAUTH_CLIENTS` with its client_id and its redirect
URIs. The client_id is either the vendor's Client ID Metadata Document URL (CIMD: ChatGPT, Claude, Claude Code)
or a pre-registered public id the user pastes into the client's settings (Cursor, Gemini CLI). The allowlist is
authoritative: the authorization endpoint never fetches anything at request time, so there is no outbound call
to abuse, and there is no dynamic client registration (no unauthenticated writes).

Redirect URIs match exactly, except loopback ones (RFC 8252 section 7.3): an entry declared as
`http://localhost/<path>` or `http://127.0.0.1/<path>` (no port) accepts that exact host and path on ANY port,
because native clients (Claude Code, Cursor, Gemini CLI) listen on a port picked at run time.

Registration is pluggable: `ClientRegistry` is what the OAuth endpoints ask. Today the only implementation is
the static allowlist; a dynamic-registration registry (RFC 7591) could implement the same protocol and advertise
`registration_endpoint`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol
from urllib.parse import urlsplit

from app.core.config import settings


LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]")
# A loopback redirect as a client sends it: lowercase host right after the scheme (no userinfo), optional port
# 1-65535 without leading zeros, then a path with no query and no fragment.
_LOOPBACK_REDIRECT = re.compile(r"http://(localhost|127\.0\.0\.1|\[::1\])(?::([1-9][0-9]{0,4}))?(/[^?#]*)")
_PRE_REGISTERED_ID = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")


def _loopback_parts(uri: str) -> tuple[str, int | None, str] | None:
    """(host, port, path) of a well-formed loopback redirect, else None."""
    match = _LOOPBACK_REDIRECT.fullmatch(uri)
    if match is None:
        return None
    port = int(match.group(2)) if match.group(2) else None
    if port is not None and port > 65535:
        return None
    return match.group(1), port, match.group(3)


def redirect_target(redirect_uri: str) -> tuple[str, bool]:
    """What the consent card shows: the host the code goes back to, and whether it is this computer."""
    loopback = _loopback_parts(redirect_uri)
    if loopback is not None:
        return loopback[0], True
    return urlsplit(redirect_uri).hostname or redirect_uri, False


@dataclass(frozen=True)
class OAuthClient:
    client_id: str
    name: str
    redirect_uris: tuple[str, ...]
    _loopbacks: frozenset[tuple[str, str]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        loopbacks = set()
        for uri in self.redirect_uris:
            parts = _loopback_parts(uri)
            if parts is not None and parts[1] is None:
                loopbacks.add((parts[0], parts[2]))
        object.__setattr__(self, "_loopbacks", frozenset(loopbacks))

    def allows_redirect(self, redirect_uri: str) -> bool:
        """Exact string match (OAuth 2.1): no prefix, no trailing-slash or case tolerance. A declared loopback
        redirect also accepts any port on the same host and path (RFC 8252 section 7.3)."""
        if redirect_uri in self.redirect_uris:
            return True
        parts = _loopback_parts(redirect_uri)
        return parts is not None and (parts[0], parts[2]) in self._loopbacks


class ClientRegistry(Protocol):
    supports_dynamic_registration: bool

    def get(self, client_id: str) -> OAuthClient | None: ...


class StaticAllowlistRegistry:
    """The allowlist from settings. Lookups are exact."""

    supports_dynamic_registration = False

    def __init__(self, clients: list[OAuthClient]) -> None:
        self._clients = {c.client_id: c for c in clients}

    def get(self, client_id: str) -> OAuthClient | None:
        return self._clients.get(client_id)


def _https_url(value: object, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"MCP_OAUTH_CLIENTS: {what} must be a non-empty string")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.netloc or parts.fragment or "@" in parts.netloc:
        raise ValueError(f"MCP_OAUTH_CLIENTS: {what} must be an https URL without fragment: {value!r}")
    return value


def _client_id(value: object) -> str:
    """A CIMD URL (https) or a pre-registered public id (lowercase letters, digits and dashes, 2-64 chars)."""
    if isinstance(value, str) and _PRE_REGISTERED_ID.fullmatch(value):
        return value
    return _https_url(value, "client_id")


def _redirect_uri(value: object) -> str:
    """An exact https URL, or a loopback one declared without port (any port is then accepted)."""
    if isinstance(value, str) and value.startswith("http://"):
        parts = _loopback_parts(value)
        if parts is None:
            raise ValueError(
                f"MCP_OAUTH_CLIENTS: plain http is only allowed for loopback (localhost, 127.0.0.1, [::1]) "
                f"with a path and no query: {value!r}"
            )
        if parts[1] is not None:
            raise ValueError(
                f"MCP_OAUTH_CLIENTS: declare loopback redirects without port (any port matches): {value!r}"
            )
        return value
    return _https_url(value, "redirect_uri")


def parse_clients(raw: str) -> list[OAuthClient]:
    """Parse and validate the allowlist. Any mistake raises ValueError (fail loudly at startup)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"MCP_OAUTH_CLIENTS is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("MCP_OAUTH_CLIENTS must be a JSON list")
    clients: list[OAuthClient] = []
    seen: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError("MCP_OAUTH_CLIENTS entries must be objects")
        client_id = _client_id(entry.get("client_id"))
        if client_id in seen:
            raise ValueError(f"MCP_OAUTH_CLIENTS: duplicated client_id {client_id!r}")
        seen.add(client_id)
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("MCP_OAUTH_CLIENTS: name is required")
        uris = entry.get("redirect_uris")
        if not isinstance(uris, list) or not uris:
            raise ValueError("MCP_OAUTH_CLIENTS: redirect_uris must be a non-empty list")
        clients.append(
            OAuthClient(
                client_id=client_id,
                name=name.strip(),
                redirect_uris=tuple(_redirect_uri(u) for u in uris),
            )
        )
    return clients


@lru_cache(maxsize=4)
def _registry_for(raw: str) -> StaticAllowlistRegistry:
    return StaticAllowlistRegistry(parse_clients(raw))


def get_client_registry() -> ClientRegistry:
    """The registry the OAuth endpoints use (cached per configuration value)."""
    return _registry_for(settings.MCP_OAUTH_CLIENTS)

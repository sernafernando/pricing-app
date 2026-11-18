"""Allowed OAuth clients of the MCP authorization server (L4).

Adding a client (Claude, Cursor, ...) is configuration: one entry in `settings.MCP_OAUTH_CLIENTS` with its
Client ID Metadata Document URL (the client_id) and its exact redirect URIs. The allowlist is authoritative:
the authorization endpoint never fetches anything at request time, so there is no outbound call to abuse.

Registration is pluggable: `ClientRegistry` is what the OAuth endpoints ask. Today the only implementation is
the static allowlist; a dynamic-registration registry (RFC 7591) can be added for clients without CIMD by
implementing the same protocol and advertising `registration_endpoint`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol
from urllib.parse import urlsplit

from app.core.config import settings


@dataclass(frozen=True)
class OAuthClient:
    client_id: str
    name: str
    redirect_uris: tuple[str, ...]

    def allows_redirect(self, redirect_uri: str) -> bool:
        """Exact string match (OAuth 2.1): no prefix, no trailing-slash or case tolerance."""
        return redirect_uri in self.redirect_uris


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
    if parts.scheme != "https" or not parts.netloc or parts.fragment:
        raise ValueError(f"MCP_OAUTH_CLIENTS: {what} must be an https URL without fragment: {value!r}")
    return value


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
        client_id = _https_url(entry.get("client_id"), "client_id")
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
                redirect_uris=tuple(_https_url(u, "redirect_uri") for u in uris),
            )
        )
    return clients


@lru_cache(maxsize=4)
def _registry_for(raw: str) -> StaticAllowlistRegistry:
    return StaticAllowlistRegistry(parse_clients(raw))


def get_client_registry() -> ClientRegistry:
    """The registry the OAuth endpoints use (cached per configuration value)."""
    return _registry_for(settings.MCP_OAUTH_CLIENTS)

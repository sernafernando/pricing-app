"""OAuth client allowlist (S10/L4): adding a client is config, not code; registration is pluggable."""

from __future__ import annotations

import json

import pytest

from app.mcp.clients import OAuthClient, StaticAllowlistRegistry, parse_clients

CHATGPT = {
    "client_id": "https://chatgpt.com/oauth/client.json",
    "name": "ChatGPT",
    "redirect_uris": ["https://chatgpt.com/connector_platform_oauth_redirect"],
}


def test_parses_several_clients():
    other = {
        "client_id": "https://client.example/oauth.json",
        "name": "Otro",
        "redirect_uris": ["https://client.example/cb"],
    }
    clients = parse_clients(json.dumps([CHATGPT, other]))
    assert [c.name for c in clients] == ["ChatGPT", "Otro"]
    assert clients[1].redirect_uris == ("https://client.example/cb",)


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        "{}",
        json.dumps(
            [{"client_id": "http://insecure.example/c.json", "name": "x", "redirect_uris": ["https://a.example/cb"]}]
        ),
        json.dumps([{"client_id": "https://a.example/c.json", "name": "x", "redirect_uris": []}]),
        json.dumps([{"client_id": "https://a.example/c.json", "name": "x", "redirect_uris": ["http://a.example/cb"]}]),
        json.dumps(
            [{"client_id": "https://a.example/c.json", "name": "x", "redirect_uris": ["https://a.example/cb#frag"]}]
        ),
        json.dumps([CHATGPT, CHATGPT]),
    ],
)
def test_invalid_configuration_fails_loudly(bad):
    with pytest.raises(ValueError):
        parse_clients(bad)


def test_registry_lookup_is_exact():
    registry = StaticAllowlistRegistry(parse_clients(json.dumps([CHATGPT])))
    client = registry.get(CHATGPT["client_id"])
    assert isinstance(client, OAuthClient)
    assert client.allows_redirect("https://chatgpt.com/connector_platform_oauth_redirect")
    assert not client.allows_redirect("https://chatgpt.com/connector_platform_oauth_redirect/")
    assert registry.get(CHATGPT["client_id"] + "?x=1") is None
    assert registry.get("https://CHATGPT.com/oauth/client.json") is None
    assert registry.supports_dynamic_registration is False


# ---------------------------------------------------------------- loopback, pre-registered ids, custom schemes


def _one(entry: dict) -> OAuthClient:
    [client] = parse_clients(json.dumps([entry]))
    return client


LOOPBACK = {
    "client_id": "https://claude.ai/oauth/claude-code-client-metadata",
    "name": "Claude Code",
    "redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"],
}


@pytest.mark.parametrize(
    "uri",
    [
        "http://localhost/callback",
        "http://localhost:1/callback",
        "http://localhost:53682/callback",
        "http://localhost:65535/callback",
        "http://127.0.0.1:8787/callback",
    ],
)
def test_loopback_redirect_accepts_any_port(uri):
    assert _one(LOOPBACK).allows_redirect(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "https://localhost:5000/callback",  # declared scheme is http
        "http://localhost:5000/callback/",  # path is exact
        "http://localhost:5000/Callback",
        "http://localhost:5000/callback/../x",
        "http://localhost:5000/callback?x=1",
        "http://localhost:5000/callback#f",
        "http://localhost:0/callback",
        "http://localhost:65536/callback",
        "http://localhost:abc/callback",
        "http://localhost:/callback",
        "http://[::1]:5000/callback",  # host not declared
        "http://127.0.0.2:5000/callback",
        "http://localhost.evil.example:5000/callback",
        "http://evil.example@localhost:5000/callback",
        "http://localhost@evil.example:5000/callback",
        "http://LOCALHOST:5000/callback",
        "http://evil.example/callback",
    ],
)
def test_loopback_redirect_rejects_everything_else(uri):
    assert not _one(LOOPBACK).allows_redirect(uri)


def test_declared_port_on_a_loopback_redirect_is_refused():
    with pytest.raises(ValueError):
        _one({**LOOPBACK, "redirect_uris": ["http://localhost:8787/callback"]})


def test_pre_registered_public_client_id():
    client = _one(
        {
            "client_id": "pricing-mcp-cursor",
            "name": "Cursor",
            "redirect_uris": ["http://localhost/callback", "https://www.cursor.com/agents/mcp/oauth/callback"],
        }
    )
    assert client.allows_redirect("http://localhost:8787/callback")
    assert client.allows_redirect("https://www.cursor.com/agents/mcp/oauth/callback")
    assert not client.allows_redirect("https://www.cursor.com/agents/mcp/oauth/callback/")
    assert not client.allows_redirect("cursor://anysphere.cursor-mcp/oauth/callback")


@pytest.mark.parametrize(
    "client_id",
    ["", "Has Spaces", "UPPER", "a", "x" * 65, "http://a.example/c.json", "pricing_mcp", "-lead", "id/with/slash"],
)
def test_invalid_pre_registered_ids_fail(client_id):
    with pytest.raises(ValueError):
        _one({"client_id": client_id, "name": "x", "redirect_uris": ["https://a.example/cb"]})


@pytest.mark.parametrize(
    "uri",
    [
        "http://a.example/cb",  # plain http outside loopback
        "http://localhost/cb?x=1",
        "http://localhost/cb#f",
        "http://localhost",  # no path
        "http://user@localhost/cb",
        "javascript://x/%0aalert(1)",
        "data://x/y",
        "file:///etc/passwd",
        "vbscript://x/y",
        "cursor://anysphere.cursor-mcp/oauth/callback",  # private-use schemes are not accepted
    ],
)
def test_dangerous_or_malformed_redirects_fail_at_startup(uri):
    with pytest.raises(ValueError):
        _one({"client_id": "pricing-mcp-x", "name": "x", "redirect_uris": [uri]})


def test_default_allowlist_holds_every_supported_client():
    from app.core.config import settings

    clients = {c.client_id: c for c in parse_clients(settings.MCP_OAUTH_CLIENTS)}
    assert {c.name for c in clients.values()} == {"ChatGPT", "Claude", "Claude Code", "Cursor", "Gemini CLI"}
    assert clients["https://claude.ai/oauth/mcp-oauth-client-metadata"].redirect_uris == (
        "https://claude.ai/api/mcp/auth_callback",
    )
    assert clients["https://claude.ai/oauth/claude-code-client-metadata"].allows_redirect(
        "http://localhost:49152/callback"
    )
    cursor = clients["pricing-mcp-cursor"]
    assert cursor.allows_redirect("http://localhost:8787/callback")
    assert cursor.allows_redirect("https://www.cursor.com/agents/mcp/oauth/callback")
    assert not cursor.allows_redirect("cursor://anysphere.cursor-mcp/oauth/callback")
    assert clients["pricing-mcp-gemini-cli"].allows_redirect("http://localhost:41234/oauth/callback")
    assert not clients["pricing-mcp-gemini-cli"].allows_redirect("http://localhost:41234/callback")

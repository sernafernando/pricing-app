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

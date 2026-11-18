"""Claude (web/desktop), Claude Code, Cursor and Gemini CLI on the MCP OAuth server, end to end.

Each client is driven the way its vendor documents it: CIMD client_id (Claude) or a pre-registered public
client_id (Cursor, Gemini CLI, no dynamic registration), its own redirect URI (exact https callback
or loopback on a random port per RFC 8252), PKCE S256 and the resource parameter.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from app.models.mcp_oauth import McpConnection, McpOAuthRequest
from tests.mcp.conftest import BASE, RESOURCE, app_login, decide, pkce_pair, rpc

INIT = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}

# (label, client_id, redirect used in the flow, client name, redirect host shown on the consent card, local)
CLIENTS = [
    (
        "claude",
        "https://claude.ai/oauth/mcp-oauth-client-metadata",
        "https://claude.ai/api/mcp/auth_callback",
        "Claude",
        "claude.ai",
        False,
    ),
    (
        "claude-code",
        "https://claude.ai/oauth/claude-code-client-metadata",
        "http://localhost:53682/callback",
        "Claude Code",
        "localhost",
        True,
    ),
    (
        "claude-code-127",
        "https://claude.ai/oauth/claude-code-client-metadata",
        "http://127.0.0.1:41001/callback",
        "Claude Code",
        "127.0.0.1",
        True,
    ),
    ("cursor", "pricing-mcp-cursor", "http://localhost:8787/callback", "Cursor", "localhost", True),
    (
        "cursor-web",
        "pricing-mcp-cursor",
        "https://www.cursor.com/agents/mcp/oauth/callback",
        "Cursor",
        "www.cursor.com",
        False,
    ),
    ("gemini-cli", "pricing-mcp-gemini-cli", "http://localhost:39017/oauth/callback", "Gemini CLI", "localhost", True),
]
IDS = [c[0] for c in CLIENTS]


def _params(client_id: str, redirect_uri: str, challenge: str, **extra: str) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "st-9",
        "scope": "pricing.read",
        "resource": RESOURCE,
        **extra,
    }


def _authorize(client, client_id: str, redirect_uri: str, challenge: str):
    return client.get(
        "/api/oauth/authorize", params=_params(client_id, redirect_uri, challenge), follow_redirects=False
    )


def _req(response) -> str:
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(f"{BASE}/mcp/autorizar?req="), location
    return parse_qs(urlsplit(location).query)["req"][0]


def _token(client, client_id: str, redirect_uri: str, code: str, verifier: str):
    return client.post(
        "/api/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "resource": RESOURCE,
        },
    )


def _approved(client, user, client_id: str, redirect_uri: str) -> tuple[str, str]:
    verifier, challenge = pkce_pair()
    req = _req(_authorize(client, client_id, redirect_uri, challenge))
    r = decide(client, req, app_login(client, user))
    assert r.status_code == 200, r.text
    target = urlsplit(r.json()["redirect_to"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == redirect_uri
    query = {k: v[0] for k, v in parse_qs(target.query).items()}
    assert query["state"] == "st-9"
    assert query["iss"] == f"{BASE}/api/oauth"
    return query["code"], verifier


@pytest.mark.parametrize(("label", "client_id", "redirect", "name", "host", "local"), CLIENTS, ids=IDS)
def test_each_client_connects_reaches_the_tools_and_can_be_revoked(
    mcp_client, mcp_user, db, label, client_id, redirect, name, host, local
):
    code, verifier = _approved(mcp_client, mcp_user, client_id, redirect)
    r = _token(mcp_client, client_id, redirect, code, verifier)
    assert r.status_code == 200, r.text
    body = r.json()
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-06-18",
        "Authorization": f"Bearer {body['access_token']}",
    }
    assert rpc(mcp_client, headers, "initialize", INIT).status_code == 200

    stored = db.query(McpConnection).one()
    assert (stored.usuario_id, stored.client_id, stored.client_name) == (mcp_user.id, client_id, name)

    r = mcp_client.post("/api/oauth/revoke", data={"token": body["refresh_token"]})
    assert r.status_code == 200
    db.refresh(stored)
    assert stored.revoked_at is not None
    assert rpc(mcp_client, headers, "initialize", INIT).status_code == 401


@pytest.mark.parametrize(("label", "client_id", "redirect", "name", "host", "local"), CLIENTS, ids=IDS)
def test_consent_card_shows_the_client_and_where_it_returns(
    mcp_client, mcp_user, label, client_id, redirect, name, host, local
):
    _, challenge = pkce_pair()
    req = _req(_authorize(mcp_client, client_id, redirect, challenge))
    r = mcp_client.get(f"/api/oauth/requests/{req}", headers=app_login(mcp_client, mcp_user))
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["client_name"] == name
    assert card["redirect_host"] == host
    assert card["redirect_local"] is local


def test_chatgpt_consent_card_is_remote(mcp_client, mcp_user):
    _, challenge = pkce_pair()
    req = _req(
        _authorize(
            mcp_client,
            "https://chatgpt.com/oauth/client.json",
            "https://chatgpt.com/connector_platform_oauth_redirect",
            challenge,
        )
    )
    card = mcp_client.get(f"/api/oauth/requests/{req}", headers=app_login(mcp_client, mcp_user)).json()
    assert (card["redirect_host"], card["redirect_local"]) == ("chatgpt.com", False)


@pytest.mark.parametrize(
    ("client_id", "redirect"),
    [
        # another client's redirect
        ("https://claude.ai/oauth/mcp-oauth-client-metadata", "http://localhost:5000/callback"),
        ("https://claude.ai/oauth/claude-code-client-metadata", "https://claude.ai/api/mcp/auth_callback"),
        ("pricing-mcp-gemini-cli", "http://localhost:8787/callback"),
        ("pricing-mcp-cursor", "http://localhost:8787/oauth/callback"),
        # look-alike loopbacks
        ("https://claude.ai/oauth/claude-code-client-metadata", "http://localhost.evil.example:5000/callback"),
        ("https://claude.ai/oauth/claude-code-client-metadata", "http://evil.example@localhost:5000/callback"),
        ("https://claude.ai/oauth/claude-code-client-metadata", "http://[::1]:5000/callback"),
        ("https://claude.ai/oauth/claude-code-client-metadata", "https://localhost:5000/callback"),
        ("https://claude.ai/oauth/claude-code-client-metadata", "http://localhost:5000/callback?next=x"),
        ("pricing-mcp-cursor", "cursor://anysphere.cursor-mcp/oauth/callback"),
        ("pricing-mcp-cursor", "https://www.cursor.com.evil.example/agents/mcp/oauth/callback"),
        # unknown pre-registered id (no dynamic registration)
        ("pricing-mcp-windsurf", "http://localhost:5000/callback"),
    ],
)
def test_rejected_redirects_get_the_error_page_and_never_a_redirect(mcp_client, db, client_id, redirect):
    _, challenge = pkce_pair()
    r = _authorize(mcp_client, client_id, redirect, challenge)
    assert r.status_code == 400
    assert "location" not in r.headers
    assert db.query(McpOAuthRequest).count() == 0


def test_loopback_port_must_match_at_the_token_endpoint(mcp_client, mcp_user):
    client_id = "https://claude.ai/oauth/claude-code-client-metadata"
    code, verifier = _approved(mcp_client, mcp_user, client_id, "http://localhost:53682/callback")
    r = _token(mcp_client, client_id, "http://localhost:53683/callback", code, verifier)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_a_pre_registered_code_cannot_be_redeemed_by_another_client(mcp_client, mcp_user):
    redirect = "http://localhost:8787/callback"
    code, verifier = _approved(mcp_client, mcp_user, "pricing-mcp-cursor", redirect)
    r = _token(mcp_client, "https://claude.ai/oauth/claude-code-client-metadata", redirect, code, verifier)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_dynamic_client_registration_stays_off(mcp_client):
    metadata = mcp_client.get("/.well-known/oauth-authorization-server/api/oauth").json()
    assert "registration_endpoint" not in metadata
    assert metadata["token_endpoint_auth_methods_supported"] == ["none"]
    assert metadata["client_id_metadata_document_supported"] is True
    r = mcp_client.post("/api/oauth/register", json={"redirect_uris": ["http://localhost/callback"]})
    assert r.status_code in (404, 405)


def test_each_machine_gets_its_own_connection(mcp_client, mcp_user, db):
    client_id = "pricing-mcp-gemini-cli"
    for port in (39017, 40123):
        redirect = f"http://localhost:{port}/oauth/callback"
        code, verifier = _approved(mcp_client, mcp_user, client_id, redirect)
        assert _token(mcp_client, client_id, redirect, code, verifier).status_code == 200
    rows = db.query(McpConnection).filter(McpConnection.revoked_at.is_(None)).all()
    assert len(rows) == 2

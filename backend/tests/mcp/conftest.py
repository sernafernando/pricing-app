"""Shared helpers for the MCP server tests: settings, a connected user and the OAuth dance.

The flow is driven exactly as ChatGPT drives it (discovery, authorize, consent, token,
MCP calls), with the EXISTING app login in the middle (L2).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import pytest

from app.core.config import settings
from tests.conftest import TEST_PASSWORD

BASE = "http://testserver"
RESOURCE = f"{BASE}/api/mcp"
ISSUER = f"{BASE}/api/oauth"
CHATGPT_CLIENT_ID = "https://chatgpt.com/oauth/client.json"
CHATGPT_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": "2025-06-18",
}


@pytest.fixture()
def mcp_settings(monkeypatch):
    """Enable the MCP server for the test app (it is off when MCP_PUBLIC_BASE_URL is unset)."""
    monkeypatch.setattr(settings, "MCP_PUBLIC_BASE_URL", BASE)
    monkeypatch.setattr(settings, "MCP_RATE_LIMIT", "1000/minute")


@pytest.fixture()
def mcp_client(mcp_settings, client):
    """The normal test client, created after the settings so the lifespan starts the MCP runtime."""
    return client


@pytest.fixture()
def mcp_user(admin_user, rol_admin, grant_permiso):
    """An ADMIN with mcp.conectar (what the migration seeds) and nothing else."""
    grant_permiso(rol_admin, "mcp.conectar")
    return admin_user


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_params(challenge: str, **overrides: str) -> dict[str, str]:
    params = {
        "response_type": "code",
        "client_id": CHATGPT_CLIENT_ID,
        "redirect_uri": CHATGPT_REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "st-123",
        "scope": "pricing.read",
        "resource": RESOURCE,
    }
    params.update(overrides)
    return {k: v for k, v in params.items() if v is not None}


def app_login(client, user) -> dict[str, str]:
    """The EXISTING login endpoint, the one the SPA login screen calls."""
    r = client.post("/api/auth/login", json={"username": user.username, "password": TEST_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def start_authorize(client, challenge: str, **overrides: str) -> str:
    """GET /authorize; returns the opaque request id the SPA receives."""
    r = client.get("/api/oauth/authorize", params=authorize_params(challenge, **overrides), follow_redirects=False)
    assert r.status_code == 302, r.text
    location = r.headers["location"]
    assert location.startswith(f"{BASE}/mcp/autorizar?req="), location
    return parse_qs(urlparse(location).query)["req"][0]


def decide(client, req: str, app_headers: dict[str, str], approve: bool = True):
    return client.post(f"/api/oauth/requests/{req}/decision", json={"approve": approve}, headers=app_headers)


def redirect_query(redirect_to: str) -> dict[str, str]:
    parsed = urlparse(redirect_to)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == CHATGPT_REDIRECT
    return {k: v[0] for k, v in parse_qs(parsed.query).items()}


def exchange_code(client, code: str, verifier: str, **overrides: str):
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": CHATGPT_REDIRECT,
        "client_id": CHATGPT_CLIENT_ID,
        "resource": RESOURCE,
    }
    data.update(overrides)
    return client.post("/api/oauth/token", data={k: v for k, v in data.items() if v is not None})


@dataclass
class Connected:
    access: str
    refresh: str
    code: str
    verifier: str

    @property
    def headers(self) -> dict[str, str]:
        return {**MCP_HEADERS, "Authorization": f"Bearer {self.access}"}


def connect(client, user, scope: str = "pricing.read") -> Connected:
    """Full flow: authorize -> existing login -> consent -> token."""
    verifier, challenge = pkce_pair()
    req = start_authorize(client, challenge, scope=scope)
    app_headers = app_login(client, user)
    r = decide(client, req, app_headers)
    assert r.status_code == 200, r.text
    query = redirect_query(r.json()["redirect_to"])
    r = exchange_code(client, query["code"], verifier)
    assert r.status_code == 200, r.text
    body = r.json()
    return Connected(access=body["access_token"], refresh=body["refresh_token"], code=query["code"], verifier=verifier)


def rpc(client, headers: dict[str, str], method: str, params: dict | None = None, rid: int = 1):
    payload: dict = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        payload["params"] = params
    return client.post("/api/mcp", json=payload, headers=headers)


def call_tool(client, headers: dict[str, str], name: str, arguments: dict | None = None) -> dict:
    r = rpc(client, headers, "tools/call", {"name": name, "arguments": arguments or {}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def tool_text(result: dict) -> str:
    return "".join(part.get("text", "") for part in result["content"])


# ---------------------------------------------------------------- write tools (delivery 2)

WRITE_SCOPE = "pricing.read pricing.write"


@pytest.fixture()
def writer(mcp_user, rol_admin, grant_permiso):
    """An ADMIN with mcp.conectar + mcp.escribir (what the migrations seed)."""
    grant_permiso(rol_admin, "mcp.escribir")
    return mcp_user


@pytest.fixture()
def write_enabled(db, monkeypatch):
    """AI writes switched on in the DB (the default is OFF), no env kill switch, no write rate limit."""
    from app.services.ml_publications import settings_store

    monkeypatch.setattr(settings, "MCP_WRITE_KILL_SWITCH", False)
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    monkeypatch.setattr(settings, "MCP_WRITE_RATE_LIMIT", "1000/minute")
    settings_store.set_setting("mcp_write.enabled", True, "test", session=db)
    db.commit()


@pytest.fixture()
def band_ok(monkeypatch):
    """A wide C1 band double, so tests of other guards do not depend on criteria rows."""
    from app.mcp.write import criteria

    monkeypatch.setattr(criteria, "band_for", lambda db, target: (0.0, 1000.0))


@pytest.fixture()
def fake_app(db, monkeypatch):
    """In-memory stand-in for the endpoints the write layer reads and writes (tests/mcp/write_fakes.py)."""
    from tests.mcp.write_fakes import FakeApp

    return FakeApp(db=db).install(monkeypatch)


def write_call(client, headers: dict[str, str], name: str, arguments: dict) -> tuple[dict, dict | str]:
    """Call a write tool; returns (raw result, parsed JSON or the error text)."""
    import json

    result = call_tool(client, headers, name, arguments)
    text = tool_text(result)
    if result.get("isError"):
        return result, text
    return result, json.loads(text)

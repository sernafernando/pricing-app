"""MCP OAuth 2.1 authorization server + resource server, end to end (S4, S8, S10).

ChatGPT is simulated with plain HTTP calls: discovery, /authorize, the existing login,
consent, /token, MCP JSON-RPC. Every negative case asserts status, body and stored state.
"""

from __future__ import annotations

import pytest

from datetime import UTC, datetime, timedelta

from app.mcp.tools import all_specs
from app.models.mcp_oauth import McpConnection, McpOAuthRequest, McpToken
from tests.conftest import make_access_token
from tests.mcp.conftest import (
    BASE,
    CHATGPT_CLIENT_ID,
    CHATGPT_REDIRECT,
    ISSUER,
    MCP_HEADERS,
    RESOURCE,
    app_login,
    authorize_params,
    connect,
    decide,
    exchange_code,
    pkce_pair,
    redirect_query,
    rpc,
    start_authorize,
)

INIT = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}


# ---------------------------------------------------------------- discovery


def test_protected_resource_metadata_points_to_our_authorization_server(mcp_client):
    r = mcp_client.get("/.well-known/oauth-protected-resource/api/mcp")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"] == RESOURCE
    assert body["authorization_servers"] == [ISSUER]
    assert body["scopes_supported"] == ["pricing.read", "pricing.write"]
    assert body["bearer_methods_supported"] == ["header"]


def test_authorization_server_metadata_advertises_cimd_pkce_and_iss(mcp_client):
    r = mcp_client.get("/.well-known/oauth-authorization-server/api/oauth")
    assert r.status_code == 200
    body = r.json()
    assert body["issuer"] == ISSUER
    assert body["authorization_endpoint"] == f"{ISSUER}/authorize"
    assert body["token_endpoint"] == f"{ISSUER}/token"
    assert body["revocation_endpoint"] == f"{ISSUER}/revoke"
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert body["token_endpoint_auth_methods_supported"] == ["none"]
    assert body["response_types_supported"] == ["code"]
    assert body["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert body["client_id_metadata_document_supported"] is True
    assert body["authorization_response_iss_parameter_supported"] is True
    assert body["scopes_supported"] == ["pricing.read", "pricing.write"]
    assert "registration_endpoint" not in body  # DCR stays off until a client needs it (L4)


def test_everything_is_off_when_the_public_base_url_is_not_configured(client):
    assert client.get("/.well-known/oauth-protected-resource/api/mcp").status_code == 404
    assert client.get("/.well-known/oauth-authorization-server/api/oauth").status_code == 404
    _, challenge = pkce_pair()
    assert client.get("/api/oauth/authorize", params=authorize_params(challenge)).status_code == 404
    assert client.post("/api/mcp", json={}, headers=MCP_HEADERS).status_code == 404


@pytest.fixture()
def broken_catalog(mcp_settings, monkeypatch):
    from app.mcp import tools

    def boom(openapi):
        raise KeyError("no GET /api/gone in the app")

    monkeypatch.setattr(tools, "build_catalog", boom)


def test_a_broken_tool_catalog_leaves_the_app_up_and_mcp_off(broken_catalog, client):
    assert client.get("/health").status_code == 200
    assert client.post("/api/mcp", json={}, headers=MCP_HEADERS).status_code == 404


def test_mcp_without_token_answers_401_with_resource_metadata(mcp_client):
    r = rpc(mcp_client, MCP_HEADERS, "initialize", INIT)
    assert r.status_code == 401
    challenge = r.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert f'resource_metadata="{BASE}/.well-known/oauth-protected-resource/api/mcp"' in challenge


# ---------------------------------------------------------------- happy path


def test_full_flow_reuses_the_existing_login_and_reaches_the_tools(mcp_client, mcp_user, db):
    conn = connect(mcp_client, mcp_user)

    r = rpc(mcp_client, conn.headers, "initialize", INIT)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["serverInfo"]["name"] == "pricing"

    r = rpc(mcp_client, conn.headers, "tools/list", rid=2)
    tools = {t["name"]: t for t in r.json()["result"]["tools"]}
    assert set(tools) == {spec.name for spec in all_specs()}
    for tool in tools.values():
        assert tool["annotations"]["readOnlyHint"] is True
        assert tool["annotations"]["destructiveHint"] is False

    stored = db.query(McpConnection).one()
    assert stored.usuario_id == mcp_user.id
    assert stored.client_id == CHATGPT_CLIENT_ID
    assert stored.client_name == "ChatGPT"
    assert stored.revoked_at is None
    # Only hashes are stored: the raw tokens never reach the database.
    hashes = {t.token_hash for t in db.query(McpToken).all()}
    assert conn.access not in hashes and conn.refresh not in hashes
    assert all(len(h) == 64 for h in hashes)


def test_authorize_redirects_to_the_spa_consent_route(mcp_client, db):
    _, challenge = pkce_pair()
    req = start_authorize(mcp_client, challenge)
    stored = db.query(McpOAuthRequest).one()
    assert stored.request_hash != req  # only the hash is stored
    assert stored.usuario_id is None


def test_authorize_is_rate_limited(mcp_client, db):
    """The only unauthenticated endpoint that writes: past the limit it answers 429 and stores nothing more."""
    _, challenge = pkce_pair()
    for _ in range(30):
        r = mcp_client.get("/api/oauth/authorize", params=authorize_params(challenge), follow_redirects=False)
        assert r.status_code == 302
    r = mcp_client.get("/api/oauth/authorize", params=authorize_params(challenge), follow_redirects=False)
    assert r.status_code == 429
    assert db.query(McpOAuthRequest).count() == 30


def test_authorize_drops_long_expired_requests(mcp_client, db):
    _, challenge = pkce_pair()
    start_authorize(mcp_client, challenge)
    old = db.query(McpOAuthRequest).one()
    old.expires_at = datetime.now(UTC) - timedelta(days=2)
    db.commit()
    old_hash = old.request_hash
    start_authorize(mcp_client, challenge)
    db.expire_all()
    assert db.query(McpOAuthRequest).filter_by(request_hash=old_hash).count() == 0
    assert db.query(McpOAuthRequest).count() == 1


def test_consent_card_data_requires_the_app_login(mcp_client, mcp_user):
    _, challenge = pkce_pair()
    req = start_authorize(mcp_client, challenge)
    assert mcp_client.get(f"/api/oauth/requests/{req}").status_code in (401, 403)
    r = mcp_client.get(f"/api/oauth/requests/{req}", headers=app_login(mcp_client, mcp_user))
    assert r.status_code == 200
    assert r.json()["client_name"] == "ChatGPT"
    assert r.json()["scope"] == "pricing.read"


def test_code_redirect_carries_state_and_iss(mcp_client, mcp_user):
    _, challenge = pkce_pair()
    req = start_authorize(mcp_client, challenge)
    r = decide(mcp_client, req, app_login(mcp_client, mcp_user))
    query = redirect_query(r.json()["redirect_to"])
    assert query["state"] == "st-123"
    assert query["iss"] == ISSUER
    assert query["code"]


def test_token_response_shape(mcp_client, mcp_user):
    verifier, challenge = pkce_pair()
    req = start_authorize(mcp_client, challenge)
    code = redirect_query(decide(mcp_client, req, app_login(mcp_client, mcp_user)).json()["redirect_to"])["code"]
    r = exchange_code(mcp_client, code, verifier)
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    assert body["scope"] == "pricing.read"
    assert r.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------- authorize errors


def test_unknown_client_gets_an_error_page_and_never_a_redirect(mcp_client, db):
    _, challenge = pkce_pair()
    r = mcp_client.get(
        "/api/oauth/authorize",
        params=authorize_params(challenge, client_id="https://evil.example/client.json"),
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "location" not in r.headers
    assert db.query(McpOAuthRequest).count() == 0


def test_redirect_uri_outside_the_allowlist_gets_an_error_page(mcp_client, db):
    _, challenge = pkce_pair()
    r = mcp_client.get(
        "/api/oauth/authorize",
        params=authorize_params(challenge, redirect_uri="https://evil.example/cb"),
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "location" not in r.headers
    assert db.query(McpOAuthRequest).count() == 0


def _error_redirect(mcp_client, **overrides):
    _, challenge = pkce_pair()
    r = mcp_client.get("/api/oauth/authorize", params=authorize_params(challenge, **overrides), follow_redirects=False)
    assert r.status_code == 302
    return redirect_query(r.headers["location"])


def test_plain_pkce_is_refused_with_iss_in_the_error(mcp_client, db):
    query = _error_redirect(mcp_client, code_challenge_method="plain")
    assert query["error"] == "invalid_request"
    assert query["iss"] == ISSUER
    assert query["state"] == "st-123"
    assert db.query(McpOAuthRequest).count() == 0


def test_wrong_resource_is_refused(mcp_client):
    query = _error_redirect(mcp_client, resource="https://other.example/mcp")
    assert query["error"] == "invalid_target"
    assert query["iss"] == ISSUER


def test_unknown_scope_is_refused(mcp_client):
    query = _error_redirect(mcp_client, scope="pricing.read pricing.admin")
    assert query["error"] == "invalid_scope"


def test_missing_scope_defaults_to_read(mcp_client, mcp_user):
    verifier, challenge = pkce_pair()
    req = start_authorize(mcp_client, challenge, scope=None)
    code = redirect_query(decide(mcp_client, req, app_login(mcp_client, mcp_user)).json()["redirect_to"])["code"]
    assert exchange_code(mcp_client, code, verifier).json()["scope"] == "pricing.read"


# ---------------------------------------------------------------- consent


def test_user_without_mcp_conectar_cannot_approve(mcp_client, active_user, db):
    _, challenge = pkce_pair()
    req = start_authorize(mcp_client, challenge)
    r = decide(mcp_client, req, app_login(mcp_client, active_user))
    assert r.status_code == 403
    assert db.query(McpOAuthRequest).one().code_hash is None


def test_deny_returns_access_denied_with_state_and_iss(mcp_client, active_user):
    _, challenge = pkce_pair()
    req = start_authorize(mcp_client, challenge)
    r = decide(mcp_client, req, app_login(mcp_client, active_user), approve=False)
    assert r.status_code == 200
    query = redirect_query(r.json()["redirect_to"])
    assert query == {"error": "access_denied", "state": "st-123", "iss": ISSUER}


def test_a_request_is_decided_once(mcp_client, mcp_user):
    _, challenge = pkce_pair()
    req = start_authorize(mcp_client, challenge)
    headers = app_login(mcp_client, mcp_user)
    assert decide(mcp_client, req, headers).status_code == 200
    assert decide(mcp_client, req, headers).status_code == 404
    assert mcp_client.get(f"/api/oauth/requests/{req}", headers=headers).status_code == 404


def test_an_expired_request_cannot_be_decided(mcp_client, mcp_user, db):
    _, challenge = pkce_pair()
    req = start_authorize(mcp_client, challenge)
    row = db.query(McpOAuthRequest).one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert decide(mcp_client, req, app_login(mcp_client, mcp_user)).status_code == 404


def test_unknown_request_is_404(mcp_client, mcp_user):
    assert decide(mcp_client, "nope", app_login(mcp_client, mcp_user)).status_code == 404


# ---------------------------------------------------------------- token errors


def _approved_code(mcp_client, user, **overrides):
    verifier, challenge = pkce_pair()
    req = start_authorize(mcp_client, challenge, **overrides)
    code = redirect_query(decide(mcp_client, req, app_login(mcp_client, user)).json()["redirect_to"])["code"]
    return code, verifier


def test_wrong_verifier_is_invalid_grant(mcp_client, mcp_user, db):
    code, _ = _approved_code(mcp_client, mcp_user)
    r = exchange_code(mcp_client, code, "x" * 50)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"
    assert db.query(McpToken).count() == 0


def test_code_is_single_use_and_reuse_revokes_what_it_issued(mcp_client, mcp_user, db):
    code, verifier = _approved_code(mcp_client, mcp_user)
    first = exchange_code(mcp_client, code, verifier)
    assert first.status_code == 200
    again = exchange_code(mcp_client, code, verifier)
    assert again.status_code == 400
    assert again.json()["error"] == "invalid_grant"
    assert db.query(McpConnection).one().revoked_at is not None
    r = rpc(mcp_client, {**MCP_HEADERS, "Authorization": f"Bearer {first.json()['access_token']}"}, "initialize", INIT)
    assert r.status_code == 401


def test_expired_code_is_invalid_grant(mcp_client, mcp_user, db):
    code, verifier = _approved_code(mcp_client, mcp_user)
    row = db.query(McpOAuthRequest).one()
    row.code_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert exchange_code(mcp_client, code, verifier).json()["error"] == "invalid_grant"


def test_redirect_uri_must_match_at_the_token_endpoint(mcp_client, mcp_user):
    code, verifier = _approved_code(mcp_client, mcp_user)
    r = exchange_code(mcp_client, code, verifier, redirect_uri="https://chatgpt.com/other")
    assert r.json()["error"] == "invalid_grant"


def test_client_id_must_match_at_the_token_endpoint(mcp_client, mcp_user):
    code, verifier = _approved_code(mcp_client, mcp_user)
    r = exchange_code(mcp_client, code, verifier, client_id="https://evil.example/client.json")
    assert r.status_code in (400, 401)
    assert r.json()["error"] in ("invalid_client", "invalid_grant")


def test_resource_must_match_at_the_token_endpoint(mcp_client, mcp_user):
    code, verifier = _approved_code(mcp_client, mcp_user)
    r = exchange_code(mcp_client, code, verifier, resource="https://other.example/mcp")
    assert r.json()["error"] == "invalid_target"


def test_unsupported_grant_type(mcp_client):
    r = mcp_client.post("/api/oauth/token", data={"grant_type": "client_credentials"})
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_grant_type"


# ---------------------------------------------------------------- refresh


def _refresh(mcp_client, refresh_token: str):
    return mcp_client.post(
        "/api/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CHATGPT_CLIENT_ID,
            "resource": RESOURCE,
        },
    )


def test_refresh_rotates_and_old_access_keeps_working_until_expiry(mcp_client, mcp_user):
    conn = connect(mcp_client, mcp_user)
    r = _refresh(mcp_client, conn.refresh)
    assert r.status_code == 200
    body = r.json()
    assert body["refresh_token"] != conn.refresh
    new_headers = {**MCP_HEADERS, "Authorization": f"Bearer {body['access_token']}"}
    assert rpc(mcp_client, new_headers, "initialize", INIT).status_code == 200


def test_refresh_reuse_revokes_the_whole_connection(mcp_client, mcp_user, db):
    conn = connect(mcp_client, mcp_user)
    rotated = _refresh(mcp_client, conn.refresh).json()
    reused = _refresh(mcp_client, conn.refresh)
    assert reused.status_code == 400
    assert reused.json()["error"] == "invalid_grant"
    assert db.query(McpConnection).one().revoked_at is not None
    assert _refresh(mcp_client, rotated["refresh_token"]).json()["error"] == "invalid_grant"
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {rotated['access_token']}"}
    assert rpc(mcp_client, headers, "initialize", INIT).status_code == 401


def test_access_token_is_not_a_refresh_token(mcp_client, mcp_user):
    conn = connect(mcp_client, mcp_user)
    assert _refresh(mcp_client, conn.access).json()["error"] == "invalid_grant"


def test_expired_access_token_is_401(mcp_client, mcp_user, db):
    conn = connect(mcp_client, mcp_user)
    for token in db.query(McpToken).filter(McpToken.kind == "access").all():
        token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert rpc(mcp_client, conn.headers, "initialize", INIT).status_code == 401


# ---------------------------------------------------------------- the user behind the token


def test_inactive_user_loses_access(mcp_client, mcp_user, db):
    conn = connect(mcp_client, mcp_user)
    mcp_user.activo = False
    db.commit()
    assert rpc(mcp_client, conn.headers, "initialize", INIT).status_code == 401


def test_removing_mcp_conectar_cuts_access_on_the_next_call(mcp_client, mcp_user, rol_admin, db):
    from app.models.permiso import Permiso, RolPermisoBase

    conn = connect(mcp_client, mcp_user)
    permiso = db.query(Permiso).filter(Permiso.codigo == "mcp.conectar").one()
    db.query(RolPermisoBase).filter(
        RolPermisoBase.rol_id == rol_admin.id, RolPermisoBase.permiso_id == permiso.id
    ).delete()
    db.commit()
    assert rpc(mcp_client, conn.headers, "initialize", INIT).status_code == 401


def test_app_jwt_is_rejected_by_mcp(mcp_client, mcp_user):
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {make_access_token(mcp_user)}"}
    assert rpc(mcp_client, headers, "initialize", INIT).status_code == 401


def test_mcp_token_is_rejected_by_the_app_api(mcp_client, mcp_user):
    conn = connect(mcp_client, mcp_user)
    assert mcp_client.get("/api/auth/me", headers={"Authorization": f"Bearer {conn.access}"}).status_code == 401


# ---------------------------------------------------------------- revocation


def test_revocation_endpoint_cuts_access(mcp_client, mcp_user, db):
    conn = connect(mcp_client, mcp_user)
    r = mcp_client.post("/api/oauth/revoke", data={"token": conn.refresh, "client_id": CHATGPT_CLIENT_ID})
    assert r.status_code == 200
    assert db.query(McpConnection).one().revoked_at is not None
    assert rpc(mcp_client, conn.headers, "initialize", INIT).status_code == 401


def test_revoking_an_unknown_token_is_200(mcp_client):
    assert mcp_client.post("/api/oauth/revoke", data={"token": "nope"}).status_code == 200


def test_user_lists_and_revokes_own_connections(mcp_client, mcp_user):
    conn = connect(mcp_client, mcp_user)
    headers = app_login(mcp_client, mcp_user)
    listed = mcp_client.get("/api/mcp/connections", headers=headers)
    assert listed.status_code == 200
    [row] = listed.json()
    assert row["client_name"] == "ChatGPT"
    assert row["usuario_id"] == mcp_user.id
    assert row["last_used_at"] is None
    assert mcp_client.delete(f"/api/mcp/connections/{row['id']}", headers=headers).status_code == 204
    assert mcp_client.get("/api/mcp/connections", headers=headers).json() == []
    assert rpc(mcp_client, conn.headers, "initialize", INIT).status_code == 401


def test_user_cannot_revoke_someone_elses_connection(mcp_client, mcp_user, active_user):
    connect(mcp_client, mcp_user)
    own = mcp_client.get("/api/mcp/connections", headers=app_login(mcp_client, mcp_user)).json()[0]
    r = mcp_client.delete(f"/api/mcp/connections/{own['id']}", headers=app_login(mcp_client, active_user))
    assert r.status_code == 404


def test_admin_lists_and_revokes_a_users_connections(mcp_client, mcp_user, active_user, db):
    conn = connect(mcp_client, mcp_user)
    admin_headers = app_login(mcp_client, mcp_user)
    r = mcp_client.get("/api/admin/mcp/connections", params={"usuario_id": mcp_user.id}, headers=admin_headers)
    assert r.status_code == 200
    [row] = r.json()
    assert row["client_id"] == CHATGPT_CLIENT_ID
    assert mcp_client.delete(f"/api/admin/mcp/connections/{row['id']}", headers=admin_headers).status_code == 204
    assert mcp_client.delete(f"/api/admin/mcp/connections/{row['id']}", headers=admin_headers).status_code == 404
    stored = db.query(McpConnection).one()
    assert stored.revoked_by_id == mcp_user.id
    assert rpc(mcp_client, conn.headers, "initialize", INIT).status_code == 401


def test_non_admin_cannot_use_the_admin_connections_endpoints(mcp_client, mcp_user, active_user):
    connect(mcp_client, mcp_user)
    headers = app_login(mcp_client, active_user)
    r = mcp_client.get("/api/admin/mcp/connections", params={"usuario_id": mcp_user.id}, headers=headers)
    assert r.status_code == 403


def test_redirect_constants_match_the_allowlist_default():
    from app.core.config import settings
    from app.mcp.clients import parse_clients

    [chatgpt] = [c for c in parse_clients(settings.MCP_OAUTH_CLIENTS) if c.client_id == CHATGPT_CLIENT_ID]
    assert chatgpt.client_id == CHATGPT_CLIENT_ID
    assert chatgpt.redirect_uris == (CHATGPT_REDIRECT,)
    assert chatgpt.name == "ChatGPT"


# ---------------------------------------------------------------- concurrent redemption (verifier follow-up)


def _redeemed_meanwhile(db, monkeypatch, target: str, mark) -> None:
    """Make another request win the race: right before this one claims the grant, mark it redeemed elsewhere."""
    from app.mcp import oauth

    real = getattr(oauth, target) if hasattr(oauth, target) else None

    def racing(*args, **kwargs):
        mark()
        db.commit()
        return real(*args, **kwargs) if real else True

    monkeypatch.setattr(oauth, target, racing)


def test_a_code_redeemed_concurrently_issues_tokens_only_once(mcp_client, mcp_user, db, monkeypatch):
    from app.models.mcp_oauth import McpOAuthRequest

    verifier, challenge = pkce_pair()
    req = start_authorize(mcp_client, challenge)
    query = redirect_query(decide(mcp_client, req, app_login(mcp_client, mcp_user)).json()["redirect_to"])
    _redeemed_meanwhile(
        db,
        monkeypatch,
        "_pkce_matches",
        lambda: db.query(McpOAuthRequest).update({McpOAuthRequest.used_at: datetime.now(UTC)}),
    )
    r = exchange_code(mcp_client, query["code"], verifier)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"
    assert db.query(McpConnection).count() == 0


def test_a_refresh_token_used_concurrently_rotates_only_once(mcp_client, mcp_user, db, monkeypatch):
    from app.mcp import store as mcp_store

    conn = connect(mcp_client, mcp_user)
    real_may_connect = mcp_store.may_connect

    def racing(session, usuario):
        db.query(McpToken).filter(McpToken.kind == "refresh").update({McpToken.rotated_at: datetime.now(UTC)})
        db.commit()
        return real_may_connect(session, usuario)

    monkeypatch.setattr(mcp_store, "may_connect", racing)
    r = mcp_client.post(
        "/api/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": conn.refresh, "client_id": CHATGPT_CLIENT_ID},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"
    assert db.query(McpToken).filter(McpToken.kind == "refresh").count() == 1

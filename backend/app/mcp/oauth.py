"""OAuth 2.1 authorization server for the MCP server, wrapping the EXISTING login (L2).

Flow (ChatGPT):
1. `GET /api/mcp` without token -> 401 pointing to the protected resource metadata.
2. Discovery: `/.well-known/oauth-protected-resource/api/mcp` and `/.well-known/oauth-authorization-server/api/oauth`
   (both at the origin root; the proxy routes them to the backend, see docs/RUNBOOKS.md).
3. `GET /api/oauth/authorize` validates the client against the allowlist and sends the browser to the SPA route
   `/mcp/autorizar?req=...`. That route sits behind the normal login, so the user signs in with the usual
   screen and credentials; the SPA then shows the consent card.
4. The SPA calls `POST /api/oauth/requests/{req}/decision` with the user's normal app token: a one-time code
   bound to that user, client, redirect, PKCE challenge and resource.
5. `POST /api/oauth/token` swaps the code (PKCE S256) for opaque MCP tokens; refresh tokens rotate.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.mcp import store
from app.mcp.clients import OAuthClient, get_client_registry
from app.models.mcp_oauth import McpConnection, McpOAuthRequest, McpToken
from app.models.usuario import Usuario

router = APIRouter()

_PKCE_CHARS = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


# ---------------------------------------------------------------- URLs


def public_base() -> str:
    """The configured public origin, or 404 for every MCP/OAuth endpoint when it is not configured."""
    base = settings.MCP_PUBLIC_BASE_URL
    if not base:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return base.rstrip("/")


def issuer_url() -> str:
    return f"{public_base()}/api/oauth"


def resource_url() -> str:
    return f"{public_base()}/api/mcp"


def _with_query(url: str, params: dict[str, str]) -> str:
    parts = urlsplit(url)
    query = "&".join(q for q in (parts.query, urlencode(params)) if q)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _authorization_response(redirect_uri: str, state: Optional[str], **params: str) -> str:
    """Every authorization response carries `iss` (RFC 9207), errors included, and echoes `state`."""
    if state is not None:
        params["state"] = state
    params["iss"] = issuer_url()
    return _with_query(redirect_uri, params)


# ---------------------------------------------------------------- discovery


@router.get("/.well-known/oauth-protected-resource/api/mcp", include_in_schema=False)
def protected_resource_metadata() -> JSONResponse:
    """RFC 9728 metadata of the MCP resource."""
    return JSONResponse(
        {
            "resource": resource_url(),
            "authorization_servers": [issuer_url()],
            "scopes_supported": list(store.SUPPORTED_SCOPES),
            "bearer_methods_supported": ["header"],
        }
    )


@router.get("/.well-known/oauth-authorization-server/api/oauth", include_in_schema=False)
def authorization_server_metadata() -> JSONResponse:
    """RFC 8414 metadata. Clients are identified by their CIMD URL (allowlisted); no dynamic registration yet."""
    issuer = issuer_url()
    metadata = {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "revocation_endpoint": f"{issuer}/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": list(store.SUPPORTED_SCOPES),
        "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True,
    }
    return JSONResponse(metadata)


# ---------------------------------------------------------------- authorize


def _error_page(message: str) -> PlainTextResponse:
    """Errors about the client or its redirect never redirect (the redirect itself is untrusted)."""
    return PlainTextResponse(f"No se puede conectar: {message}", status_code=status.HTTP_400_BAD_REQUEST)


@router.get("/api/oauth/authorize", include_in_schema=False)
@limiter.limit("30/minute")
def authorize(
    request: Request,
    response_type: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    redirect_uri: Optional[str] = Query(None),
    code_challenge: Optional[str] = Query(None),
    code_challenge_method: Optional[str] = Query(None),
    state: Optional[str] = Query(None, max_length=512),
    scope: Optional[str] = Query(None),
    resource: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> Response:
    """Validate the request and hand the browser to the SPA consent route (behind the existing login)."""
    base = public_base()
    client: Optional[OAuthClient] = get_client_registry().get(client_id or "")
    if client is None:
        return _error_page("cliente no autorizado")
    if not redirect_uri or not client.allows_redirect(redirect_uri):
        return _error_page("redirect_uri no permitido para este cliente")

    def fail(error: str, description: str) -> RedirectResponse:
        url = _authorization_response(redirect_uri, state, error=error, error_description=description)
        return RedirectResponse(url, status_code=status.HTTP_302_FOUND)

    if response_type != "code":
        return fail("unsupported_response_type", "only response_type=code")
    if code_challenge_method != "S256" or not code_challenge or not _PKCE_CHARS.match(code_challenge):
        return fail("invalid_request", "PKCE with S256 is required")
    if resource is not None and resource != resource_url():
        return fail("invalid_target", "unknown resource")
    requested = (scope or store.SCOPE_READ).split()
    if not requested or any(s not in store.SUPPORTED_SCOPES for s in requested):
        return fail("invalid_scope", "unsupported scope")

    store.prune_requests(db)
    raw = store.new_secret()
    db.add(
        McpOAuthRequest(
            request_hash=store.hash_secret(raw),
            client_id=client.client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            scope=" ".join(dict.fromkeys(requested)),
            resource=resource_url(),
            created_at=store.now(),
            expires_at=store.now() + store.REQUEST_TTL,
        )
    )
    db.commit()
    return RedirectResponse(_with_query(f"{base}/mcp/autorizar", {"req": raw}), status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------- consent (SPA, normal app token)


class PendingRequestResponse(BaseModel):
    client_name: str
    scope: str
    expires_at: datetime


class DecisionRequest(BaseModel):
    approve: bool


class DecisionResponse(BaseModel):
    redirect_to: str


def _pending(db: Session, req: str) -> McpOAuthRequest:
    """An undecided, unexpired request, or 404."""
    public_base()
    row = db.query(McpOAuthRequest).filter(McpOAuthRequest.request_hash == store.hash_secret(req)).first()
    if row is None or row.decided_at is not None or store.aware(row.expires_at) <= store.now():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El pedido de conexión venció o ya se usó")
    return row


def _client_name(client_id: str) -> str:
    client = get_client_registry().get(client_id)
    return client.name if client else client_id


@router.get("/api/oauth/requests/{req}", response_model=PendingRequestResponse)
def get_pending_request(
    req: str, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> PendingRequestResponse:
    """What the consent card shows: who asks and for what."""
    row = _pending(db, req)
    return PendingRequestResponse(
        client_name=_client_name(row.client_id), scope=row.scope, expires_at=store.aware(row.expires_at)
    )


@router.post("/api/oauth/requests/{req}/decision", response_model=DecisionResponse)
@limiter.limit("20/minute")
def decide_request(
    request: Request,
    req: str,
    body: DecisionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> DecisionResponse:
    """The logged-in user approves (needs mcp.conectar) or denies. Approving issues a one-time code bound to
    this user; the redirect target is built only from the stored, validated request."""
    row = _pending(db, req)
    if not body.approve:
        row.decided_at = store.now()
        db.commit()
        return DecisionResponse(redirect_to=_authorization_response(row.redirect_uri, row.state, error="access_denied"))
    usuario = store.load_user(db, current_user.id)
    if not store.may_connect(db, usuario):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Falta el permiso mcp.conectar")
    code = store.new_secret()
    row.decided_at = store.now()
    row.usuario_id = usuario.id
    row.code_hash = store.hash_secret(code)
    row.code_expires_at = store.now() + store.CODE_TTL
    db.commit()
    return DecisionResponse(redirect_to=_authorization_response(row.redirect_uri, row.state, code=code))


# ---------------------------------------------------------------- token


def _token_error(error: str, description: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=status_code, headers=_NO_STORE)


def _token_success(tokens: store.IssuedTokens) -> JSONResponse:
    return JSONResponse(
        {
            "access_token": tokens.access_token,
            "token_type": "Bearer",
            "expires_in": tokens.expires_in,
            "refresh_token": tokens.refresh_token,
            "scope": tokens.scope,
        },
        headers=_NO_STORE,
    )


def _pkce_matches(verifier: str, challenge: str) -> bool:
    if not _PKCE_CHARS.match(verifier):
        return False
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    return hmac.compare_digest(digest, challenge)


def _exchange_code(
    db: Session,
    code: Optional[str],
    verifier: Optional[str],
    redirect_uri: Optional[str],
    client_id: str,
    resource: Optional[str],
) -> JSONResponse:
    if not code or not verifier:
        return _token_error("invalid_request", "code and code_verifier are required")
    row = db.query(McpOAuthRequest).filter(McpOAuthRequest.code_hash == store.hash_secret(code)).first()
    if row is None:
        return _token_error("invalid_grant", "unknown code")
    if row.used_at is not None:
        # A replayed code: revoke whatever it produced (RFC 6749 §4.1.2).
        if row.connection_id is not None:
            connection = db.get(McpConnection, row.connection_id)
            if connection is not None:
                store.revoke_connection(db, connection)
                db.commit()
        return _token_error("invalid_grant", "code already used")
    if store.aware(row.code_expires_at) <= store.now():
        return _token_error("invalid_grant", "code expired")
    if row.client_id != client_id or row.redirect_uri != redirect_uri:
        return _token_error("invalid_grant", "code was issued to another client or redirect_uri")
    if resource is not None and resource != row.resource:
        return _token_error("invalid_target", "unknown resource")
    if not _pkce_matches(verifier, row.code_challenge):
        return _token_error("invalid_grant", "PKCE verification failed")
    usuario = store.load_user(db, row.usuario_id)
    if not store.may_connect(db, usuario):
        return _token_error("invalid_grant", "user may not connect")

    # Claim the code atomically: of two concurrent redemptions only one updates the row (the other sees 0 rows).
    claimed = (
        db.query(McpOAuthRequest)
        .filter(McpOAuthRequest.id == row.id, McpOAuthRequest.used_at.is_(None))
        .update({McpOAuthRequest.used_at: store.now()}, synchronize_session=False)
    )
    if claimed != 1:
        db.rollback()
        return _token_error("invalid_grant", "code already used")

    connection = McpConnection(
        usuario_id=usuario.id,
        client_id=row.client_id,
        client_name=_client_name(row.client_id),
        scope=row.scope,
        resource=row.resource,
        created_at=store.now(),
    )
    db.add(connection)
    db.flush()
    db.query(McpOAuthRequest).filter(McpOAuthRequest.id == row.id).update(
        {McpOAuthRequest.connection_id: connection.id}, synchronize_session=False
    )
    tokens = store.issue_tokens(db, connection)
    store.prune(db)
    db.commit()
    return _token_success(tokens)


def _refresh(db: Session, refresh_token: Optional[str], client_id: str, resource: Optional[str]) -> JSONResponse:
    if not refresh_token:
        return _token_error("invalid_request", "refresh_token is required")
    token = db.query(McpToken).filter(McpToken.token_hash == store.hash_secret(refresh_token)).first()
    if token is None or token.kind != "refresh":
        return _token_error("invalid_grant", "unknown refresh token")
    connection = db.get(McpConnection, token.connection_id)
    if connection is None or connection.revoked_at is not None:
        return _token_error("invalid_grant", "connection revoked")
    if token.rotated_at is not None or token.revoked_at is not None:
        # A rotated refresh token came back: it leaked. Kill the whole connection.
        store.revoke_connection(db, connection)
        db.commit()
        return _token_error("invalid_grant", "refresh token reuse")
    if store.aware(token.expires_at) <= store.now():
        return _token_error("invalid_grant", "refresh token expired")
    if connection.client_id != client_id:
        return _token_error("invalid_grant", "refresh token was issued to another client")
    if resource is not None and resource != connection.resource:
        return _token_error("invalid_target", "unknown resource")
    if not store.may_connect(db, store.load_user(db, connection.usuario_id)):
        return _token_error("invalid_grant", "user may not connect")
    # Rotate atomically: of two concurrent uses of one refresh token only one rotates it.
    rotated = (
        db.query(McpToken)
        .filter(McpToken.id == token.id, McpToken.rotated_at.is_(None), McpToken.revoked_at.is_(None))
        .update({McpToken.rotated_at: store.now()}, synchronize_session=False)
    )
    if rotated != 1:
        db.rollback()
        return _token_error("invalid_grant", "refresh token reuse")
    tokens = store.issue_tokens(db, connection)
    store.prune(db)
    db.commit()
    return _token_success(tokens)


@router.post("/api/oauth/token", include_in_schema=False)
@limiter.limit("30/minute")
def token(
    request: Request,
    grant_type: Optional[str] = Form(None),
    code: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
    resource: Optional[str] = Form(None),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Token endpoint for public clients (no secret: PKCE and exact client/redirect binding)."""
    public_base()
    if grant_type not in ("authorization_code", "refresh_token"):
        return _token_error("unsupported_grant_type", "only authorization_code and refresh_token")
    if get_client_registry().get(client_id or "") is None:
        return _token_error("invalid_client", "unknown client", status.HTTP_401_UNAUTHORIZED)
    if grant_type == "authorization_code":
        return _exchange_code(db, code, code_verifier, redirect_uri, client_id, resource)
    return _refresh(db, refresh_token, client_id, resource)


@router.post("/api/oauth/revoke", include_in_schema=False)
@limiter.limit("30/minute")
def revoke(request: Request, token: Optional[str] = Form(None), db: Session = Depends(get_db)) -> Response:
    """RFC 7009. Revoking any token of a connection revokes the whole connection. Unknown tokens: 200."""
    public_base()
    if token:
        row = db.query(McpToken).filter(McpToken.token_hash == store.hash_secret(token)).first()
        if row is not None:
            connection = db.get(McpConnection, row.connection_id)
            if connection is not None:
                store.revoke_connection(db, connection)
                db.commit()
    return Response(status_code=status.HTTP_200_OK, headers=_NO_STORE)


# ---------------------------------------------------------------- connections (list / revoke)


class ConnectionResponse(BaseModel):
    id: int
    usuario_id: int
    client_id: str
    client_name: str
    scope: str
    created_at: datetime
    last_used_at: Optional[datetime]


def _active_connections(db: Session, usuario_id: int) -> list[ConnectionResponse]:
    rows = (
        db.query(McpConnection)
        .filter(McpConnection.usuario_id == usuario_id, McpConnection.revoked_at.is_(None))
        .order_by(McpConnection.created_at.desc())
        .all()
    )
    return [
        ConnectionResponse(
            id=r.id,
            usuario_id=r.usuario_id,
            client_id=r.client_id,
            client_name=r.client_name,
            scope=r.scope,
            created_at=store.aware(r.created_at),
            last_used_at=store.aware(r.last_used_at),
        )
        for r in rows
    ]


def _revoke_one(db: Session, connection_id: int, by: Usuario, owner_id: Optional[int]) -> Response:
    query = db.query(McpConnection).filter(McpConnection.id == connection_id, McpConnection.revoked_at.is_(None))
    if owner_id is not None:
        query = query.filter(McpConnection.usuario_id == owner_id)
    connection = query.first()
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conexión inexistente o ya revocada")
    store.revoke_connection(db, connection, by_id=by.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/mcp/connections", response_model=list[ConnectionResponse])
def list_own_connections(
    db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> list[ConnectionResponse]:
    """The caller's active AI connections."""
    return _active_connections(db, current_user.id)


@router.delete("/api/mcp/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_own_connection(
    connection_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> Response:
    """Revoke one of the caller's own connections (someone else's answers 404)."""
    return _revoke_one(db, connection_id, current_user, owner_id=current_user.id)


@router.get("/api/admin/mcp/connections", response_model=list[ConnectionResponse])
def list_user_connections(
    usuario_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_admin),
) -> list[ConnectionResponse]:
    """Admin: a user's active AI connections (same gate as the user admin screen)."""
    return _active_connections(db, usuario_id)


@router.delete("/api/admin/mcp/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user_connection(
    connection_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_admin)
) -> Response:
    """Admin: revoke any user's connection."""
    return _revoke_one(db, connection_id, current_user, owner_id=None)

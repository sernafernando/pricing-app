"""Storage rules of the MCP OAuth server: hashing, token issue/rotation, revocation, lookup, pruning.

Raw secrets (request ids, codes, tokens) leave this module once, in the HTTP response; the database only ever
sees their SHA-256 hex digest.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.mcp_oauth import McpConnection, McpOAuthRequest, McpToken, McpToolCall
from app.models.usuario import Usuario
from app.services.permisos_service import OPT_IN_PERMISSION_CODES, PermisosService

PERMISO_CONECTAR = "mcp.conectar"
PERMISO_ESCRIBIR = "mcp.escribir"
SCOPE_READ = "pricing.read"
SCOPE_WRITE = "pricing.write"
SUPPORTED_SCOPES = (SCOPE_READ, SCOPE_WRITE)
REQUEST_TTL = timedelta(minutes=10)
CODE_TTL = timedelta(seconds=60)


def now() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; every stored datetime is UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_user(db: Session, usuario_id: int) -> Usuario | None:
    return db.query(Usuario).options(joinedload(Usuario.rol_obj)).filter(Usuario.id == usuario_id).first()


def has_permission(db: Session, usuario: Usuario, codigo: str) -> bool:
    """Fresh from the database (role + extra roles + overrides, SUPERADMIN implicit), never from the
    per-request cache `get_current_user` leaves on the instance: a token outlives requests."""
    if usuario.es_superadmin and codigo not in OPT_IN_PERMISSION_CODES:
        return True
    return codigo in PermisosService(db).obtener_permisos_usuario(usuario)


def may_connect(db: Session, usuario: Usuario | None) -> bool:
    """Active and holding mcp.conectar: checked on every use of a token."""
    return bool(usuario and usuario.activo and has_permission(db, usuario, PERMISO_CONECTAR))


def may_write(db: Session, usuario: Usuario | None) -> bool:
    """Active and holding mcp.escribir (fresh): checked at consent and before every write."""
    return bool(usuario and usuario.activo and has_permission(db, usuario, PERMISO_ESCRIBIR))


def normalize_scope(requested: list[str]) -> str:
    """Requested scopes in a stable order; write implies read (the MCP endpoint itself requires read)."""
    wanted = set(requested)
    if SCOPE_WRITE in wanted:
        wanted.add(SCOPE_READ)
    return " ".join(s for s in SUPPORTED_SCOPES if s in wanted)


def granted_scope(db: Session, usuario: Usuario | None, requested: str) -> str:
    """What the token gets: `pricing.write` only when asked AND the user holds mcp.escribir, else read only."""
    scopes = requested.split()
    if SCOPE_WRITE in scopes and not may_write(db, usuario):
        scopes = [s for s in scopes if s != SCOPE_WRITE]
    return normalize_scope(scopes or [SCOPE_READ])


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    scope: str


def issue_tokens(db: Session, connection: McpConnection) -> IssuedTokens:
    access, refresh = new_secret(), new_secret()
    moment = now()
    access_ttl = timedelta(minutes=settings.MCP_ACCESS_TOKEN_MINUTES)
    db.add_all(
        [
            McpToken(
                connection_id=connection.id,
                kind="access",
                token_hash=hash_secret(access),
                created_at=moment,
                expires_at=moment + access_ttl,
            ),
            McpToken(
                connection_id=connection.id,
                kind="refresh",
                token_hash=hash_secret(refresh),
                created_at=moment,
                expires_at=moment + timedelta(days=settings.MCP_REFRESH_TOKEN_DAYS),
            ),
        ]
    )
    return IssuedTokens(
        access_token=access,
        refresh_token=refresh,
        expires_in=int(access_ttl.total_seconds()),
        scope=connection.scope,
    )


def revoke_connection(db: Session, connection: McpConnection, by_id: int | None = None) -> None:
    """Revoke a connection and every token it holds (idempotent)."""
    moment = now()
    if connection.revoked_at is None:
        connection.revoked_at = moment
        connection.revoked_by_id = by_id
    db.query(McpToken).filter(McpToken.connection_id == connection.id, McpToken.revoked_at.is_(None)).update(
        {McpToken.revoked_at: moment}, synchronize_session=False
    )


@dataclass(frozen=True)
class AccessGrant:
    connection_id: int
    usuario_id: int
    username: str
    client_id: str
    scope: str
    resource: str
    expires_at: datetime


def resolve_access_token(db: Session, raw: str) -> AccessGrant | None:
    """The grant behind an MCP access token, or None when anything about it is no longer valid:
    unknown, not an access token, expired, revoked, connection revoked, user inactive, or the user
    lost mcp.conectar. Marks the connection as used."""
    token = db.query(McpToken).filter(McpToken.token_hash == hash_secret(raw)).first()
    if token is None or token.kind != "access" or token.revoked_at is not None:
        return None
    if aware(token.expires_at) <= now():
        return None
    connection = db.get(McpConnection, token.connection_id)
    if connection is None or connection.revoked_at is not None:
        return None
    usuario = load_user(db, connection.usuario_id)
    if not may_connect(db, usuario):
        return None
    connection.last_used_at = now()
    db.commit()
    return AccessGrant(
        connection_id=connection.id,
        usuario_id=usuario.id,
        username=usuario.username,
        client_id=connection.client_id,
        scope=connection.scope,
        resource=connection.resource,
        expires_at=aware(token.expires_at),
    )


def prune_requests(db: Session) -> None:
    """Drop authorization requests expired over a day ago (also run on /authorize, the unauthenticated writer)."""
    db.query(McpOAuthRequest).filter(McpOAuthRequest.expires_at < now() - timedelta(days=1)).delete(
        synchronize_session=False
    )


def prune(db: Session) -> None:
    """Opportunistic cleanup on the token endpoint (no cron, S6): old tool-call logs (L3 Q5), long-expired
    authorization requests and tokens."""
    moment = now()
    db.query(McpToolCall).filter(
        McpToolCall.created_at < moment - timedelta(days=settings.MCP_TOOL_LOG_RETENTION_DAYS)
    ).delete(synchronize_session=False)
    prune_requests(db)
    db.query(McpToken).filter(McpToken.expires_at < moment - timedelta(days=1)).delete(synchronize_session=False)

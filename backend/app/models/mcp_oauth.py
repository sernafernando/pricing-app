"""MCP server storage: OAuth connections, pending authorizations, opaque tokens and the tool-call log.

Raw tokens, codes and request ids are never stored: only their SHA-256 hex digest.
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class McpConnection(Base):
    """One approved client (e.g. ChatGPT) acting as one user. Revoking it kills all of its tokens."""

    __tablename__ = "mcp_connections"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String(512), nullable=False)
    client_name = Column(String(100), nullable=False)
    scope = Column(String(255), nullable=False)
    resource = Column(String(512), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)


class McpOAuthRequest(Base):
    """An /authorize request waiting for the user's decision, then the one-time code it produced."""

    __tablename__ = "mcp_oauth_requests"

    id = Column(Integer, primary_key=True)
    request_hash = Column(String(64), nullable=False, unique=True)
    client_id = Column(String(512), nullable=False)
    redirect_uri = Column(String(512), nullable=False)
    state = Column(String(512), nullable=True)
    code_challenge = Column(String(128), nullable=False)
    scope = Column(String(255), nullable=False)
    resource = Column(String(512), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=True)
    code_hash = Column(String(64), nullable=True, unique=True)
    code_expires_at = Column(DateTime(timezone=True), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    connection_id = Column(Integer, ForeignKey("mcp_connections.id", ondelete="CASCADE"), nullable=True)


class McpToken(Base):
    """An opaque access or refresh token of a connection. Refresh tokens rotate on every use."""

    __tablename__ = "mcp_tokens"

    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, ForeignKey("mcp_connections.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(10), nullable=False)  # access | refresh
    token_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    rotated_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class McpToolCall(Base):
    """One MCP tool call: who, which tool, a truncated summary of the arguments, outcome and size."""

    __tablename__ = "mcp_tool_calls"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = Column(Integer, ForeignKey("mcp_connections.id", ondelete="SET NULL"), nullable=True)
    tool = Column(String(64), nullable=False)
    args_summary = Column(JSON, nullable=False, default=dict)
    status = Column(String(10), nullable=False)  # ok | error | denied | limited
    result_bytes = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (Index("ix_mcp_tool_calls_created_at", "created_at"),)

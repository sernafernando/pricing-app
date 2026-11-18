"""MCP write actions (delivery 2): plans waiting for confirmation and the audit of every applied row.

A plan is what a write tool (or the app's undo) proposes: its rows with the live values seen, the limits and reason
of the order, and a single-use confirmation token stored as its SHA-256 digest. Applying it writes one
`McpWriteAction` per target with the before/after snapshot; undo rows point back with `undo_of_id`.
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class McpWritePlan(Base):
    """A planned write order: rows, limits and reason, confirmable once within its TTL by the same user/connection."""

    __tablename__ = "mcp_write_plans"

    id = Column(Integer, primary_key=True)
    plan_id = Column(String(40), nullable=False, unique=True)
    confirm_token_hash = Column(String(64), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    connection_id = Column(Integer, ForeignKey("mcp_connections.id", ondelete="SET NULL"), nullable=True)
    origen = Column(String(10), nullable=False)  # mcp | app
    cliente = Column(String(100), nullable=False)
    tool = Column(String(64), nullable=False)
    motivo = Column(String(500), nullable=False)
    limites = Column(JSON, nullable=True)
    filas = Column(JSON, nullable=False)
    plan_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    resultado = Column(JSON, nullable=True)

    __table_args__ = (Index("ix_mcp_write_plans_usuario_id", "usuario_id"),)


class McpWriteAction(Base):
    """One target of an applied plan: what it was, what it became, why, and how it ended."""

    __tablename__ = "mcp_write_actions"

    id = Column(Integer, primary_key=True)
    plan_id = Column(String(40), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    connection_id = Column(Integer, ForeignKey("mcp_connections.id", ondelete="SET NULL"), nullable=True)
    cliente = Column(String(100), nullable=False)
    tool = Column(String(64), nullable=False)
    accion = Column(String(32), nullable=False)
    objetivo = Column(String(64), nullable=False)
    objetivo_label = Column(String(255), nullable=True)
    antes = Column(JSON, nullable=True)
    despues = Column(JSON, nullable=True)
    motivo = Column(String(500), nullable=False)
    resultado = Column(String(12), nullable=False)  # ok | rechazada | bloqueada | ambigua | error | denegada
    detalle = Column(String(500), nullable=True)
    criteria_version = Column(String(64), nullable=True)
    undo_of_id = Column(Integer, ForeignKey("mcp_write_actions.id", ondelete="SET NULL"), nullable=True)
    deshecha_por_id = Column(Integer, ForeignKey("mcp_write_actions.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("plan_id", "objetivo", "accion", name="uq_mcp_write_actions_plan_objetivo_accion"),
        Index("ix_mcp_write_actions_usuario_id", "usuario_id"),
        Index("ix_mcp_write_actions_created_at", "created_at"),
        Index("ix_mcp_write_actions_plan_id", "plan_id"),
    )

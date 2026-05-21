"""
BancoMovimiento — append-only ledger for bank account movements.

Each row represents one atomic balance change on a BancoEmpresa account.
Pattern mirrors CajaMovimiento: saldo_posterior is a snapshot for fast
historical queries; saldo_actual on BancoEmpresa is the denormalized running
balance updated transactionally by BancoService.registrar_movimiento.

APPEND-ONLY invariant: rows are never deleted after creation, and their
financial fields (monto, tipo, banco_id) are immutable. The sole exception
is `BancoService.recalcular_saldo`, a repair utility that corrects
saldo_posterior snapshots after manual DB fixes — it must only be used in
controlled reconciliation contexts, never in the normal payment flow.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class BancoMovimiento(Base):
    """Movimiento de cuenta bancaria — egreso o ingreso, append-only."""

    __tablename__ = "banco_movimientos"

    id = Column(Integer, primary_key=True, index=True)

    # ── Foreign keys ──────────────────────────────────────────────
    banco_id = Column(
        Integer,
        ForeignKey("bancos_empresa.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # ── Movement data ─────────────────────────────────────────────
    fecha = Column(Date, nullable=False)
    detalle = Column(String(500), nullable=False)
    tipo = Column(String(10), nullable=False)  # 'ingreso' | 'egreso'
    monto = Column(Numeric(18, 2), nullable=False)
    saldo_posterior = Column(Numeric(18, 2), nullable=False)

    # ── Metadata ──────────────────────────────────────────────────
    origen = Column(String(50), nullable=False, default="manual", server_default="manual")
    observaciones = Column(Text, nullable=True)

    # ── Audit ─────────────────────────────────────────────────────
    registrado_por_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────────
    banco = relationship("BancoEmpresa", back_populates="movimientos")
    registrado_por = relationship("Usuario")

    # ── Constraints & Indexes ─────────────────────────────────────
    __table_args__ = (
        CheckConstraint("monto > 0", name="ck_banco_mov_monto_positivo"),
        CheckConstraint("tipo IN ('ingreso', 'egreso')", name="ck_banco_mov_tipo"),
        Index("ix_banco_mov_banco_fecha", "banco_id", "fecha"),
        Index("ix_banco_mov_banco_tipo", "banco_id", "tipo"),
    )

    def __repr__(self) -> str:
        return f"<BancoMovimiento(id={self.id}, banco_id={self.banco_id}, tipo='{self.tipo}', monto={self.monto})>"

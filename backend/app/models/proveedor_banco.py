"""
Modelo ProveedorBanco — datos bancarios de un proveedor.

Cada proveedor puede tener múltiples cuentas bancarias.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class ProveedorBanco(Base):
    __tablename__ = "proveedor_bancos"

    id = Column(Integer, primary_key=True, index=True)
    proveedor_id = Column(
        Integer,
        ForeignKey("proveedores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Datos bancarios ───────────────────────────────────────────
    banco = Column(String(255), nullable=False)
    tipo_cuenta = Column(String(50), nullable=True)  # "CA $", "CC $", "CA USD", etc.
    cbu = Column(String(30), nullable=True)
    alias = Column(String(100), nullable=True)
    numero_cuenta = Column(String(50), nullable=True)
    sucursal = Column(String(100), nullable=True)
    titular = Column(String(255), nullable=True)
    cuit_titular = Column(String(20), nullable=True)
    moneda = Column(String(10), nullable=True, default="ARS")  # ARS, USD
    notas = Column(Text, nullable=True)

    # ── Estado ────────────────────────────────────────────────────
    activo = Column(Boolean, default=True, nullable=False)

    # ── Auditoría ─────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=True,
    )

    # ── Relación ──────────────────────────────────────────────────
    proveedor = relationship("Proveedor", back_populates="bancos")

    def __repr__(self) -> str:
        return f"<ProveedorBanco(id={self.id}, banco='{self.banco}', cbu='{self.cbu}')>"

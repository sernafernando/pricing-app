"""
Modelo BancoEmpresa — cuentas bancarias propias de la empresa.

Cada registro representa una cuenta bancaria que la empresa opera.
Se usa como base para el módulo de caja/tesorería.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
)

from app.core.database import Base


class BancoEmpresa(Base):
    __tablename__ = "bancos_empresa"

    id = Column(Integer, primary_key=True, index=True)

    # ── Datos del banco ───────────────────────────────────────────
    banco = Column(String(255), nullable=False)
    tipo_cuenta = Column(String(50), nullable=True)  # "CA $", "CC $", "CA USD", etc.
    cbu = Column(String(30), nullable=True, unique=True)
    alias = Column(String(100), nullable=True)
    numero_cuenta = Column(String(50), nullable=True)
    sucursal = Column(String(100), nullable=True)
    moneda = Column(String(10), nullable=False, default="ARS")

    # ── Titularidad ───────────────────────────────────────────────
    titular = Column(String(255), nullable=True)
    cuit_titular = Column(String(20), nullable=True)

    # ── Saldo inicial (para arrancar el módulo de caja) ───────────
    saldo_inicial = Column(Numeric(18, 2), nullable=False, default=0)

    # ── Notas ─────────────────────────────────────────────────────
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

    def __repr__(self) -> str:
        return f"<BancoEmpresa(id={self.id}, banco='{self.banco}', cbu='{self.cbu}')>"

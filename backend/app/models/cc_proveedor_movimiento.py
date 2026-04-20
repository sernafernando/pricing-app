"""
CCProveedorMovimiento — libro mayor de cuenta corriente de proveedor.

Fuente de verdad del saldo propio (reemplaza eventualmente el snapshot
`cuentas_corrientes_proveedores` sincronizado desde el ERP — ver R2 de
state.yaml). Cada movimiento es inmutable (append-only): ajustes se
modelan con `tipo='ajuste'` + `signo_ajuste` ∈ {+1, -1}.

El saldo por moneda se calcula con:
  SUM(CASE tipo WHEN 'debe' THEN monto WHEN 'haber' THEN -monto
                WHEN 'ajuste' THEN signo_ajuste * monto END)
GROUP BY moneda.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class CCProveedorMovimiento(Base):
    """Movimiento del libro mayor de CC por proveedor (append-only)."""

    __tablename__ = "cc_proveedor_movimientos"

    id = Column(BigInteger, primary_key=True, index=True)
    proveedor_id = Column(
        Integer,
        ForeignKey("proveedores.id", ondelete="RESTRICT"),
        nullable=False,
    )
    empresa_id = Column(
        Integer,
        ForeignKey("empresas.id", ondelete="RESTRICT"),
        nullable=False,
    )
    fecha_movimiento = Column(Date, nullable=False)
    tipo = Column(String(8), nullable=False)
    signo_ajuste = Column(SmallInteger, nullable=True)
    monto = Column(Numeric(18, 2), nullable=False)
    moneda = Column(String(3), nullable=False)
    tipo_cambio_a_ars = Column(Numeric(18, 6), nullable=True)
    origen_tipo = Column(String(32), nullable=False)
    origen_id = Column(BigInteger, nullable=True)
    descripcion = Column(String(500), nullable=True)
    creado_por_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    proveedor = relationship("Proveedor")
    empresa = relationship("Empresa")
    creado_por = relationship("Usuario")

    __table_args__ = (
        CheckConstraint("tipo IN ('debe','haber','ajuste')", name="ck_ccpm_tipo"),
        CheckConstraint("signo_ajuste IN (1, -1)", name="ck_ccpm_signo_ajuste_valores"),
        CheckConstraint("monto > 0", name="ck_ccpm_monto_positivo"),
        CheckConstraint("moneda IN ('ARS','USD')", name="ck_ccpm_moneda"),
        CheckConstraint(
            "(tipo = 'ajuste' AND signo_ajuste IS NOT NULL) OR (tipo <> 'ajuste' AND signo_ajuste IS NULL)",
            name="chk_cc_ajuste_signo",
        ),
        Index(
            "ix_ccpm_proveedor_fecha",
            "proveedor_id",
            "fecha_movimiento",
            "id",
        ),
        Index("ix_ccpm_origen", "origen_tipo", "origen_id"),
        Index("ix_ccpm_empresa_proveedor", "empresa_id", "proveedor_id"),
        Index("ix_ccpm_proveedor_moneda", "proveedor_id", "moneda"),
    )

    def __repr__(self) -> str:
        return (
            f"<CCProveedorMovimiento(id={self.id}, proveedor_id={self.proveedor_id}, "
            f"tipo='{self.tipo}', monto={self.monto} {self.moneda})>"
        )

"""
DineroACuenta — objeto de tracking del overpay real-money dentro del CC.

El dinero real vive en `cc_proveedor_movimientos` (como siempre).
Esta tabla es un índice navegable con lifecycle por proveedor+moneda.

Lifecycle: disponible → consumido_parcial → consumido.
El `estado` es un CACHE derivado (AD-3) — recalculado por
`dinero_a_cuenta_service.recalcular_estado` tras cada imputación.
El saldo consumible real se computa sumando imputaciones (append-only),
igual que el saldo_pendiente de un pedido o NC local.

NO guarda saldo mutable. `monto` es el monto original inmutable.

References:
  - design §1.1, AD-2, AD-3
  - tasks T2.2
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class DineroACuenta(Base):
    """Fila de tracking de dinero a cuenta (overpay de OP) dentro del CC."""

    __tablename__ = "dinero_a_cuenta"

    id = Column(BigInteger, primary_key=True)

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
    # Monto original creado — INMUTABLE.
    monto = Column(Numeric(18, 2), nullable=False)
    # Per-moneda: ARS o USD. Cross-moneda prohibido (INV-4).
    moneda = Column(String(3), nullable=False)
    # Cache derivado (AD-3). Fuente de verdad: imputaciones.
    estado = Column(String(20), nullable=False, server_default="disponible")

    # OP que originó este dinero a cuenta (item pago_a_cuenta).
    origen_op_id = Column(
        BigInteger,
        ForeignKey("ordenes_pago.id", ondelete="RESTRICT"),
        nullable=False,
    )
    creado_por_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    proveedor = relationship("Proveedor")
    empresa = relationship("Empresa")
    origen_op = relationship("OrdenPago", foreign_keys=[origen_op_id])
    creado_por = relationship("Usuario")

    __table_args__ = (
        CheckConstraint("monto > 0", name="ck_dac_monto_positivo"),
        CheckConstraint("moneda IN ('ARS','USD')", name="ck_dac_moneda"),
        CheckConstraint(
            "estado IN ('disponible','consumido_parcial','consumido')",
            name="ck_dac_estado",
        ),
        Index("ix_dinero_a_cuenta_proveedor_estado", "proveedor_id", "estado"),
        Index("ix_dinero_a_cuenta_proveedor_moneda", "proveedor_id", "moneda"),
        Index("ix_dinero_a_cuenta_origen_op", "origen_op_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<DineroACuenta(id={self.id}, proveedor_id={self.proveedor_id}, "
            f"monto={self.monto} {self.moneda}, estado='{self.estado}')>"
        )

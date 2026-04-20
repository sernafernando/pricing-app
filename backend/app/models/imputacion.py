"""
Imputacion — relación monetaria polimórfica entre origen y destino (D9).

Une flujos de dinero (orden de pago, nota de crédito ERP) con obligaciones
(pedido de compra, factura ERP, saldo a cuenta). `origen_tipo` y
`destino_tipo` son VARCHAR abiertos; la whitelist v1 (6 combos) vive
en `imputaciones_service.COMBOS_VALIDOS_V1`.

**Append-only** (D9): re-imputación y desimputación NO hacen UPDATE ni
DELETE — insertan filas nuevas con `es_reversal=True` y
`reimputada_desde_id` apuntando a la original. El saldo neto contra el
destino se obtiene agregando todas las filas.

Cross-moneda prohibido en v1 (D3): origen y destino deben compartir
moneda.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
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


class Imputacion(Base):
    """Imputación polimórfica origen→destino, append-only con reversals."""

    __tablename__ = "imputaciones"

    id = Column(BigInteger, primary_key=True, index=True)
    origen_tipo = Column(String(32), nullable=False)
    origen_id = Column(BigInteger, nullable=False)
    destino_tipo = Column(String(32), nullable=False)
    destino_id = Column(BigInteger, nullable=True)
    monto_imputado = Column(Numeric(18, 2), nullable=False)
    moneda_imputada = Column(String(3), nullable=False)
    tipo_cambio = Column(Numeric(18, 6), nullable=True)
    proveedor_id = Column(
        Integer,
        ForeignKey("proveedores.id", ondelete="RESTRICT"),
        nullable=False,
    )
    es_reversal = Column(Boolean, nullable=False, default=False, server_default="false")
    reimputada_desde_id = Column(
        BigInteger,
        ForeignKey("imputaciones.id", ondelete="RESTRICT"),
        nullable=True,
    )
    creado_por_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    proveedor = relationship("Proveedor")
    creado_por = relationship("Usuario")
    reimputada_desde = relationship("Imputacion", remote_side="Imputacion.id", foreign_keys=[reimputada_desde_id])

    __table_args__ = (
        CheckConstraint("monto_imputado > 0", name="ck_imputaciones_monto_positivo"),
        CheckConstraint("moneda_imputada IN ('ARS','USD')", name="ck_imputaciones_moneda"),
        CheckConstraint(
            "(destino_tipo = 'saldo' AND destino_id IS NULL) OR (destino_tipo <> 'saldo' AND destino_id IS NOT NULL)",
            name="chk_imputacion_saldo_id",
        ),
        Index(
            "ix_imputaciones_proveedor_created",
            "proveedor_id",
            "created_at",
        ),
        Index("ix_imputaciones_origen", "origen_tipo", "origen_id"),
        Index(
            "ix_imputaciones_destino",
            "destino_tipo",
            "destino_id",
            postgresql_where="destino_id IS NOT NULL",
        ),
        Index(
            "ix_imputaciones_reversal",
            "origen_id",
            postgresql_where="es_reversal = true",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Imputacion(id={self.id}, {self.origen_tipo}:{self.origen_id} -> "
            f"{self.destino_tipo}:{self.destino_id}, monto={self.monto_imputado} "
            f"{self.moneda_imputada}, reversal={self.es_reversal})>"
        )

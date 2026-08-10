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

**Doble pata** (compras_038): cada fila registra las DOS puntas del
vínculo, porque en cross-moneda no son el mismo número:

  - `monto_origen` / `moneda_origen`     → lo consumido del ORIGEN, en la
                                           moneda del ORIGEN.
  - `monto_imputado` / `moneda_imputada` → lo aplicado al DESTINO, en la
                                           moneda del DESTINO.
  - `tipo_cambio`                        → obligatorio si las monedas difieren.

Regla de lectura: las agregaciones origin-side (saldo de una NC, de un
dinero a cuenta) usan la pata ORIGEN; las destination-side (saldo de un
pedido, TC ponderado, CC del proveedor) usan la pata DESTINO. Mezclarlas
es exactamente el bug que `compras_038` cierra.

Ambas columnas de la pata origen son NULLABLE a nivel DB sólo para
tolerar filas escritas por instancias de app pre-compras_038 durante una
ventana de deploy rolling; `imputaciones_service.crear_imputacion` las
exige siempre. Los CHECK prohíben la pata a medias.

Cross-moneda: soportado. OP↔pedido desde `compras-cross-moneda-y-ncs-cc`;
NC↔pedido desde `compras-imputacion-doble-pata` (una NC es un medio de pago:
viaja por la cadena NC → OP → pedido y se graba denominada en el destino).
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
    # Pata origen (compras_038). Nullable sólo por tolerancia a filas legacy /
    # deploy rolling — `crear_imputacion` siempre las completa.
    monto_origen = Column(Numeric(18, 2), nullable=True)
    moneda_origen = Column(String(3), nullable=True)
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
            "monto_origen IS NULL OR monto_origen > 0",
            name="ck_imputaciones_monto_origen_positivo",
        ),
        CheckConstraint(
            "moneda_origen IS NULL OR moneda_origen IN ('ARS','USD')",
            name="ck_imputaciones_moneda_origen",
        ),
        CheckConstraint(
            "(monto_origen IS NULL AND moneda_origen IS NULL) "
            "OR (monto_origen IS NOT NULL AND moneda_origen IS NOT NULL)",
            name="ck_imputaciones_origen_leg_completa",
        ),
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
            f"{self.destino_tipo}:{self.destino_id}, origen={self.monto_origen} "
            f"{self.moneda_origen}, destino={self.monto_imputado} "
            f"{self.moneda_imputada}, reversal={self.es_reversal})>"
        )

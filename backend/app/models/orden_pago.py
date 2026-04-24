"""
OrdenPago — orden de pago a proveedor con integración Cajas + CC.

Una OP representa un pago (o promesa de pago) a un proveedor. Al
ejecutar el pago dispara un movimiento de caja (egreso) + un documento
de caja polimórfico (`entidad_tipo='orden_pago'`) y crea imputaciones
contra pedidos/facturas/saldo según `modo_imputacion`.

Restricciones v1:
  - `moneda` OP debe coincidir con `moneda` de la caja elegida (D7 → HTTP 422).
  - Cross-moneda en imputaciones prohibido (D3).
  - Anulación genera documento adicional `orden_pago_anulada` (D19).
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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class OrdenPago(Base):
    """Orden de pago a proveedor — vincula caja + imputaciones + CC."""

    __tablename__ = "ordenes_pago"

    id = Column(BigInteger, primary_key=True, index=True)
    numero = Column(String(32), nullable=False)
    empresa_id = Column(
        Integer,
        ForeignKey("empresas.id", ondelete="RESTRICT"),
        nullable=False,
    )
    proveedor_id = Column(
        Integer,
        ForeignKey("proveedores.id", ondelete="RESTRICT"),
        nullable=False,
    )
    moneda = Column(String(3), nullable=False)
    monto_total = Column(Numeric(18, 2), nullable=False)
    tipo_cambio = Column(Numeric(18, 6), nullable=True)
    modo_imputacion = Column(String(16), nullable=False)
    estado = Column(String(16), nullable=False, default="pendiente", server_default="pendiente")
    caja_id = Column(
        Integer,
        ForeignKey("cajas.id", ondelete="RESTRICT"),
        nullable=True,
    )
    # NOTE: el design §1.3 especifica BIGINT para caja_movimiento_id pero
    # caja_movimientos.id es Integer en el modelo existente → usamos Integer
    # para que la FK sea consistente (levantado como riesgo en el contract).
    caja_movimiento_id = Column(
        Integer,
        ForeignKey("caja_movimientos.id", ondelete="RESTRICT"),
        nullable=True,
    )
    caja_documento_id = Column(
        Integer,
        ForeignKey("caja_documentos.id", ondelete="RESTRICT"),
        nullable=True,
    )
    fecha_pago_estimada = Column(Date, nullable=True)
    fecha_pago_real = Column(Date, nullable=True)
    observaciones = Column(Text, nullable=True)
    creado_por_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pagado_por_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    paid_at = Column(DateTime(timezone=True), nullable=True)

    empresa = relationship("Empresa")
    proveedor = relationship("Proveedor")
    caja = relationship("Caja")
    caja_movimiento = relationship("CajaMovimiento")
    caja_documento = relationship("CajaDocumento")
    creado_por = relationship("Usuario", foreign_keys=[creado_por_id])
    pagado_por = relationship("Usuario", foreign_keys=[pagado_por_id])

    __table_args__ = (
        UniqueConstraint("numero", name="uq_ordenes_pago_numero"),
        CheckConstraint("moneda IN ('ARS','USD')", name="ck_ordenes_pago_moneda"),
        CheckConstraint("monto_total > 0", name="ck_ordenes_pago_monto_positivo"),
        CheckConstraint(
            "modo_imputacion IN ('especifica','a_cuenta','mixta')",
            name="ck_ordenes_pago_modo_imputacion",
        ),
        CheckConstraint(
            "estado IN ('pendiente','pagado','anulado','cancelado')",
            name="ck_ordenes_pago_estado",
        ),
        Index("ix_ordenes_pago_proveedor_estado", "proveedor_id", "estado"),
        Index("ix_ordenes_pago_empresa_created", "empresa_id", "created_at"),
        Index(
            "ix_ordenes_pago_caja_mov",
            "caja_movimiento_id",
            postgresql_where="caja_movimiento_id IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<OrdenPago(id={self.id}, numero='{self.numero}', estado='{self.estado}', "
            f"monto_total={self.monto_total} {self.moneda})>"
        )

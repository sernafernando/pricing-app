"""
PedidoCompra — solicitud de compra a proveedor (flujo de aprobación).

Entidad cabecera del módulo de compras. Modela el ciclo de vida:
borrador → pendiente_aprobacion → aprobado → (pagado_parcial |) pagado
con ramas hacia rechazado/cancelado. Los eventos del ciclo se registran
en la tabla polimórfica `compras_eventos` (no hay tabla separada).

`ct_transaction_id` es una FK LÓGICA a `tb_commercial_transactions.ct_transaction`
sin restricción física: el ERP llena esa tabla vía sync externo y una FK
real bloquearía el sync. El `erp_matching_service` valida existencia.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
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


class PedidoCompra(Base):
    """Pedido de compra a proveedor con flujo de aprobación y pagos imputados."""

    __tablename__ = "pedidos_compra"

    id = Column(BigInteger, primary_key=True, index=True)
    numero = Column(String(32), nullable=False)
    empresa_id = Column(
        Integer,
        ForeignKey("empresas.id", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
    )
    proveedor_id = Column(
        Integer,
        ForeignKey("proveedores.id", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
    )
    moneda = Column(String(3), nullable=False)
    monto = Column(Numeric(18, 2), nullable=False)
    # Cotización ARS/USD al momento del pedido. Solo aplica cuando moneda='USD'.
    # NULL + USD → el servicio intenta leer el TC del día al consultar.
    tipo_cambio = Column(Numeric(18, 6), nullable=True)
    fecha_pago_texto = Column(String(200), nullable=True)
    fecha_pago_estimada = Column(Date, nullable=True)
    requiere_envio = Column(Boolean, nullable=False, default=False, server_default="false")
    numero_factura = Column(String(50), nullable=True)
    ct_transaction_id = Column(BigInteger, nullable=True)
    # F1 — Immutable snapshot of tipo_cambio at approval time. Set once when the
    # pedido transitions to 'aprobado' and never overwritten. NULL for ARS pedidos
    # (no TC) or pre-F1 pedidos where TC was already NULL.
    # Backfill migration: tipo_cambio_original = tipo_cambio for existing rows.
    tipo_cambio_original = Column(Numeric(18, 6), nullable=True)

    # Notas libres del pedido. Editable en borrador y en aprobado/pagado_parcial/pagado
    # como metadata (no impacta CC ni imputaciones). Ver compras_026_pedido_observaciones.
    observaciones = Column(Text, nullable=True)
    estado = Column(
        String(24),
        nullable=False,
        default="borrador",
        server_default="borrador",
    )
    creado_por_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False,
    )
    aprobado_por_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Feature D — círculo cerrado de correcciones (self-ref, nullable).
    # Si no-NULL, este pedido es un clon corrección del referenciado.
    corregido_desde_id = Column(
        BigInteger,
        ForeignKey("pedidos_compra.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Si no-NULL, este pedido fue reemplazado (cancelado) por el clon referenciado.
    corregido_a_id = Column(
        BigInteger,
        ForeignKey("pedidos_compra.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    empresa = relationship("Empresa")
    proveedor = relationship("Proveedor")
    creado_por = relationship("Usuario", foreign_keys=[creado_por_id])
    aprobado_por = relationship("Usuario", foreign_keys=[aprobado_por_id])
    # Self-ref relationships para el círculo de correcciones (Feature D).
    # `post_update=True` evita ciclos en la transacción cuando se setean
    # ambos FKs (clon.corregido_desde_id y original.corregido_a_id) a la
    # vez: SQLAlchemy emite un UPDATE extra tras el flush inicial.
    corregido_desde = relationship(
        "PedidoCompra",
        foreign_keys=[corregido_desde_id],
        remote_side="PedidoCompra.id",
        post_update=True,
    )
    corregido_a = relationship(
        "PedidoCompra",
        foreign_keys=[corregido_a_id],
        remote_side="PedidoCompra.id",
        post_update=True,
    )

    __table_args__ = (
        UniqueConstraint("numero", name="uq_pedidos_compra_numero"),
        CheckConstraint("moneda IN ('ARS','USD')", name="ck_pedidos_compra_moneda"),
        CheckConstraint("monto > 0", name="ck_pedidos_compra_monto_positivo"),
        CheckConstraint(
            "estado IN ('borrador','pendiente_aprobacion','aprobado','rechazado',"
            "'cancelado','pagado_parcial','pagado')",
            name="ck_pedidos_compra_estado",
        ),
        Index("ix_pedidos_compra_empresa_estado", "empresa_id", "estado"),
        Index(
            "ix_pedidos_compra_proveedor_created",
            "proveedor_id",
            "created_at",
        ),
        Index(
            "ix_pedidos_compra_numero_factura",
            "proveedor_id",
            "numero_factura",
            postgresql_where="numero_factura IS NOT NULL",
        ),
        Index(
            "ix_pedidos_compra_ct_transaction",
            "ct_transaction_id",
            postgresql_where="ct_transaction_id IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PedidoCompra(id={self.id}, numero='{self.numero}', "
            f"estado='{self.estado}', monto={self.monto} {self.moneda})>"
        )

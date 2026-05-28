"""
NotaCreditoLocal — nota de crédito de proveedor cargada manualmente en
pricing-app (v2 del módulo compras).

Modela NCs que los PMs/tesorería cargan ANTES de que el ERP las registre,
o NCs que el ERP no va a registrar (ajustes internos, variaciones de TC,
bonificaciones internas, etc.).

Patrón análogo a `pedido_compra` (mismo flujo de aprobación, eventos en
`compras_eventos` polimórfico, vinculación con ERP via `ct_transaction_id`
como FK lógica sin restricción física), pero con UN cambio semántico clave:

  - PedidoCompra aprobado → DEBE en CC (deuda reconocida).
  - NotaCreditoLocal aprobada → NO impacta CC. La NC es CRÉDITO disponible
    que solo entra a CC cuando se IMPUTA a un pedido o factura específica
    via `imputaciones_service`. Análogo a OPs (no tocan caja hasta el pago).

`ct_transaction_id` es FK lógica a `tb_commercial_transactions.ct_transaction`
(sin restricción física: la tabla se puebla via sync externo y una FK real
bloquearía el sync). Se setea via `vincular_factura_erp` o por matching
automático en `erp_matching_service.match_ncs_backward`.
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


class NotaCreditoLocal(Base):
    """Nota de crédito local cargada en pricing-app (workflow de aprobación)."""

    __tablename__ = "notas_credito_local"

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
    # Cotización ARS/USD al momento de cargar la NC. Solo aplica a moneda='USD'.
    # NULL + USD → el servicio intenta leer el TC del día.
    tipo_cambio = Column(Numeric(18, 6), nullable=True)
    # Fecha en la que la NC fue emitida por el proveedor (carga manual del PM).
    fecha_emision = Column(Date, nullable=False)
    # Número de la NC tal como lo emitió el proveedor (ej: "NC-A-0001-00000042").
    # Llave de matching contra `tb_commercial_transactions.ct_docnumber` cuando
    # el ERP sincroniza la NC.
    numero_nc_proveedor = Column(String(50), nullable=True)
    motivo = Column(Text, nullable=False)
    observaciones = Column(Text, nullable=True)
    # FK lógica al ERP (ver docstring del módulo).
    ct_transaction_id = Column(BigInteger, nullable=True)
    # F2 — ND/NC variance circuit (compras_030).
    # 'credito' → HABER en CC (reduce deuda). 'debito' → DEBE en CC (aumenta deuda).
    # Backfill-safe: server_default='credito' preserva la semántica actual de todas
    # las filas existentes (NC = reduce deuda = HABER).
    tipo = Column(
        String(8),
        nullable=False,
        default="credito",
        server_default="credito",
    )
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

    __table_args__ = (
        UniqueConstraint("numero", name="uq_notas_credito_local_numero"),
        CheckConstraint("tipo IN ('credito','debito')", name="ck_ncs_local_tipo"),
        CheckConstraint("moneda IN ('ARS','USD')", name="ck_ncs_local_moneda"),
        CheckConstraint("monto > 0", name="ck_ncs_local_monto_positivo"),
        CheckConstraint(
            "estado IN ('borrador','pendiente_aprobacion','aprobado','rechazado',"
            "'cancelado','aplicada_parcial','aplicada')",
            name="ck_ncs_local_estado",
        ),
        Index("ix_ncs_local_empresa_estado", "empresa_id", "estado"),
        Index("ix_ncs_local_proveedor_estado", "proveedor_id", "estado"),
        # Unique constraint parcial: un mismo número de NC de proveedor no puede
        # aparecer más de una vez por proveedor. WHERE IS NOT NULL porque muchas
        # NCs locales no tienen número de proveedor (no corresponde a ERP aún).
        Index(
            "uq_ncs_local_proveedor_numero_nc_prov",
            "proveedor_id",
            "numero_nc_proveedor",
            unique=True,
            postgresql_where="numero_nc_proveedor IS NOT NULL",
        ),
        Index(
            "ix_ncs_local_ct_transaction",
            "ct_transaction_id",
            postgresql_where="ct_transaction_id IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<NotaCreditoLocal(id={self.id}, numero='{self.numero}', "
            f"estado='{self.estado}', monto={self.monto} {self.moneda})>"
        )

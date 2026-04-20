"""
CCReconciliacionLog — log de corridas del cron de reconciliación CC (D6).

Registra una fila por cada combinación (fecha_corrida, proveedor_id,
moneda) del cron standalone diario (design §8.2). Compara el saldo del
libro mayor propio (`cc_proveedor_movimientos`) contra el snapshot
sincronizado desde el ERP (`cuentas_corrientes_proveedores`) con una
`tolerancia_aplicada` leída de `configuracion`.

`alerta_id` y `notificacion_id` son FKs nullable a las tablas
existentes `alertas` (banner agregado) y `notificaciones` (feed
individual por divergencia) — permite trazabilidad sin crear tabla
nueva.
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
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class CCReconciliacionLog(Base):
    """Log diario de reconciliación CC libro mayor vs snapshot ERP."""

    __tablename__ = "cc_reconciliacion_log"

    ESTADO_OK: str = "ok"
    ESTADO_DIVERGENCIA: str = "divergencia"

    id = Column(BigInteger, primary_key=True, index=True)
    fecha_corrida = Column(Date, nullable=False)
    proveedor_id = Column(
        Integer,
        ForeignKey("proveedores.id", ondelete="RESTRICT"),
        nullable=False,
    )
    moneda = Column(String(3), nullable=False)
    saldo_libro_mayor = Column(Numeric(18, 2), nullable=False)
    saldo_snapshot = Column(Numeric(18, 2), nullable=False)
    diferencia = Column(Numeric(18, 2), nullable=False)
    tolerancia_aplicada = Column(Numeric(18, 2), nullable=False)
    estado = Column(String(16), nullable=False)
    nota = Column(String(500), nullable=True)
    alerta_id = Column(
        Integer,
        ForeignKey("alertas.id", ondelete="SET NULL"),
        nullable=True,
    )
    notificacion_id = Column(
        Integer,
        ForeignKey("notificaciones.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    proveedor = relationship("Proveedor")
    alerta = relationship("Alerta")
    notificacion = relationship("Notificacion")

    __table_args__ = (
        CheckConstraint("moneda IN ('ARS','USD')", name="ck_cc_recon_moneda"),
        CheckConstraint("estado IN ('ok','divergencia')", name="ck_cc_recon_estado"),
        UniqueConstraint(
            "fecha_corrida",
            "proveedor_id",
            "moneda",
            name="uq_reconciliacion_corrida",
        ),
        Index(
            "ix_reconciliacion_estado_fecha",
            "estado",
            "fecha_corrida",
        ),
        Index(
            "ix_reconciliacion_proveedor",
            "proveedor_id",
            "fecha_corrida",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CCReconciliacionLog(id={self.id}, fecha={self.fecha_corrida}, "
            f"proveedor_id={self.proveedor_id}, moneda='{self.moneda}', "
            f"estado='{self.estado}', diferencia={self.diferencia})>"
        )

"""
CompraEvento — log polimórfico de eventos del módulo compras (D2).

Reemplaza a dos tablas paralelas (`pedido_compra_eventos` +
`ordenes_pago_eventos`) con una única tabla donde `entidad_tipo`
discrimina el dueño del evento. Append-only: no se exponen endpoints
PUT/DELETE y la lógica de servicio jamás actualiza ni borra filas.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class CompraEvento(Base):
    """Evento de auditoría para pedidos de compra u órdenes de pago."""

    __tablename__ = "compras_eventos"

    ENTIDAD_TIPO_PEDIDO: str = "pedido_compra"
    ENTIDAD_TIPO_ORDEN_PAGO: str = "orden_pago"
    ENTIDAD_TIPO_NC_LOCAL: str = "nota_credito_local"

    id = Column(BigInteger, primary_key=True, index=True)
    entidad_tipo = Column(String(32), nullable=False)
    entidad_id = Column(BigInteger, nullable=False)
    tipo = Column(String(48), nullable=False)
    usuario_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payload = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    usuario = relationship("Usuario")

    __table_args__ = (
        CheckConstraint(
            "entidad_tipo IN ('pedido_compra','orden_pago','nota_credito_local')",
            name="ck_compras_eventos_entidad_tipo",
        ),
        Index(
            "ix_compras_eventos_entidad",
            "entidad_tipo",
            "entidad_id",
            "created_at",
        ),
        Index("ix_compras_eventos_tipo", "tipo"),
    )

    def __repr__(self) -> str:
        return f"<CompraEvento(id={self.id}, entidad={self.entidad_tipo}:{self.entidad_id}, tipo='{self.tipo}')>"

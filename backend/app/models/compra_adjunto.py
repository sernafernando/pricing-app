"""
CompraAdjunto — adjuntos polimórficos para pedidos de compra y órdenes de pago.

Una sola tabla sirve ambas entidades vía `entidad_tipo`, patrón consistente
con `compras_eventos`, `compras_papelera` y `caja_documentos.entidad_tipo`.

Los archivos se guardan en filesystem local bajo:
    {COMPRAS_UPLOADS_DIR}/{entidad_tipo}/{entidad_id}/{uuid}_{filename}

La columna `path_archivo` es el path RELATIVO a `COMPRAS_UPLOADS_DIR` (no
incluye la raíz) — así podemos mover la raíz sin migrar la DB.

NO es append-only: los adjuntos SÍ se pueden eliminar (hard delete con
borrado del archivo físico). Los eventos derivados quedan en
`compras_eventos` si el router decide loguearlos (v1 no lo hace).
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
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class CompraAdjunto(Base):
    """Adjunto de un pedido de compra o de una orden de pago."""

    __tablename__ = "compras_adjuntos"

    ENTIDAD_TIPO_PEDIDO: str = "pedido_compra"
    ENTIDAD_TIPO_ORDEN_PAGO: str = "orden_pago"
    ENTIDAD_TIPO_NC_LOCAL: str = "nota_credito_local"

    id = Column(BigInteger, primary_key=True, index=True)
    entidad_tipo = Column(String(32), nullable=False)
    entidad_id = Column(BigInteger, nullable=False)

    nombre_archivo = Column(String(255), nullable=False)
    path_archivo = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=True)
    tamano_bytes = Column(Integer, nullable=True)
    tipo = Column(String(20), nullable=True)  # 'factura' | 'presupuesto' | 'comprobante' | 'otro'
    descripcion = Column(Text, nullable=True)

    subido_por_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    subido_por = relationship("Usuario")

    __table_args__ = (
        CheckConstraint(
            "entidad_tipo IN ('pedido_compra','orden_pago','nota_credito_local')",
            name="ck_compras_adjuntos_entidad_tipo",
        ),
        CheckConstraint(
            "tipo IS NULL OR tipo IN ('factura','presupuesto','comprobante','otro')",
            name="ck_compras_adjuntos_tipo",
        ),
        Index(
            "ix_compras_adjuntos_entidad",
            "entidad_tipo",
            "entidad_id",
        ),
        Index("ix_compras_adjuntos_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<CompraAdjunto(id={self.id}, entidad={self.entidad_tipo}:{self.entidad_id}, "
            f"nombre='{self.nombre_archivo}', tamano={self.tamano_bytes})>"
        )

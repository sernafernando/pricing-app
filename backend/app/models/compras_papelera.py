"""
ComprasPapelera — papelera auditable de hard-deletes del módulo compras.

Guarda un snapshot JSONB completo de pedidos/OPs físicamente eliminados,
junto con metadata de auditoría (quién, cuándo, por qué, qué challenge
word tipeó). Los eventos de `compras_eventos` correspondientes a la
entidad se COPIAN dentro de `snapshot['eventos']` antes de borrarse
(opción B del scope) — la historia queda preservada en el JSON.

APPEND-ONLY: esta tabla es inmutable (misma regla que `compras_eventos`).
No se expone PUT/DELETE en el router. Si en el futuro aparece un caso de
"limpieza de papelera >1 año" se hace via cron que logee detalles.

Cross-reference:
  - Modelo: compras_016_papelera migration
  - Service: app.services.compras_papelera_service
  - Router: app.routers.administracion_compras (endpoints /papelera/*)
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ComprasPapelera(Base):
    """Fila de papelera: snapshot de una entidad compras físicamente eliminada."""

    __tablename__ = "compras_papelera"

    ENTIDAD_TIPO_PEDIDO: str = "pedido_compra"
    ENTIDAD_TIPO_ORDEN_PAGO: str = "orden_pago"

    id = Column(BigInteger, primary_key=True, index=True)
    entidad_tipo = Column(String(32), nullable=False)
    entidad_id_original = Column(BigInteger, nullable=False)
    numero = Column(String(32), nullable=True)
    empresa_id = Column(
        Integer,
        ForeignKey("empresas.id", ondelete="RESTRICT"),
        nullable=True,
    )
    proveedor_id = Column(
        Integer,
        ForeignKey("proveedores.id", ondelete="RESTRICT"),
        nullable=True,
    )
    snapshot = Column(JSONB, nullable=False)
    eliminado_por_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False,
    )
    motivo = Column(Text, nullable=False)
    challenge_palabra = Column(String(64), nullable=True)
    estado_original = Column(String(24), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    empresa = relationship("Empresa")
    proveedor = relationship("Proveedor")
    eliminado_por = relationship("Usuario")

    __table_args__ = (
        CheckConstraint(
            "entidad_tipo IN ('pedido_compra','orden_pago')",
            name="ck_compras_papelera_entidad_tipo",
        ),
        Index(
            "ix_compras_papelera_entidad",
            "entidad_tipo",
            "entidad_id_original",
        ),
        Index("ix_compras_papelera_created", "created_at"),
        Index(
            "ix_compras_papelera_proveedor",
            "proveedor_id",
            postgresql_where="proveedor_id IS NOT NULL",
        ),
        Index("ix_compras_papelera_eliminado_por", "eliminado_por_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ComprasPapelera(id={self.id}, entidad={self.entidad_tipo}:"
            f"{self.entidad_id_original}, numero='{self.numero}')>"
        )

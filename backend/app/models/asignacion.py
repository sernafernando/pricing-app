"""
Sistema genérico de asignaciones.

Diseñado para ser reutilizable en múltiples contextos:
- items_sin_mla: Asignación de items/listas faltantes a usuarios
- (futuro): comparacion_listas, pedidos, etc.

Cada asignación rastrea:
- QUÉ se asignó (tipo + referencia_id + subtipo)
- A QUIÉN se asignó (usuario_id)
- QUIÉN lo asignó (asignado_por_id) — auditoría de gestión
- CUÁNDO se asignó y cuándo se resolvió
- Un tracking_id UUID para rastreo externo
- Un estado_hash: fingerprint del estado al asignar, para detectar cambios
  y medir tiempo de resolución real (métricas de productividad)
- Origen: manual vs automático (para futuro)
"""

import uuid
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Asignacion(Base):
    """
    Registro de asignación genérica.

    Ejemplo para items_sin_mla:
        tipo = 'item_sin_mla'
        referencia_id = 12345  (item_id del producto)
        subtipo = 'Clásica'   (lista de precio faltante)
        tienda_oficial_id = 57997  (tienda oficial de ML donde falta)
        estado_hash = sha256 de listas_sin_mla al momento de asignar
    """

    __tablename__ = "asignaciones"

    id = Column(Integer, primary_key=True, index=True)
    tracking_id = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False, index=True)

    # Qué se asigna (genérico)
    tipo = Column(String(50), nullable=False, index=True)  # 'item_sin_mla', 'comparacion_listas', etc.
    referencia_id = Column(Integer, nullable=False, index=True)  # item_id, mla_id numérico, etc.
    subtipo = Column(String(100), nullable=True, index=True)  # 'Clásica', '3 Cuotas', etc.
    tienda_oficial_id = Column(Integer, nullable=True, index=True)  # mlp_official_store_id (57997=Gauss, etc.)

    # A quién se asigna
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)

    # Quién creó la asignación (auditoría)
    asignado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)

    # Estado
    estado = Column(String(20), nullable=False, default="pendiente", index=True)  # pendiente / completado / cancelado

    # Fingerprint del estado al momento de la asignación
    # Para items_sin_mla: sha256(sorted(listas_sin_mla)) — si el hash cambia,
    # el item fue modificado (publicación creada) y podemos medir tiempo de resolución
    estado_hash = Column(String(64), nullable=True)

    # Contexto al momento de la asignación (snapshot)
    metadata_asignacion = Column(JSONB, nullable=True)  # {'listas_faltantes': [...], 'listas_con_mla': [...]}

    # Origen (para escalabilidad automática)
    origen = Column(String(20), nullable=False, default="manual")  # manual / automatico

    # Timestamps
    fecha_asignacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fecha_resolucion = Column(DateTime(timezone=True), nullable=True)

    # Notas opcionales
    notas = Column(Text, nullable=True)

    # Relaciones
    usuario = relationship("Usuario", foreign_keys=[usuario_id], backref="asignaciones")
    asignado_por = relationship("Usuario", foreign_keys=[asignado_por_id], backref="asignaciones_creadas")

    # Indexes compuestos para queries frecuentes
    __table_args__ = (
        Index("idx_asignacion_tipo_ref", "tipo", "referencia_id"),
        Index("idx_asignacion_tipo_ref_subtipo", "tipo", "referencia_id", "subtipo"),
        Index("idx_asignacion_tipo_ref_subtipo_tienda", "tipo", "referencia_id", "subtipo", "tienda_oficial_id"),
        Index("idx_asignacion_usuario_estado", "usuario_id", "estado"),
        Index("idx_asignacion_tipo_estado", "tipo", "estado"),
        Index("idx_asignacion_asignado_por", "asignado_por_id"),
        Index("idx_asignacion_estado_hash", "estado_hash"),
    )

    def __repr__(self) -> str:
        return f"<Asignacion(id={self.id}, tipo={self.tipo}, ref={self.referencia_id}, subtipo={self.subtipo}, tienda={self.tienda_oficial_id}, estado={self.estado})>"

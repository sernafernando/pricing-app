from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import false, func
from app.core.database import Base


class OffsetGrupo(Base):
    """
    Grupo de offsets para agrupar múltiples productos/offsets que comparten límites.
    Permite que varios productos compartan un límite de unidades o monto máximo.
    """

    __tablename__ = "offset_grupos"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(String(255), nullable=True)
    # Created by a tactical line for its own products (tacticals T1): never listed in the Grupos tab nor offered to
    # pick; it lives and dies with its campaign.
    oculto = Column(Boolean, nullable=False, default=False, server_default=false())

    # Auditoría
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relaciones
    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    offsets = relationship("OffsetGanancia", back_populates="grupo")
    filtros = relationship("OffsetGrupoFiltro", back_populates="grupo", cascade="all, delete-orphan")

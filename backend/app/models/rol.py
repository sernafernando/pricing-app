"""
Modelo para roles dinámicos del sistema.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Rol(Base):
    """
    Roles del sistema.
    Reemplaza el enum RolUsuario con roles dinámicos almacenados en DB.
    """

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, nullable=False, index=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(Text, nullable=True)

    # Roles de sistema no se pueden eliminar (SUPERADMIN, ADMIN)
    es_sistema = Column(Boolean, default=False, nullable=False)

    # Orden para mostrar en selectores
    orden = Column(Integer, default=0, nullable=False)

    # Si está activo
    activo = Column(Boolean, default=True, nullable=False)

    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relaciones
    usuarios = relationship("Usuario", back_populates="rol_obj")
    permisos_base = relationship("RolPermisoBase", back_populates="rol_obj", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Rol(codigo='{self.codigo}', nombre='{self.nombre}')>"

    @property
    def es_superadmin(self) -> bool:
        """Verifica si es el rol SUPERADMIN"""
        return self.codigo == "SUPERADMIN"

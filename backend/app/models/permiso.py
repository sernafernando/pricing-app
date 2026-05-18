"""
Sistema de Permisos Híbrido
- Roles base con permisos por defecto
- Overrides por usuario (agregar o quitar permisos específicos)
"""

import enum

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class CategoriaPermiso(str, enum.Enum):
    """Categorías de permisos para organización en el panel"""

    PRODUCTOS = "productos"
    VENTAS_ML = "ventas_ml"
    VENTAS_FUERA = "ventas_fuera"
    VENTAS_TN = "ventas_tn"
    CLIENTES = "clientes"
    ADMINISTRACION = "administracion"
    REPORTES = "reportes"
    CONFIGURACION = "configuracion"
    ALERTAS = "alertas"
    ENVIOS_FLEX = "envios_flex"
    RRHH = "rrhh"
    TICKETS = "tickets"
    DOCUMENTOS = "documentos"
    ADMINISTRACION_SECTOR = "administracion_sector"


class Permiso(Base):
    """
    Catálogo de permisos disponibles en el sistema.
    Cada permiso representa una acción o acceso específico.
    """

    __tablename__ = "permisos"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(100), unique=True, nullable=False, index=True)
    nombre = Column(String(255), nullable=False)
    descripcion = Column(Text, nullable=True)
    # Usar String en vez de Enum para evitar problemas de caching de SQLAlchemy
    categoria = Column(String(50), nullable=False)

    # Orden para mostrar en el panel
    orden = Column(Integer, default=0)

    # Si es un permiso crítico (requiere confirmación adicional)
    es_critico = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Permiso({self.codigo})>"


class RolPermisoBase(Base):
    """
    Permisos por defecto de cada rol.
    Define qué permisos tiene un rol de forma predeterminada.
    """

    __tablename__ = "roles_permisos_base"
    __table_args__ = (UniqueConstraint("rol_id", "permiso_id", name="uq_rol_permiso"),)

    id = Column(Integer, primary_key=True, index=True)

    # Nuevo: FK a tabla roles
    rol_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True)

    permiso_id = Column(Integer, ForeignKey("permisos.id", ondelete="CASCADE"), nullable=False)

    # Relaciones
    rol_obj = relationship("Rol", back_populates="permisos_base")
    permiso = relationship("Permiso")

    def __repr__(self):
        return f"<RolPermisoBase(rol_id={self.rol_id}, permiso_id={self.permiso_id})>"


class UsuarioPermisoOverride(Base):
    """
    Overrides de permisos por usuario.
    Permite agregar o quitar permisos específicos a un usuario,
    independientemente de su rol base.
    """

    __tablename__ = "usuarios_permisos_override"
    __table_args__ = (UniqueConstraint("usuario_id", "permiso_id", name="uq_usuario_permiso"),)

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    permiso_id = Column(Integer, ForeignKey("permisos.id", ondelete="CASCADE"), nullable=False)

    # True = agregar permiso, False = quitar permiso
    concedido = Column(Boolean, nullable=False)

    # Auditoría
    otorgado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    motivo = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relaciones
    usuario = relationship("Usuario", foreign_keys=[usuario_id], backref="permisos_override")
    permiso = relationship("Permiso")
    otorgado_por = relationship("Usuario", foreign_keys=[otorgado_por_id])

    def __repr__(self):
        accion = "+" if self.concedido else "-"
        return f"<UsuarioPermisoOverride(usuario={self.usuario_id}, {accion}{self.permiso_id})>"


# =============================================================================
# Permisos del sistema: la fuente de verdad es la DB.
# Cada permiso se agrega/modifica vía migración Alembic
# (ver alembic/versions/*permiso*.py). Los roles base se gestionan vía
# /api/roles/{id}/permisos y se persisten en roles_permisos_base.
# =============================================================================

"""
Roles adicionales por usuario (solo permisos).

`usuarios.rol_id` sigue siendo el rol PRINCIPAL y decide la identidad (SUPERADMIN,
vista completa de marcas por código de rol, etiqueta del rol). Un rol adicional solo
suma los permisos base de ese rol a la unión; los overrides del usuario se aplican después.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class UsuarioRolAdicional(Base):
    __tablename__ = "usuarios_roles_adicionales"
    __table_args__ = (UniqueConstraint("usuario_id", "rol_id", name="uq_usuario_rol_adicional"),)

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    rol_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True)

    # Auditoría
    otorgado_por_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<UsuarioRolAdicional(usuario={self.usuario_id}, rol={self.rol_id})>"

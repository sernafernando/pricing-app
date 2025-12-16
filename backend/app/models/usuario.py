from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class RolUsuario(str, enum.Enum):
    """
    DEPRECADO: Usar tabla roles en su lugar.
    Se mantiene temporalmente para compatibilidad con código existente.
    """
    SUPERADMIN = "SUPERADMIN"
    ADMIN = "ADMIN"
    GERENTE = "GERENTE"
    PRICING = "PRICING"
    VENTAS = "VENTAS"


class AuthProvider(str, enum.Enum):
    LOCAL = "local"
    GOOGLE = "google"


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    nombre = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=True)  # Nullable para OAuth

    # Rol antiguo (DEPRECADO - mantener para compatibilidad)
    rol = Column(SQLEnum(RolUsuario), default=RolUsuario.VENTAS)

    # Nuevo: FK a tabla roles
    rol_id = Column(Integer, ForeignKey('roles.id'), nullable=True, index=True)

    auth_provider = Column(SQLEnum(AuthProvider), default=AuthProvider.LOCAL)

    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relaciones
    rol_obj = relationship("Rol", back_populates="usuarios")
    precios_modificados = relationship("ProductoPricing", back_populates="usuario", lazy="dynamic")
    auditorias = relationship("Auditoria", back_populates="usuario", lazy="dynamic")
    calculos_pricing = relationship("CalculoPricing", back_populates="usuario", lazy="dynamic")

    @property
    def rol_codigo(self) -> str:
        """Retorna el código del rol (compatible con código existente)"""
        if self.rol_obj:
            return self.rol_obj.codigo
        return self.rol.value if self.rol else "VENTAS"

    @property
    def es_superadmin(self) -> bool:
        """Verifica si el usuario es SUPERADMIN"""
        return self.rol_codigo == "SUPERADMIN"

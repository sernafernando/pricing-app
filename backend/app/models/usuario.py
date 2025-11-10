from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum

class RolUsuario(str, enum.Enum):
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
    
    rol = Column(SQLEnum(RolUsuario), default=RolUsuario.VENTAS)
    auth_provider = Column(SQLEnum(AuthProvider), default=AuthProvider.LOCAL)
    
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relaciones
    precios_modificados = relationship("ProductoPricing", back_populates="usuario", lazy="dynamic")
    auditorias = relationship("Auditoria", back_populates="usuario", lazy="dynamic")
    calculos_pricing = relationship("CalculoPricing", back_populates="usuario", lazy="dynamic")

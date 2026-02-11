from sqlalchemy import Column, Integer, String, Numeric, Boolean, Date, DateTime, ForeignKey, Text, CheckConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class ComisionVersion(Base):
    """Versión de comisiones con vigencia por fechas"""

    __tablename__ = "comisiones_versiones"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(200), nullable=False)
    descripcion = Column(Text)
    fecha_desde = Column(Date, nullable=False, index=True)
    fecha_hasta = Column(Date, index=True)
    activo = Column(Boolean, default=True, index=True)
    fecha_creacion = Column(DateTime, default=func.now())
    usuario_creacion = Column(String(100))

    # Relaciones
    comisiones_base = relationship("ComisionBase", back_populates="version", cascade="all, delete-orphan")
    adicionales_cuota = relationship("ComisionAdicionalCuota", back_populates="version", cascade="all, delete-orphan")

    __table_args__ = (CheckConstraint("fecha_hasta IS NULL OR fecha_hasta >= fecha_desde", name="chk_fechas"),)


class ComisionBase(Base):
    """Comisión base (lista 4) por grupo de subcategorías"""

    __tablename__ = "comisiones_base"

    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(Integer, ForeignKey("comisiones_versiones.id", ondelete="CASCADE"), nullable=False, index=True)
    grupo_id = Column(Integer, nullable=False, index=True)
    comision_base = Column(Numeric(5, 2), nullable=False)

    # Relación
    version = relationship("ComisionVersion", back_populates="comisiones_base")

    __table_args__ = (CheckConstraint("grupo_id > 0", name="chk_grupo_positivo"),)


class ComisionAdicionalCuota(Base):
    """Adicional que se suma a la comisión base para calcular comisiones en cuotas"""

    __tablename__ = "comisiones_adicionales_cuota"

    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(Integer, ForeignKey("comisiones_versiones.id", ondelete="CASCADE"), nullable=False, index=True)
    cuotas = Column(Integer, nullable=False)
    adicional = Column(Numeric(5, 2), nullable=False)

    # Relación
    version = relationship("ComisionVersion", back_populates="adicionales_cuota")

    __table_args__ = (CheckConstraint("cuotas IN (3, 6, 9, 12)", name="chk_cuotas_validas"),)

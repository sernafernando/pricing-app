from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class ZonaReparto(Base):
    """
    Modelo para zonas de reparto (polígonos GeoJSON).
    Usadas para asignación automática de envíos Turbo.
    """
    __tablename__ = "zonas_reparto"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    poligono = Column(JSONB, nullable=False)  # GeoJSON del polígono
    color = Column(String(7), nullable=False)  # Hex color (ej: #FF5733)
    activa = Column(Boolean, default=True, nullable=False, index=True)
    creado_por = Column(Integer, ForeignKey('usuarios.id'), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    asignaciones = relationship("AsignacionTurbo", back_populates="zona")

    def __repr__(self):
        return f"<ZonaReparto(id={self.id}, nombre='{self.nombre}', activa={self.activa})>"

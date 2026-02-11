from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Motoquero(Base):
    """
    Modelo para motoqueros/repartidores de envíos Turbo.
    """

    __tablename__ = "motoqueros"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    telefono = Column(String(20), nullable=True)
    activo = Column(Boolean, default=True, nullable=False, index=True)
    zona_preferida_id = Column(Integer, ForeignKey("zonas_reparto.id", ondelete="SET NULL"), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    zona_preferida = relationship("ZonaReparto", foreign_keys=[zona_preferida_id])
    asignaciones = relationship("AsignacionTurbo", back_populates="motoquero")

    def __repr__(self):
        return f"<Motoquero(id={self.id}, nombre='{self.nombre}', activo={self.activo})>"

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class MarcaPM(Base):
    __tablename__ = "marcas_pm"

    id = Column(Integer, primary_key=True, index=True)
    marca = Column(String(100), unique=True, index=True, nullable=False)
    usuario_id = Column(Integer, ForeignKey('usuarios.id'), nullable=True)

    fecha_asignacion = Column(DateTime(timezone=True), server_default=func.now())
    fecha_modificacion = Column(DateTime(timezone=True), onupdate=func.now())

    # Relación con usuario
    usuario = relationship("Usuario", backref="marcas_asignadas")

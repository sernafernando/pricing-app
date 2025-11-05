from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class Configuracion(Base):
    __tablename__ = "configuracion"

    clave = Column(String(100), primary_key=True)
    valor = Column(Text, nullable=False)
    descripcion = Column(Text)
    tipo = Column(String(50), default='string')
    fecha_modificacion = Column(DateTime, default=func.now(), onupdate=func.now())

from sqlalchemy import Column, Integer, String, Float, Boolean
from app.core.database import Base

class Subcategoria(Base):
    __tablename__ = "subcategorias"
    
    id = Column(Integer, primary_key=True, index=True)
    subcat_id = Column(Integer, unique=True, index=True)
    nombre = Column(String(200))
    comision_porcentaje = Column(Float)
    activo = Column(Boolean, default=True)

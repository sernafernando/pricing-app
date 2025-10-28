from sqlalchemy import Column, Integer, String, Float, Boolean
from app.core.database import Base

class GrupoComision(Base):
    """Grupos de subcategorías"""
    __tablename__ = "grupos_comision"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100))
    descripcion = Column(String(500), nullable=True)
    activo = Column(Boolean, default=True)

class SubcategoriaGrupo(Base):
    """Mapeo de subcategorías a grupos"""
    __tablename__ = "subcategorias_grupos"
    
    id = Column(Integer, primary_key=True, index=True)
    subcat_id = Column(Integer, unique=True, index=True)
    grupo_id = Column(Integer, index=True)
    nombre_subcategoria = Column(String(200), nullable=True)
    cat_id = Column(String(10), index=True, nullable=True)
    nombre_categoria = Column(String(200), nullable=True) 

class ComisionListaGrupo(Base):
    """Comisión según Lista de Precios (pricelist4) y Grupo"""
    __tablename__ = "comisiones_lista_grupo"
    
    id = Column(Integer, primary_key=True, index=True)
    pricelist_id = Column(Integer, index=True)  # 4, 5, 6, 17, etc
    grupo_id = Column(Integer, index=True)  # 1, 2, 3, etc
    comision_porcentaje = Column(Float)  # 15.5, 12.15, etc
    activo = Column(Boolean, default=True)

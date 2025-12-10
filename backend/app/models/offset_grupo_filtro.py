from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class OffsetGrupoFiltro(Base):
    """
    Filtros para un grupo de offsets.
    Cada filtro define una combinación de marca/categoría/subcategoría/producto
    que matchea con el grupo. Una venta matchea si cumple con AL MENOS UN filtro.

    Ejemplos de filtros:
    - marca="HP", categoria="Impresoras" -> todas las impresoras HP
    - marca="HP", categoria="Notebooks" -> todas las notebooks HP
    - marca="Lenovo", item_id=12345 -> un producto específico de Lenovo
    - categoria="Monitores" -> todos los monitores de cualquier marca
    """
    __tablename__ = "offset_grupo_filtros"

    id = Column(Integer, primary_key=True, index=True)
    grupo_id = Column(Integer, ForeignKey('offset_grupos.id', ondelete='CASCADE'), nullable=False, index=True)

    # Filtros (todos opcionales, se combinan con AND)
    marca = Column(String(255), nullable=True, index=True)
    categoria = Column(String(255), nullable=True, index=True)
    subcategoria_id = Column(Integer, nullable=True, index=True)
    item_id = Column(Integer, ForeignKey('productos_erp.item_id'), nullable=True, index=True)

    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relaciones
    grupo = relationship("OffsetGrupo", back_populates="filtros")
    producto = relationship("ProductoERP", foreign_keys=[item_id])

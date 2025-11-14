"""
Modelo para tbCategory - Categorías
"""
from sqlalchemy import Column, Integer, String
from app.core.database import Base


class TBCategory(Base):
    """Tabla de categorías del ERP"""
    __tablename__ = "tb_category"

    comp_id = Column(Integer, primary_key=True)
    cat_id = Column(Integer, primary_key=True)
    cat_desc = Column(String(255), nullable=False)
    cat_code = Column(String(50))

    def __repr__(self):
        return f"<TBCategory(cat_id={self.cat_id}, cat_desc='{self.cat_desc}')>"

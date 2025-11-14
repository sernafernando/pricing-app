"""
Modelo para tbSubCategory - Subcategorías
"""
from sqlalchemy import Column, Integer, String
from app.core.database import Base


class TBSubCategory(Base):
    """Tabla de subcategorías del ERP"""
    __tablename__ = "tb_subcategory"

    comp_id = Column(Integer, primary_key=True)
    cat_id = Column(Integer, primary_key=True)
    subcat_id = Column(Integer, primary_key=True)
    subcat_desc = Column(String(255), nullable=False)
    subcat_code = Column(String(50))

    def __repr__(self):
        return f"<TBSubCategory(subcat_id={self.subcat_id}, subcat_desc='{self.subcat_desc}')>"

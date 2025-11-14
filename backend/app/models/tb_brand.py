"""
Modelo para tbBrand - Marcas
"""
from sqlalchemy import Column, Integer, String
from app.core.database import Base


class TBBrand(Base):
    """Tabla de marcas del ERP"""
    __tablename__ = "tb_brand"

    comp_id = Column(Integer, primary_key=True)
    brand_id = Column(Integer, primary_key=True)
    bra_id = Column(Integer)
    brand_desc = Column(String(255), nullable=False)

    def __repr__(self):
        return f"<TBBrand(brand_id={self.brand_id}, brand_desc='{self.brand_desc}')>"

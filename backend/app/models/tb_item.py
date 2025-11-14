"""
Modelo para tbItem - Items/Productos
"""
from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime
from app.core.database import Base


class TBItem(Base):
    """Tabla principal de items del ERP"""
    __tablename__ = "tb_item"

    comp_id = Column(Integer, primary_key=True)
    item_id = Column(Integer, primary_key=True, index=True)
    item_code = Column(String(100), nullable=False)
    item_desc = Column(String(500))
    cat_id = Column(Integer)
    subcat_id = Column(Integer)
    brand_id = Column(Integer)
    item_liquidation = Column(String(50))
    item_active = Column(Boolean, default=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    def __repr__(self):
        return f"<TBItem(item_id={self.item_id}, item_code='{self.item_code}', item_desc='{self.item_desc}')>"

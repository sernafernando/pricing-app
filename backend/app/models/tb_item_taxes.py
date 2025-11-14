"""
Modelo para tbItemTaxes - Impuestos por item
"""
from sqlalchemy import Column, Integer, Numeric
from app.core.database import Base


class TBItemTaxes(Base):
    """Tabla de impuestos por item"""
    __tablename__ = "tb_item_taxes"

    comp_id = Column(Integer, primary_key=True)
    item_id = Column(Integer, primary_key=True, index=True)
    tax_id = Column(Integer, primary_key=True)
    tax_percentage = Column(Numeric(10, 2))

    def __repr__(self):
        return f"<TBItemTaxes(item_id={self.item_id}, tax_id={self.tax_id}, tax_percentage={self.tax_percentage})>"

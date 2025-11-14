"""
Modelo para tbTaxName - Nombres de impuestos
"""
from sqlalchemy import Column, Integer, String
from app.core.database import Base


class TBTaxName(Base):
    """Tabla de nombres de impuestos"""
    __tablename__ = "tb_tax_name"

    comp_id = Column(Integer, primary_key=True)
    tax_id = Column(Integer, primary_key=True)
    tax_name = Column(String(100), nullable=False)
    tax_desc = Column(String(255))

    def __repr__(self):
        return f"<TBTaxName(tax_id={self.tax_id}, tax_name='{self.tax_name}')>"

"""
Modelo para tbTaxName - Nombres de impuestos
"""

from sqlalchemy import Column, Integer, String, Numeric
from app.core.database import Base


class TBTaxName(Base):
    """Tabla de nombres de impuestos"""

    __tablename__ = "tb_tax_name"

    comp_id = Column(Integer, primary_key=True)
    tax_id = Column(Integer, primary_key=True)
    tax_desc = Column(String(255), nullable=False)
    tax_percentage = Column(Numeric(10, 2))

    def __repr__(self):
        return f"<TBTaxName(tax_id={self.tax_id}, tax_desc='{self.tax_desc}')>"

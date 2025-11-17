from sqlalchemy import Column, Integer, String
from app.core.database import Base


class TBSupplier(Base):
    """Modelo para la tabla tb_supplier (proveedores del ERP)"""
    __tablename__ = "tb_supplier"

    comp_id = Column(Integer, primary_key=True)
    supp_id = Column(Integer, primary_key=True)
    supp_name = Column(String(255), nullable=False)
    supp_tax_number = Column(String(50))

    def __repr__(self):
        return f"<TBSupplier(comp_id={self.comp_id}, supp_id={self.supp_id}, supp_name='{self.supp_name}')>"

from sqlalchemy import Column, Integer, BigInteger, Numeric, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class ItemCostListHistory(Base):
    """
    Modelo para tbItemCostListHistory del ERP
    Historial de costos de items por lista de costos
    """
    __tablename__ = "tb_item_cost_list_history"

    # Primary Key
    iclh_id = Column(BigInteger, primary_key=True, index=True)

    # IDs de referencia
    comp_id = Column(Integer, index=True)
    item_id = Column(Integer, index=True)
    coslis_id = Column(Integer, index=True)  # ID de lista de costos (1 = principal)

    # Datos del costo
    iclh_price = Column(Numeric(18, 6))  # Costo sin IVA
    curr_id = Column(Integer)  # ID de moneda (1=ARS, 2=USD, etc.)

    # Fecha de creación del registro
    iclh_cd = Column(DateTime, index=True)

    def __repr__(self):
        return f"<ItemCostListHistory(iclh_id={self.iclh_id}, item_id={self.item_id}, price={self.iclh_price})>"

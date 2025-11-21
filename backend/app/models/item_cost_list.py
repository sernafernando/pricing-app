from sqlalchemy import Column, Integer, BigInteger, Numeric, DateTime
from app.core.database import Base


class ItemCostList(Base):
    """
    Modelo para tbItemCostList del ERP
    Lista de costos actual de items
    """
    __tablename__ = "tb_item_cost_list"

    # Composite Primary Key
    comp_id = Column(Integer, primary_key=True)
    coslis_id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, primary_key=True, index=True)

    # Datos del costo
    coslis_price = Column(Numeric(18, 6))  # Precio/costo actual
    curr_id = Column(Integer)  # ID de moneda (1=ARS, 2=USD, etc.)

    # Campos adicionales opcionales
    coslis_cd = Column(DateTime)  # Fecha de creación/actualización

    def __repr__(self):
        return f"<ItemCostList(comp_id={self.comp_id}, coslis_id={self.coslis_id}, item_id={self.item_id}, price={self.coslis_price})>"

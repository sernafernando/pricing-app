from sqlalchemy import Column, Integer, BigInteger, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class ItemTransactionDetail(Base):
    """
    Modelo para tbItemTransactionDetails del ERP
    Contiene descripciones y detalles adicionales de cada item transaction

    IMPORTANTE: Los nombres de columnas están en minúsculas en PostgreSQL
    """
    __tablename__ = "tb_item_transaction_details"

    # IDs principales
    comp_id = Column(Integer)
    bra_id = Column(Integer)
    ct_transaction = Column(BigInteger, index=True)
    it_transaction = Column(BigInteger, index=True)
    itm_transaction = Column(BigInteger, primary_key=True, index=True)

    # Descripciones
    itm_desc = Column(Text)
    itm_desc1 = Column(Text)
    itm_desc2 = Column(Text)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

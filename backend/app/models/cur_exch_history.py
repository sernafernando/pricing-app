from sqlalchemy import Column, Integer, BigInteger, Numeric, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class CurExchHistory(Base):
    """
    Modelo para tbCurExchHistory del ERP
    Historial de tipos de cambio entre monedas
    """
    __tablename__ = "tb_cur_exch_history"

    # Primary Key
    ceh_id = Column(BigInteger, primary_key=True, index=True)

    # IDs de referencia
    comp_id = Column(Integer)
    curr_id_1 = Column(Integer)  # Moneda origen (ej: 2=USD)
    curr_id_2 = Column(Integer)  # Moneda destino (ej: 1=ARS)

    # Datos del tipo de cambio
    ceh_cd = Column(DateTime, index=True)  # Fecha del tipo de cambio
    ceh_exchange = Column(Numeric(18, 6))  # Tipo de cambio (venta)

    def __repr__(self):
        return f"<CurExchHistory(ceh_id={self.ceh_id}, date={self.ceh_cd}, exchange={self.ceh_exchange})>"

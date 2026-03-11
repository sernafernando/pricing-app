"""
Modelo para la tabla tb_item_transaction_serials
Puente entre seriales (tb_item_serials.is_id) y transacciones de venta
(tb_item_transactions.it_transaction / tb_commercial_transactions.ct_transaction).

GBP usa esta tabla para mostrar TODOS los movimientos de un serial (compra + venta)
en la pantalla "Traza de Artículos por Nº Serie".
"""

from sqlalchemy import Column, BigInteger, Integer, Index
from app.core.database import Base


class TbItemTransactionSerial(Base):
    __tablename__ = "tb_item_transaction_serials"

    # Primary key
    comp_id = Column(Integer, primary_key=True)
    bra_id = Column(Integer, primary_key=True)
    its_id = Column(BigInteger, primary_key=True)

    # Foreign keys — the bridge
    it_transaction = Column(BigInteger, nullable=True, index=True)
    is_id = Column(BigInteger, nullable=True, index=True)
    ct_transaction = Column(BigInteger, nullable=True, index=True)

    # Import tracking (used by GBP internally)
    impData_id = Column("impdata_id", BigInteger, nullable=True)
    import_id = Column(BigInteger, nullable=True)

    __table_args__ = (Index("idx_its_is_id_it_transaction", "is_id", "it_transaction"),)

    def __repr__(self) -> str:
        return (
            f"<TbItemTransactionSerial("
            f"its_id={self.its_id}, is_id={self.is_id}, "
            f"it_transaction={self.it_transaction}, ct_transaction={self.ct_transaction}"
            f")>"
        )

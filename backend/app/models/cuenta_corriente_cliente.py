from sqlalchemy import Column, Integer, String, Numeric, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class CuentaCorrienteCliente(Base):
    """Cuenta corriente de clientes sincronizada desde ERP (export 29)."""

    __tablename__ = "cuentas_corrientes_clientes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bra_id = Column(Integer, nullable=False, index=True)
    id_cliente = Column(Integer, nullable=False, index=True)
    cliente = Column(String(255), nullable=False)
    monto_total = Column(Numeric(15, 2), nullable=False, default=0)
    monto_abonado = Column(Numeric(15, 2), nullable=False, default=0)
    pendiente = Column(Numeric(15, 2), nullable=False, default=0)

    synced_at = Column(DateTime(timezone=True), server_default=func.now())

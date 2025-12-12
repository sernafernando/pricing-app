"""
Modelo para guardar el método de pago seleccionado por operación de Tienda Nube.
Esta tabla es separada de ventas_tienda_nube_metricas para que no se borre al recalcular métricas.
"""
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class MetodoPagoTN(Base):
    """
    Tabla para guardar el método de pago seleccionado por el usuario para cada operación TN.
    Relaciona it_transaction con el método de pago elegido.
    """
    __tablename__ = "metodos_pago_tienda_nube"

    id = Column(Integer, primary_key=True, index=True)

    # Identificador de la transacción (mismo que en ventas_tienda_nube_metricas)
    it_transaction = Column(BigInteger, unique=True, index=True, nullable=False)

    # Método de pago: 'efectivo' o 'tarjeta'
    metodo_pago = Column(String(20), nullable=False, default='efectivo')

    # Auditoría
    usuario_id = Column(Integer, ForeignKey('usuarios.id'))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    usuario = relationship("Usuario")

    def __repr__(self):
        return f"<MetodoPagoTN(it_transaction={self.it_transaction}, metodo={self.metodo_pago})>"

from sqlalchemy import Column, Integer, Numeric, Date, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class PricingConstants(Base):
    __tablename__ = "pricing_constants"

    id = Column(Integer, primary_key=True, index=True)
    monto_tier1 = Column(Numeric(12, 2), nullable=False, default=15000)
    monto_tier2 = Column(Numeric(12, 2), nullable=False, default=24000)
    monto_tier3 = Column(Numeric(12, 2), nullable=False, default=33000)
    comision_tier1 = Column(Numeric(12, 2), nullable=False, default=1095)
    comision_tier2 = Column(Numeric(12, 2), nullable=False, default=2190)
    comision_tier3 = Column(Numeric(12, 2), nullable=False, default=2628)
    varios_porcentaje = Column(Numeric(5, 2), nullable=False, default=6.5)
    grupo_comision_default = Column(Integer, nullable=False, default=1)
    markup_adicional_cuotas = Column(Numeric(5, 2), nullable=False, default=4.0)
    fecha_desde = Column(Date, nullable=False)
    fecha_hasta = Column(Date)
    fecha_creacion = Column(DateTime, default=func.now())
    creado_por = Column(Integer, ForeignKey('usuarios.id'))

    usuario = relationship("Usuario")

    __table_args__ = (
        CheckConstraint('fecha_hasta IS NULL OR fecha_hasta >= fecha_desde', name='chk_fecha_hasta'),
    )

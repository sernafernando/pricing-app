from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class OffsetMigracionPendiente(Base):
    """A legacy offset the sell in / sell out migration did not carry over, kept for the owner's review
    (`app.scripts.migrar_offsets_a_sell_out --apply`, sell-in-sell-out T22a). A copy of the offset's own detail plus
    the reason: no foreign key, so the row outlives the offset (migration 20261206_offsets_migracion_pendientes)."""

    __tablename__ = "offsets_migracion_pendientes"

    id = Column(Integer, primary_key=True)
    offset_id = Column(Integer, nullable=False, unique=True)
    tipo_offset = Column(String(20))
    descripcion = Column(String(255))
    marca = Column(String(100))
    categoria = Column(String(100))
    subcategoria_id = Column(Integer)
    item_id = Column(Integer)
    grupo_id = Column(Integer)
    monto = Column(Float)
    porcentaje = Column(Float)
    moneda = Column(String(3))
    tipo_cambio = Column(Float)
    fecha_desde = Column(Date)
    fecha_hasta = Column(Date)
    max_unidades = Column(Integer)
    max_monto_usd = Column(Float)
    aplica_ml = Column(Boolean)
    aplica_fuera = Column(Boolean)
    aplica_tienda_nube = Column(Boolean)
    usuario_id = Column(Integer)
    motivo = Column(Text, nullable=False)
    avisos = Column(Text)
    registrado_en = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

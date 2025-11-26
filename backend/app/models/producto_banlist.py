from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class ProductoBanlist(Base):
    __tablename__ = "producto_banlist"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, unique=True, index=True, nullable=True)
    ean = Column(String(50), unique=True, index=True, nullable=True)
    motivo = Column(String(500), nullable=True)
    activo = Column(Boolean, default=True, nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())
    fecha_modificacion = Column(DateTime(timezone=True), onupdate=func.now())

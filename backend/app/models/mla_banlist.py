from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class MLABanlist(Base):
    __tablename__ = "mla_banlist"

    id = Column(Integer, primary_key=True, index=True)
    mla = Column(String(50), unique=True, index=True, nullable=False)  # Formato: MLA123456789
    motivo = Column(String(255), nullable=True)

    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())

    activo = Column(Boolean, default=True)

    # Relación con usuario
    usuario = relationship("Usuario", backref="mlas_baneados")

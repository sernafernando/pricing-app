from sqlalchemy import Column, Integer, String, DateTime, Index
from sqlalchemy.sql import func
from app.core.database import Base


class CodigoPostalCordon(Base):
    """
    Mapeo de código postal a cordón de envío.
    Los cordones posibles son: CABA, Cordón 1, Cordón 2, Cordón 3.
    La localidad se popula automáticamente desde los datos de envío de ML.
    """

    __tablename__ = "cp_cordones"

    id = Column(Integer, primary_key=True, index=True)
    codigo_postal = Column(String(10), unique=True, nullable=False, index=True)
    localidad = Column(String(255), nullable=True)
    cordon = Column(String(50), nullable=True)  # CABA, Cordón 1, Cordón 2, Cordón 3, o NULL (Sin Asignar)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_cp_cordones_cordon", "cordon"),)

    def __repr__(self) -> str:
        return f"<CodigoPostalCordon(cp={self.codigo_postal}, cordon={self.cordon})>"

from sqlalchemy import Column, String, Numeric, DateTime
from sqlalchemy.sql import func
from app.core.database import Base
import hashlib


class GeocodingCache(Base):
    """
    Cache de direcciones geocodificadas.
    Evita llamadas repetidas a APIs de geocoding.
    """
    __tablename__ = "geocoding_cache"

    direccion_hash = Column(String(32), primary_key=True)  # MD5 hash
    direccion_normalizada = Column(String(500), nullable=False, index=True)
    latitud = Column(Numeric(10, 8), nullable=False)
    longitud = Column(Numeric(11, 8), nullable=False)
    provider = Column(String(20), nullable=True)  # 'google', 'nominatim', 'datosabiertos'
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    @staticmethod
    def hash_direccion(direccion: str) -> str:
        """
        Genera un hash MD5 de una dirección normalizada.
        """
        normalizada = direccion.strip().lower()
        return hashlib.md5(normalizada.encode('utf-8')).hexdigest()

    def __repr__(self):
        return f"<GeocodingCache(hash='{self.direccion_hash[:8]}...', direccion='{self.direccion_normalizada[:50]}...')>"

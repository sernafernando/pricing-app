"""
Historial de lecturas de clima desde OpenWeatherMap.

Cada consulta exitosa a la API se persiste aquí para poder cruzar
con envíos despachados y saber qué clima había al momento del despacho.
"""

from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime, Index
from sqlalchemy.sql import func

from app.core.database import Base


class WeatherHistory(Base):
    """Registro histórico de lecturas de clima."""

    __tablename__ = "weather_history"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Datos de clima
    temp = Column(Float, nullable=False)
    feels_like = Column(Float, nullable=False)
    temp_min = Column(Float, nullable=False)
    temp_max = Column(Float, nullable=False)
    humidity = Column(Integer, nullable=False)
    description = Column(String(100), nullable=False)
    icon = Column(String(10), nullable=False)
    wind_speed = Column(Float, nullable=False)
    rain_1h = Column(Float, nullable=False, server_default="0")
    is_rainy = Column(Boolean, nullable=False, server_default="false")

    # Ubicación
    city = Column(String(100), nullable=False)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)

    # Timestamp de OpenWeather (unix -> datetime) y nuestro created_at
    weather_dt = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_weather_history_created_at", "created_at"),
        Index("idx_weather_history_is_rainy", "is_rainy"),
    )

    def __repr__(self) -> str:
        return f"<WeatherHistory(id={self.id}, temp={self.temp}, desc='{self.description}', at={self.created_at})>"

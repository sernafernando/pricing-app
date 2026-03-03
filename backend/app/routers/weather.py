"""
Router para datos de clima (OpenWeatherMap).

Expone un endpoint GET /api/weather/current que devuelve el clima actual.
Usa cache de 15 minutos en el service para no exceder el free tier.
Cualquier usuario autenticado puede consultar.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.core.deps import get_current_user
from app.models.usuario import Usuario
from app.services.weather_service import get_current_weather

router = APIRouter(prefix="/weather", tags=["Weather"])


class WeatherResponse(BaseModel):
    """Respuesta del endpoint de clima."""

    temp: float
    feels_like: float
    temp_min: float
    temp_max: float
    humidity: int
    description: str
    icon: str
    icon_url: str
    wind_speed: float
    city: str
    rain_1h: float
    is_rainy: bool

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "temp": 22.5,
                "feels_like": 21.0,
                "temp_min": 19.0,
                "temp_max": 25.0,
                "humidity": 65,
                "description": "cielo claro",
                "icon": "01d",
                "icon_url": "https://openweathermap.org/img/wn/01d@2x.png",
                "wind_speed": 3.5,
                "city": "Buenos Aires",
                "rain_1h": 0.0,
                "is_rainy": False,
            }
        }
    )


@router.get("/current", response_model=WeatherResponse)
async def obtener_clima_actual(
    current_user: Usuario = Depends(get_current_user),
) -> WeatherResponse:
    """
    Obtiene el clima actual de la ciudad configurada (default: Buenos Aires).

    El resultado se cachea 15 minutos en memoria del servidor para
    minimizar las llamadas a OpenWeatherMap (free tier: 1000/día).

    Cualquier usuario autenticado puede consultar este endpoint.
    """
    data = await get_current_weather()

    if data is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de clima no disponible. Verificar OPENWEATHER_API_KEY.",
        )

    return WeatherResponse(**data)

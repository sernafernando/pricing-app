"""
Servicio de clima usando OpenWeatherMap API.

Cache en memoria con TTL de 15 minutos para minimizar llamadas a la API.
Free tier: 1000 calls/día → con cache de 15min = ~96 calls/día (sobra).

El dato se expone en el TopBar del frontend para depósito, y a futuro
se puede persistir en BD para cruzar con envíos (pronóstico de lluvia).
"""

import time
import logging
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# OpenWeatherMap Current Weather API
# Docs: https://openweathermap.org/current
OPENWEATHER_API_URL = "https://api.openweathermap.org/data/2.5/weather"

# Cache en memoria: {data, timestamp}
_weather_cache: dict = {}
CACHE_TTL_SECONDS = 900  # 15 minutos


def _is_cache_valid() -> bool:
    """Verifica si el cache tiene datos vigentes."""
    if not _weather_cache:
        return False
    elapsed = time.time() - _weather_cache.get("timestamp", 0)
    return elapsed < CACHE_TTL_SECONDS


def _get_cached() -> Optional[dict]:
    """Retorna datos cacheados si son válidos."""
    if _is_cache_valid():
        return _weather_cache.get("data")
    return None


def _set_cache(data: dict) -> None:
    """Guarda datos en cache con timestamp."""
    _weather_cache["data"] = data
    _weather_cache["timestamp"] = time.time()


async def get_current_weather() -> Optional[dict]:
    """
    Obtiene el clima actual de la ciudad configurada.

    Returns:
        Dict con datos de clima o None si hay error.
        Estructura:
        {
            "temp": 22.5,          # Temperatura en °C
            "feels_like": 21.0,    # Sensación térmica en °C
            "temp_min": 19.0,      # Mínima del día en °C
            "temp_max": 25.0,      # Máxima del día en °C
            "humidity": 65,        # Humedad %
            "description": "cielo claro",
            "icon": "01d",         # Código de ícono OpenWeather
            "icon_url": "https://openweathermap.org/img/wn/01d@2x.png",
            "wind_speed": 3.5,     # Viento en m/s
            "city": "Buenos Aires",
            "rain_1h": 0.0,        # Lluvia última hora en mm (si hay)
            "is_rainy": False,     # Flag simple para lógica de envíos
        }
    """
    # Verificar cache primero
    cached = _get_cached()
    if cached:
        logger.debug("Weather cache HIT")
        return cached

    # Verificar API key
    if not settings.OPENWEATHER_API_KEY:
        logger.warning("OPENWEATHER_API_KEY no configurada — clima no disponible")
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                OPENWEATHER_API_URL,
                params={
                    "lat": settings.OPENWEATHER_LAT,
                    "lon": settings.OPENWEATHER_LON,
                    "appid": settings.OPENWEATHER_API_KEY,
                    "units": "metric",
                    "lang": "es",
                },
            )
            response.raise_for_status()
            raw = response.json()

        # Extraer datos relevantes
        main = raw.get("main", {})
        weather_info = raw.get("weather", [{}])[0]
        wind = raw.get("wind", {})
        rain = raw.get("rain", {})

        icon_code = weather_info.get("icon", "01d")

        data = {
            "temp": round(main.get("temp", 0), 1),
            "feels_like": round(main.get("feels_like", 0), 1),
            "temp_min": round(main.get("temp_min", 0), 1),
            "temp_max": round(main.get("temp_max", 0), 1),
            "humidity": main.get("humidity", 0),
            "description": weather_info.get("description", ""),
            "icon": icon_code,
            "icon_url": f"https://openweathermap.org/img/wn/{icon_code}@2x.png",
            "wind_speed": round(wind.get("speed", 0), 1),
            "city": raw.get("name", "Buenos Aires"),
            "rain_1h": rain.get("1h", 0.0),
            "is_rainy": bool(rain) or "rain" in weather_info.get("main", "").lower(),
        }

        # Guardar en cache
        _set_cache(data)
        logger.info(
            "Weather updated: %s — %.1f°C, %s",
            data["city"],
            data["temp"],
            data["description"],
        )

        return data

    except httpx.HTTPStatusError as e:
        logger.error("OpenWeather HTTP error: %s - %s", e.response.status_code, e.response.text)
        return None
    except httpx.RequestError as e:
        logger.error("OpenWeather request error: %s", e)
        return None
    except (ValueError, KeyError, IndexError) as e:
        logger.error("OpenWeather parse error: %s", e)
        return None

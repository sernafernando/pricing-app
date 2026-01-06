"""
Servicio de geocoding para convertir direcciones a coordenadas (lat, lng).
Usa Mapbox Geocoding API con cache para evitar consultas repetidas.
"""
import asyncio
import httpx
import logging
from typing import Optional, Tuple, Dict, List
from urllib.parse import quote

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.models.geocoding_cache import GeocodingCache
from app.core.config import settings

logger = logging.getLogger(__name__)

# URL de Mapbox Geocoding API v5
# Docs: https://docs.mapbox.com/api/search/geocoding/
MAPBOX_GEOCODING_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places"


async def geocode_address(
    direccion: str,
    ciudad: str = "Buenos Aires",
    pais: str = "Argentina",
    db: Optional[Session] = None,
    usar_cache: bool = True
) -> Optional[Tuple[float, float]]:
    """
    Geocodifica una dirección y devuelve (latitud, longitud).
    Usa Mapbox Geocoding API v5.
    
    Args:
        direccion: Dirección completa (calle, número, etc)
        ciudad: Ciudad (default Buenos Aires)
        pais: País (default Argentina)
        db: Sesión de BD para cache (opcional)
        usar_cache: Si True, busca en cache antes de consultar API
        
    Returns:
        Tupla (latitud, longitud) o None si no se encuentra
    """
    # Verificar que existe el token de Mapbox
    if not settings.MAPBOX_ACCESS_TOKEN:
        logger.error("MAPBOX_ACCESS_TOKEN no configurado en .env")
        return None
    
    # Construir query completa
    query = f"{direccion}, {ciudad}, {pais}"
    
    # Verificar cache si está disponible
    if usar_cache and db:
        cache_entry = get_from_cache(query, db)
        if cache_entry:
            logger.info(f"Geocoding cache HIT: {query[:50]}...")
            return (cache_entry.latitud, cache_entry.longitud)
    
    # Consultar Mapbox Geocoding API
    try:
        logger.info(f"Geocoding API call (Mapbox): {query[:50]}...")
        
        # URL encode del query
        query_encoded = quote(query)
        
        # Construir URL de Mapbox
        # Formato: /geocoding/v5/mapbox.places/{search_text}.json
        url = f"{MAPBOX_GEOCODING_URL}/{query_encoded}.json"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                params={
                    "access_token": settings.MAPBOX_ACCESS_TOKEN,
                    "limit": 1,  # Solo el mejor resultado
                    "country": "ar",  # Restringir a Argentina (código ISO 3166-1)
                    "language": "es"  # Respuesta en español
                }
            )
            response.raise_for_status()
            data = response.json()
            
            # Verificar que hay resultados
            if not data.get("features") or len(data["features"]) == 0:
                logger.warning(f"Geocoding no encontró resultados: {query[:50]}")
                return None
            
            # Obtener primera coincidencia
            feature = data["features"][0]
            
            # Mapbox devuelve coordenadas en formato [longitud, latitud]
            coordinates = feature["geometry"]["coordinates"]
            longitud = float(coordinates[0])
            latitud = float(coordinates[1])
            
            # Guardar en cache si está disponible
            if usar_cache and db:
                save_to_cache(query, latitud, longitud, db)
            
            logger.info(f"Geocoding SUCCESS: {query[:50]} -> ({latitud}, {longitud})")
            return (latitud, longitud)
            
    except httpx.HTTPStatusError as e:
        logger.error(f"Geocoding HTTP error: {e.response.status_code} - {e.response.text}")
        return None
    except httpx.RequestError as e:
        logger.error(f"Geocoding request error: {e}")
        return None
    except (ValueError, KeyError, IndexError) as e:
        logger.error(f"Geocoding parse error: {e}")
        return None


def get_from_cache(direccion: str, db: Session) -> Optional[GeocodingCache]:
    """
    Busca una dirección en el cache de geocoding.
    
    Args:
        direccion: Dirección a buscar
        db: Sesión de BD
        
    Returns:
        GeocodingCache o None si no existe
    """
    hash_dir = GeocodingCache.hash_direccion(direccion)
    return db.query(GeocodingCache).filter(
        GeocodingCache.direccion_hash == hash_dir
    ).first()


def save_to_cache(direccion: str, latitud: float, longitud: float, db: Session) -> None:
    """
    Guarda una geocodificación en cache.
    
    Args:
        direccion: Dirección geocodificada
        latitud: Latitud resultante
        longitud: Longitud resultante
        db: Sesión de BD
    """
    try:
        hash_dir = GeocodingCache.hash_direccion(direccion)
        
        # Verificar si ya existe
        existing = db.query(GeocodingCache).filter(
            GeocodingCache.direccion_hash == hash_dir
        ).first()
        
        if existing:
            # Actualizar
            existing.latitud = latitud
            existing.longitud = longitud
        else:
            # Crear nuevo
            cache_entry = GeocodingCache(
                direccion_normalizada=direccion[:500],  # Limitar a 500 chars
                direccion_hash=hash_dir,
                latitud=latitud,
                longitud=longitud
            )
            db.add(cache_entry)
        
        db.commit()
        logger.info(f"Geocoding guardado en cache: {direccion[:50]}")
        
    except SQLAlchemyError as e:
        logger.error(f"Error de BD guardando geocoding cache: {e}")
        db.rollback()
    except Exception as e:
        logger.error(f"Error inesperado guardando geocoding cache: {e}")
        db.rollback()


async def geocode_batch(
    direcciones: List[str],
    db: Session,
    delay_ms: int = 100
) -> Dict[str, Optional[Tuple[float, float]]]:
    """
    Geocodifica múltiples direcciones con rate limiting.
    
    Args:
        direcciones: Lista de direcciones a geocodificar
        db: Sesión de BD para cache
        delay_ms: Delay entre requests en milisegundos (default 100ms)
                  Mapbox permite hasta 600 req/min = 10 req/seg = 100ms entre requests
        
    Returns:
        Diccionario {direccion: (lat, lng) o None}
    """
    
    resultados = {}
    
    for direccion in direcciones:
        coords = await geocode_address(direccion, db=db)
        resultados[direccion] = coords
        
        # Rate limiting: Mapbox permite 600 req/min (10 req/seg)
        # Con 100ms de delay = 10 requests/segundo (dentro del límite)
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)
    
    return resultados

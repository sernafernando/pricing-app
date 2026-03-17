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


def _es_cp_caba(zip_code: Optional[str]) -> bool:
    """
    Detecta si un código postal argentino pertenece a CABA.

    CABA usa CPs de 4 dígitos que empiezan con '1' (1000-1499),
    o CPA alfanumérico que empieza con 'C' (ej. C1029AAO).
    """
    if not zip_code:
        return False
    cp = zip_code.strip()
    # CPA alfanumérico: C1029AAO → empieza con C
    if cp.upper().startswith("C") and len(cp) >= 5:
        return True
    # CP numérico de 4 dígitos: 1000-1499
    if cp.isdigit() and len(cp) == 4 and cp.startswith("1") and int(cp) < 1500:
        return True
    return False


def _extract_postcode_from_context(feature: dict) -> Optional[str]:
    """
    Extrae el código postal del context array de un resultado Mapbox.
    El context es un array de objetos con ids como 'postcode.123456'.
    """
    # Primero buscar en context
    for ctx in feature.get("context", []):
        ctx_id = ctx.get("id", "")
        if ctx_id.startswith("postcode"):
            return ctx.get("text", "").strip()
    # Si el feature mismo es un postcode
    for pt in feature.get("place_type", []):
        if pt == "postcode":
            return feature.get("text", "").strip()
    return None


def _postcodes_compatible(expected: str, actual: str) -> bool:
    """
    Compara dos códigos postales argentinos con tolerancia.
    CPA alfanumérico (C1429AAA) → extraer parte numérica (1429).
    CP numérico → comparar los primeros 2 dígitos (misma zona).

    Ejemplos:
      '1429' vs '1429' → True
      'C1429AAA' vs '1429' → True
      '1429' vs '1430' → True (misma zona, primeros 2 dígitos iguales)
      '1429' vs '2000' → False (Rosario vs CABA)
    """

    def _normalize_cp(cp: str) -> str:
        cp = cp.strip().upper()
        # CPA alfanumérico: C1429AAA → extraer dígitos
        digits = "".join(c for c in cp if c.isdigit())
        return digits

    norm_expected = _normalize_cp(expected)
    norm_actual = _normalize_cp(actual)

    if not norm_expected or not norm_actual:
        # No podemos comparar, dejar pasar
        return True

    # Comparación exacta
    if norm_expected == norm_actual:
        return True

    # Comparar primeros 2 dígitos (misma zona geográfica)
    # 10xx-14xx = CABA/GBA, 20xx = Rosario, 50xx = Córdoba, etc.
    if len(norm_expected) >= 2 and len(norm_actual) >= 2:
        return norm_expected[:2] == norm_actual[:2]

    return True


async def geocode_address(
    direccion: str,
    ciudad: str = "Buenos Aires",
    pais: str = "Argentina",
    zip_code: Optional[str] = None,
    db: Optional[Session] = None,
    usar_cache: bool = True,
) -> Optional[Tuple[float, float]]:
    """
    Geocodifica una dirección y devuelve (latitud, longitud).
    Usa Mapbox Geocoding API v5.

    Args:
        direccion: Dirección completa (calle, número, etc)
        ciudad: Ciudad (default Buenos Aires)
        pais: País (default Argentina)
        zip_code: Código postal (opcional, mejora precisión)
        db: Sesión de BD para cache (opcional)
        usar_cache: Si True, busca en cache antes de consultar API

    Returns:
        Tupla (latitud, longitud) o None si no se encuentra
    """
    # Verificar que existe el token de Mapbox
    if not settings.MAPBOX_ACCESS_TOKEN:
        logger.error("MAPBOX_ACCESS_TOKEN no configurado en .env")
        return None

    # Si el CP indica CABA pero la ciudad es un barrio (no "Buenos Aires"),
    # corregir para que Mapbox no se confunda con nombres de barrio
    if _es_cp_caba(zip_code) and ciudad.lower() not in (
        "buenos aires",
        "caba",
        "capital federal",
        "ciudad autónoma de buenos aires",
        "ciudad autonoma de buenos aires",
    ):
        logger.info(
            "CP %s indica CABA, overriding ciudad '%s' → 'Buenos Aires'",
            zip_code,
            ciudad,
        )
        ciudad = "Buenos Aires"

    # Construir query completa — incluir CP si está disponible
    if zip_code:
        query = f"{direccion}, {zip_code} {ciudad}, {pais}"
    else:
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

        # Bias results toward Buenos Aires area for better accuracy
        params = {
            "access_token": settings.MAPBOX_ACCESS_TOKEN,
            "limit": 1,  # Solo el mejor resultado
            "country": "ar",  # Restringir a Argentina (código ISO 3166-1)
            "language": "es",  # Respuesta en español
            "proximity": "-58.3816,-34.6037",  # Bias hacia Buenos Aires
        }

        # If we have a zip code, prefer address-level results
        if zip_code:
            params["types"] = "address,poi,neighborhood,locality"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            # Verificar que hay resultados
            if not data.get("features") or len(data["features"]) == 0:
                logger.warning(f"Geocoding no encontró resultados: {query[:50]}")
                return None

            # Obtener primera coincidencia
            feature = data["features"][0]

            # ── Validación de confianza ──────────────────────────────
            # Mapbox relevance: 0-1 (1 = match perfecto)
            relevance = feature.get("relevance", 0)
            place_type = feature.get("place_type", [])

            # Rechazar resultados de baja relevancia (dirección mal escrita)
            if relevance < 0.6:
                logger.warning(
                    "Geocoding REJECTED (low relevance %.2f): %s → %s",
                    relevance,
                    query[:60],
                    feature.get("place_name", "?"),
                )
                return None

            # Rechazar si Mapbox solo matcheó a nivel de ciudad/región/país
            # (significa que no encontró la dirección, solo la ciudad)
            coarse_types = {"place", "region", "country", "district"}
            if place_type and set(place_type).issubset(coarse_types):
                logger.warning(
                    "Geocoding REJECTED (coarse place_type %s): %s → %s",
                    place_type,
                    query[:60],
                    feature.get("place_name", "?"),
                )
                return None

            # Si tenemos CP, validar que el resultado esté en la misma zona postal
            # Esto previene "calle X en CABA" → match en Rosario
            if zip_code:
                result_postcode = _extract_postcode_from_context(feature)
                if result_postcode and not _postcodes_compatible(zip_code, result_postcode):
                    logger.warning(
                        "Geocoding REJECTED (postcode mismatch: expected %s, got %s): %s",
                        zip_code,
                        result_postcode,
                        query[:60],
                    )
                    return None

            # ── Resultado válido ─────────────────────────────────────
            # Mapbox devuelve coordenadas en formato [longitud, latitud]
            coordinates = feature["geometry"]["coordinates"]
            longitud = float(coordinates[0])
            latitud = float(coordinates[1])

            # Guardar en cache si está disponible
            if usar_cache and db:
                save_to_cache(query, latitud, longitud, db)

            logger.info(
                "Geocoding SUCCESS (relevance=%.2f, type=%s): %s -> (%.6f, %.6f)",
                relevance,
                place_type,
                query[:50],
                latitud,
                longitud,
            )
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
    return db.query(GeocodingCache).filter(GeocodingCache.direccion_hash == hash_dir).first()


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
        existing = db.query(GeocodingCache).filter(GeocodingCache.direccion_hash == hash_dir).first()

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
                longitud=longitud,
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
    direcciones: List[str], db: Session, delay_ms: int = 100
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

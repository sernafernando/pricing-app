"""
Servicio para interactuar con ML Webhook API.

API URL: https://ml-webhook.gaussonline.com.ar/api/ml/render
Recursos:
- GET /shipments/{shipping_id} - Datos completos de envío con lat/lng y estados

Ventajas:
- Geocoding 100% preciso (ML ya lo hizo)
- Estados en tiempo real
- 0 costo (API interna)
"""

import httpx
import logging
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

ML_WEBHOOK_BASE_URL = "https://ml-webhook.gaussonline.com.ar/api/ml/render"


async def fetch_shipment_data(shipping_id: str) -> Optional[Dict[str, Any]]:
    """
    Obtiene datos completos de un envío desde ML Webhook API.

    Args:
        shipping_id: ID del envío de MercadoLibre (mlshippingid)

    Returns:
        Dict con datos del envío o None si falla

    Ejemplo response:
    {
        "id": 46186874958,
        "status": "shipped",
        "substatus": "out_for_delivery",
        "receiver_address": {
            "latitude": -32.994693,
            "longitude": -68.877665,
            "street_name": "Pueyrredón",
            "street_number": "1210",
            "city": {"name": "Carbometal"},
            "state": {"name": "Mendoza"}
        },
        ...
    }
    """
    if not shipping_id:
        logger.warning("shipping_id vacío")
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                ML_WEBHOOK_BASE_URL, params={"resource": f"/shipments/{shipping_id}", "format": "json"}
            )
            response.raise_for_status()
            data = response.json()

            logger.info(f"✅ Shipment {shipping_id} obtenido correctamente")
            return data

    except httpx.HTTPStatusError as e:
        logger.error(f"ML Webhook HTTP error para {shipping_id}: {e.response.status_code}")
        return None
    except httpx.RequestError as e:
        logger.error(f"ML Webhook request error para {shipping_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado obteniendo shipment {shipping_id}: {e}")
        return None


def extraer_coordenadas(data: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """
    Extrae latitud y longitud de respuesta de ML Webhook.

    Args:
        data: Respuesta JSON de ML Webhook

    Returns:
        Tupla (latitud, longitud) o (None, None) si no están disponibles
    """
    try:
        receiver = data.get("receiver_address", {})
        lat = receiver.get("latitude")
        lng = receiver.get("longitude")

        if lat is not None and lng is not None:
            # Validar que sean números válidos
            lat_float = float(lat)
            lng_float = float(lng)

            # Validar rangos razonables (Argentina aprox)
            if -55 <= lat_float <= -20 and -75 <= lng_float <= -50:
                return (lat_float, lng_float)
            else:
                logger.warning(f"Coordenadas fuera de rango Argentina: lat={lat_float}, lng={lng_float}")
                return (None, None)

        return (None, None)

    except (ValueError, TypeError) as e:
        logger.error(f"Error parseando coordenadas: {e}")
        return (None, None)


def extraer_direccion_completa(data: Dict[str, Any]) -> Optional[str]:
    """
    Extrae dirección completa formateada de respuesta ML Webhook.

    Args:
        data: Respuesta JSON de ML Webhook

    Returns:
        String con dirección completa o None

    Ejemplo: "Pueyrredón 1210, Carbometal, Mendoza"
    """
    try:
        receiver = data.get("receiver_address", {})

        street_name = receiver.get("street_name", "")
        street_number = receiver.get("street_number", "")
        city_name = receiver.get("city", {}).get("name", "")
        state_name = receiver.get("state", {}).get("name", "")

        # Construir dirección
        parts = []

        if street_name and street_number:
            parts.append(f"{street_name} {street_number}")
        elif street_name:
            parts.append(street_name)

        if city_name:
            parts.append(city_name)

        if state_name:
            parts.append(state_name)

        if parts:
            return ", ".join(parts)

        return None

    except Exception as e:
        logger.error(f"Error extrayendo dirección: {e}")
        return None


def extraer_estado(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extrae información de estado del envío.

    Args:
        data: Respuesta JSON de ML Webhook

    Returns:
        Dict con información de estado

    Ejemplo:
    {
        'status': 'shipped',
        'substatus': 'out_for_delivery',
        'tracking_number': '360002849715830',
        'date_shipped': '2026-01-05T01:45:10.794-04:00',
        'date_delivered': None
    }
    """
    try:
        status_history = data.get("status_history", {})

        return {
            "status": data.get("status"),
            "substatus": data.get("substatus"),
            "tracking_number": data.get("tracking_number"),
            "date_shipped": status_history.get("date_shipped"),
            "date_delivered": status_history.get("date_delivered"),
            "date_ready_to_ship": status_history.get("date_ready_to_ship"),
            "last_updated": data.get("last_updated"),
        }
    except Exception as e:
        logger.error(f"Error extrayendo estado: {e}")
        return {}


def extraer_comentario_direccion(data: Dict[str, Any]) -> Optional[str]:
    """
    Extrae el comentario del comprador sobre la dirección.

    Args:
        data: Respuesta JSON de ML Webhook

    Returns:
        String con comentario o None

    Ejemplo: "Referencia: Puerta negra Entre: Rondeau y Avenida Roca"
    """
    try:
        receiver = data.get("receiver_address", {})
        comment = receiver.get("comment")

        if comment and isinstance(comment, str):
            stripped = comment.strip()
            return stripped if stripped else None

        return None

    except Exception as e:
        logger.error(f"Error extrayendo comentario dirección: {e}")
        return None


def extraer_es_outlet(data: Dict[str, Any]) -> bool:
    """
    Detecta si algún item del envío contiene 'outlet' en el título.

    Args:
        data: Respuesta JSON de ML Webhook

    Returns:
        True si al menos un shipping_item tiene 'outlet' en su description
    """
    try:
        items = data.get("shipping_items", [])
        for item in items:
            desc = item.get("description", "")
            if desc and "outlet" in desc.lower():
                return True
        return False
    except Exception as e:
        logger.error(f"Error detectando outlet: {e}")
        return False


async def fetch_shipment_label_zpl(shipping_id: str) -> Dict[str, Any]:
    """
    Obtiene la etiqueta ZPL de un envío desde ML vía el proxy ml-webhook.

    Llama a /shipment_labels?shipment_ids=XXX&response_type=zpl2 a través
    del render endpoint del proxy, con query params embebidos en resource.

    Args:
        shipping_id: ID del envío de MercadoLibre

    Returns:
        Dict con {ok: True, zpl: "^XA..."} o {ok: False, error: "msg", code: "XXX"}
    """
    if not shipping_id:
        return {"ok": False, "error": "shipping_id vacío", "code": "EMPTY_ID"}

    # Embeber query params de ML dentro del resource (el proxy los forwardea)
    resource = f"/shipment_labels?shipment_ids={shipping_id}&response_type=zpl2"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                ML_WEBHOOK_BASE_URL,
                params={"resource": resource, "format": "json"},
            )

            content_type = response.headers.get("content-type", "")

            # Si ML devuelve JSON, puede ser un error o una respuesta con detalle
            if "application/json" in content_type:
                data = response.json()
                # ML devuelve errores con status 400 en JSON
                if "failed_shipments" in data or data.get("status") == 400:
                    causes = data.get("causes", [])
                    message = data.get("message", "Error desconocido de ML")
                    return {"ok": False, "error": message, "code": causes[0] if causes else "ML_ERROR"}
                # Puede ser JSON exitoso (raro para ZPL, pero por si acaso)
                return {"ok": False, "error": "Respuesta inesperada de ML (JSON)", "code": "UNEXPECTED_JSON"}

            # Si no es JSON, debería ser el ZPL como texto plano
            zpl_text = response.text
            if zpl_text and "^XA" in zpl_text:
                logger.info(f"✅ Etiqueta ZPL obtenida para {shipping_id} ({len(zpl_text)} chars)")
                return {"ok": True, "zpl": zpl_text}

            # Respuesta no reconocida
            logger.warning(f"Respuesta no reconocida para etiqueta {shipping_id}: {content_type}")
            return {"ok": False, "error": "Respuesta no reconocida de ML", "code": "UNKNOWN_RESPONSE"}

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error obteniendo etiqueta {shipping_id}: {e.response.status_code}")
        return {"ok": False, "error": f"Error HTTP {e.response.status_code}", "code": "HTTP_ERROR"}
    except httpx.RequestError as e:
        logger.error(f"Request error obteniendo etiqueta {shipping_id}: {e}")
        return {"ok": False, "error": "Error de conexión con ML webhook", "code": "CONNECTION_ERROR"}
    except Exception as e:
        logger.error(f"Error inesperado obteniendo etiqueta {shipping_id}: {e}")
        return {"ok": False, "error": str(e), "code": "UNEXPECTED_ERROR"}


def extraer_tipo_geocoding(data: Dict[str, Any]) -> str:
    """
    Extrae el tipo de geocoding usado por ML.

    Args:
        data: Respuesta JSON de ML Webhook

    Returns:
        String con tipo: 'ROOFTOP' (alta precisión) o 'APPROXIMATE'
    """
    try:
        receiver = data.get("receiver_address", {})
        return receiver.get("geolocation_type", "UNKNOWN")
    except Exception:
        return "UNKNOWN"

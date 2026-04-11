"""
Schemas y helpers compartidos para turbo_routing.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
import pytz
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings

logger = logging.getLogger(__name__)

# Timezone de Argentina
ARGENTINA_TZ = pytz.timezone("America/Argentina/Buenos_Aires")

# Cache en memoria para scriptEnvios (evitar martillar el ERP)
_envios_cache: Dict[str, Any] = {
    "data": [],
    "timestamp": None,
    "ttl_seconds": 300,  # 5 minutos
}


def convert_to_argentina_tz(utc_dt: Optional[datetime]) -> Optional[datetime]:
    """Convierte un datetime UTC a timezone de Argentina"""
    if not utc_dt:
        return None
    if utc_dt.tzinfo is None:
        utc_dt = pytz.utc.localize(utc_dt)
    return utc_dt.astimezone(ARGENTINA_TZ)


async def obtener_envios_desde_erp(dias_atras: int = 30, usar_cache: bool = True) -> List[Dict[str, Any]]:
    """
    Obtiene envíos desde el ERP usando scriptEnvios CON CACHE para performance.

    Args:
        dias_atras: Cantidad de días hacia atrás para consultar (default 30)
        usar_cache: Si True, usa cache de 5 minutos para evitar martillar el ERP

    Returns:
        Lista de envíos con estructura:
        {
            "Número de Envío": int,
            "Dirección de Entrega": str,
            "Cordón": str,
            "Costo de envío": float,
            "Monto": float,
            "Usuario": str,
            "Estado": str (ready_to_ship, not_delivered, shipped, delivered, cancelled),
            "Pedido": str
        }
    """
    # Verificar cache
    if usar_cache and _envios_cache["timestamp"]:
        cache_age = (datetime.now(UTC) - _envios_cache["timestamp"]).total_seconds()
        if cache_age < _envios_cache["ttl_seconds"]:
            logger.info(f"Usando cache de scriptEnvios (edad: {cache_age:.1f}s)")
            return _envios_cache["data"]

    try:
        fecha_hasta = datetime.now(UTC).strftime("%Y-%m-%d")
        fecha_desde = (datetime.now(UTC) - timedelta(days=dias_atras)).strftime("%Y-%m-%d")

        logger.info(f"Consultando scriptEnvios (desde={fecha_desde}, hasta={fecha_hasta})")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                settings.GBP_PARSER_URL,
                json={"strScriptLabel": "scriptEnvios", "fromDate": fecha_desde, "toDate": fecha_hasta},
            )
            response.raise_for_status()
            data = response.json()

            # Filtrar error -9
            if data and len(data) == 1 and data[0].get("Column1") == "-9":
                return []

            # Guardar en cache
            if usar_cache:
                _envios_cache["data"] = data
                _envios_cache["timestamp"] = datetime.now(UTC)
                logger.info(f"Cache actualizado con {len(data)} envíos")

            return data

    except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as e:
        logger.error(f"Error al obtener envíos desde ERP: {e}")
        # Si hay cache viejo, usarlo como fallback
        if usar_cache and _envios_cache["data"]:
            logger.warning("Usando cache antiguo como fallback")
            return _envios_cache["data"]
        return []
    except (ValueError, KeyError) as e:
        logger.error(f"Error al parsear respuesta de scriptEnvios: {e}")
        return []


# ==================== SCHEMAS ====================


class MotoqueroBase(BaseModel):
    nombre: str = Field(..., max_length=100)
    telefono: Optional[str] = Field(None, max_length=20)
    activo: bool = True
    zona_preferida_id: Optional[int] = None


class MotoqueroCreate(MotoqueroBase):
    pass


class MotoqueroResponse(MotoqueroBase):
    id: int
    created_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class ZonaRepartoBase(BaseModel):
    nombre: str = Field(..., max_length=100)
    poligono: dict  # GeoJSON
    color: str = Field(..., max_length=7)  # Hex color
    activa: bool = True
    tipo_generacion: str = Field(default="manual", max_length=20)  # 'manual' o 'automatica'


class ZonaRepartoCreate(ZonaRepartoBase):
    pass


class ZonaRepartoResponse(ZonaRepartoBase):
    id: int
    creado_por: Optional[int]
    created_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class EnvioTurboResponse(BaseModel):
    """Envío Turbo con datos de la orden de ML"""

    mlshippingid: str
    mlo_id: int
    direccion_completa: str
    mlstreet_name: Optional[str]
    mlstreet_number: Optional[str]
    mlzip_code: Optional[str]
    mlcity_name: Optional[str]
    mlstate_name: Optional[str]
    mlreceiver_name: Optional[str]
    mlreceiver_phone: Optional[str]
    mlestimated_delivery_limit: Optional[datetime]
    mlstatus: Optional[str]
    mllogistic_type: Optional[str] = None  # 'xd_drop_off' o similar
    mlshipping_mode: Optional[str] = None  # Modo de envío
    mlturbo: Optional[str] = None  # Flag de Turbo
    mlself_service: Optional[str] = None  # Self service
    mlcross_docking: Optional[str] = None  # Cross docking
    tipo_envio: Optional[str] = None  # 'turbo', 'self_service', 'cross_docking', 'normal'
    asignado: bool = False  # True si ya está asignado
    motoquero_id: Optional[int] = None
    motoquero_nombre: Optional[str] = None
    latitud: Optional[float] = None  # Coordenadas desde geocoding_cache
    longitud: Optional[float] = None  # Coordenadas desde geocoding_cache

    model_config = ConfigDict(from_attributes=True)


class AsignacionRequest(BaseModel):
    """Request para asignar envíos a un motoquero"""

    mlshippingids: List[str] = Field(..., description="Lista de IDs de shipping a asignar")
    motoquero_id: int = Field(..., description="ID del motoquero")
    zona_id: Optional[int] = Field(None, description="ID de la zona (opcional)")
    asignado_por: str = Field(default="manual", description="'manual' o 'automatico'")


class AsignacionResponse(BaseModel):
    """Respuesta de asignación"""

    id: int
    mlshippingid: str
    motoquero_id: int
    zona_id: Optional[int]
    direccion: str
    latitud: Optional[float]
    longitud: Optional[float]
    estado: str
    asignado_por: Optional[str]
    asignado_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class EnvioPorMotoqueroStat(BaseModel):
    """Estadística de envíos por motoquero"""

    motoquero_id: int
    nombre: str
    total_envios: int
    ultima_asignacion: Optional[datetime]


class EstadisticasResponse(BaseModel):
    """Estadísticas generales de Turbo Routing"""

    total_envios_pendientes: int
    total_envios_asignados: int
    total_motoqueros_activos: int
    total_zonas_activas: int
    asignaciones_hoy: int


class DeleteResponse(BaseModel):
    """Respuesta estándar para operaciones DELETE"""

    message: str
    success: bool = True


class BanearEnvioRequest(BaseModel):
    mlshippingid: str = Field(..., description="ID del envío ML a banear")
    motivo: str = Field(..., max_length=500, description="Motivo del baneo")
    notas: Optional[str] = Field(None, description="Notas adicionales")

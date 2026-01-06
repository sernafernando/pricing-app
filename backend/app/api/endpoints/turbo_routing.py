"""
Endpoint para gestión de routing de envíos Turbo de MercadoLibre.
Sistema de asignación de envíos a motoqueros con zonas y optimización de rutas.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

import httpx
import pytz
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.api.deps import get_current_user
from app.models.motoquero import Motoquero
from app.models.zona_reparto import ZonaReparto
from app.models.asignacion_turbo import AsignacionTurbo
from app.models.geocoding_cache import GeocodingCache
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.usuario import Usuario
from app.services.permisos_service import verificar_permiso
from app.services.kmeans_zone_service import (
    generar_zonas_kmeans,
    validar_envios_geocodificados
)
from app.services.geocoding_service import geocode_address
from app.services.ml_webhook_service import (
    fetch_shipment_data,
    extraer_coordenadas,
    extraer_direccion_completa
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Timezone de Argentina
ARGENTINA_TZ = pytz.timezone('America/Argentina/Buenos_Aires')

# Cache en memoria para scriptEnvios (evitar martillar el ERP)
_envios_cache: Dict[str, Any] = {
    "data": [],
    "timestamp": None,
    "ttl_seconds": 300  # 5 minutos
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
        cache_age = (datetime.now() - _envios_cache["timestamp"]).total_seconds()
        if cache_age < _envios_cache["ttl_seconds"]:
            logger.info(f"Usando cache de scriptEnvios (edad: {cache_age:.1f}s)")
            return _envios_cache["data"]
    
    try:
        fecha_hasta = datetime.now().strftime('%Y-%m-%d')
        fecha_desde = (datetime.now() - timedelta(days=dias_atras)).strftime('%Y-%m-%d')
        
        logger.info(f"Consultando scriptEnvios (desde={fecha_desde}, hasta={fecha_hasta})")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                settings.GBP_PARSER_URL,
                json={
                    "strScriptLabel": "scriptEnvios",
                    "fromDate": fecha_desde,
                    "toDate": fecha_hasta
                }
            )
            response.raise_for_status()
            data = response.json()
            
            # Filtrar error -9
            if data and len(data) == 1 and data[0].get("Column1") == "-9":
                return []
            
            # Guardar en cache
            if usar_cache:
                _envios_cache["data"] = data
                _envios_cache["timestamp"] = datetime.now()
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
    
    class Config:
        from_attributes = True


class ZonaRepartoBase(BaseModel):
    nombre: str = Field(..., max_length=100)
    poligono: dict  # GeoJSON
    color: str = Field(..., max_length=7)  # Hex color
    activa: bool = True


class ZonaRepartoCreate(ZonaRepartoBase):
    pass


class ZonaRepartoResponse(ZonaRepartoBase):
    id: int
    creado_por: Optional[int]
    created_at: Optional[datetime]
    
    class Config:
        from_attributes = True


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
    
    class Config:
        from_attributes = True


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
    
    class Config:
        from_attributes = True


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


# ==================== ENDPOINTS: ENVÍOS TURBO ====================

@router.get("/turbo/envios/pendientes", response_model=List[EnvioTurboResponse])
async def obtener_envios_turbo_pendientes(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    incluir_asignados: bool = Query(False, description="Incluir envíos ya asignados"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    dias_atras: int = Query(30, ge=1, le=90, description="Días hacia atrás para consultar scriptEnvios")
):
    """
    Obtiene envíos Turbo pendientes ACTUALIZADOS desde scriptEnvios del ERP.
    
    Proceso:
    1. Obtiene todos los envíos Turbo (mlshipping_method_id = 515282) de la BD
    2. Cruza con scriptEnvios para actualizar estado y dirección real
    3. Filtra solo los que estén realmente pendientes (ready_to_ship, not_delivered)
    
    Esto garantiza direcciones completas y estados actualizados.
    """
    # Verificar permiso
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso para gestionar Turbo Routing")
    
    # 1. Obtener solo IDs de envíos Turbo desde BD (query optimizada - solo IDs necesarios)
    turbo_query = db.query(
        MercadoLibreOrderShipping.mlshippingid,
        MercadoLibreOrderShipping.mlo_id,
        MercadoLibreOrderShipping.mlstreet_name,
        MercadoLibreOrderShipping.mlstreet_number,
        MercadoLibreOrderShipping.mlzip_code,
        MercadoLibreOrderShipping.mlcity_name,
        MercadoLibreOrderShipping.mlstate_name,
        MercadoLibreOrderShipping.mlreceiver_name,
        MercadoLibreOrderShipping.mlreceiver_phone,
        MercadoLibreOrderShipping.mlestimated_delivery_limit,
        MercadoLibreOrderShipping.mllogistic_type,
        MercadoLibreOrderShipping.mlshipping_mode,
        MercadoLibreOrderShipping.mlturbo,
        MercadoLibreOrderShipping.mlself_service,
        MercadoLibreOrderShipping.mlcross_docking
    ).filter(
        MercadoLibreOrderShipping.mlshipping_method_id == '515282'
    ).all()
    
    # Crear mapa: shipment_id -> datos BD (solo campos necesarios)
    turbo_map = {str(row.mlshippingid): row for row in turbo_query}
    
    # 2. Obtener datos actualizados desde scriptEnvios (CON CACHE)
    envios_erp = await obtener_envios_desde_erp(dias_atras)
    
    # 3. Pre-filtrar scriptEnvios solo estados pendientes (reduce iteraciones)
    envios_pendientes_erp = [
        e for e in envios_erp 
        if e.get("Estado", "").lower() in ['ready_to_ship', 'not_delivered']
    ]
    
    # 4. Cruce optimizado: solo procesar envíos pendientes que sean Turbo
    envios_turbo_actualizados = []
    for envio_erp in envios_pendientes_erp:
        shipment_id = str(envio_erp.get("Número de Envío", ""))
        
        if shipment_id in turbo_map:
            envios_turbo_actualizados.append({
                "envio_bd": turbo_map[shipment_id],
                "envio_erp": envio_erp,
                "estado_real": envio_erp.get("Estado", "").lower()
            })
    
    # 5. Filtrar asignados si corresponde (query optimizada)
    if not incluir_asignados:
        asignados_ids_query = db.query(AsignacionTurbo.mlshippingid).filter(
            AsignacionTurbo.estado != 'cancelado'
        ).all()
        asignados_ids_set = {str(a[0]) for a in asignados_ids_query}
        
        # Filtrado usando set comprehension (más rápido)
        envios_turbo_actualizados = [
            e for e in envios_turbo_actualizados 
            if str(e["envio_bd"].mlshippingid) not in asignados_ids_set
        ]
    
    # 6. Obtener asignaciones existentes (solo si incluye asignados)
    asignaciones_map = {}
    if incluir_asignados and envios_turbo_actualizados:
        shipment_ids = [str(e["envio_bd"].mlshippingid) for e in envios_turbo_actualizados]
        asignaciones = db.query(AsignacionTurbo).filter(
            AsignacionTurbo.mlshippingid.in_(shipment_ids)
        ).all()
        asignaciones_map = {str(asig.mlshippingid): asig for asig in asignaciones}
    
    # 7. Construir respuesta con paginación
    total = len(envios_turbo_actualizados)
    envios_paginados = envios_turbo_actualizados[offset:offset+limit]
    
    resultado = []
    for item in envios_paginados:
        envio_bd = item["envio_bd"]
        envio_erp = item["envio_erp"]
        estado_real = item["estado_real"]
        
        shipment_id = str(envio_bd.mlshippingid)
        asignacion = asignaciones_map.get(shipment_id)
        
        # Usar dirección del ERP (más completa)
        direccion_completa = envio_erp.get("Dirección de Entrega", "Dirección no disponible")
        
        resultado.append(EnvioTurboResponse(
            mlshippingid=shipment_id,
            mlo_id=envio_bd.mlo_id,
            direccion_completa=direccion_completa,
            mlstreet_name=envio_bd.mlstreet_name,
            mlstreet_number=envio_bd.mlstreet_number,
            mlzip_code=envio_bd.mlzip_code,
            mlcity_name=envio_bd.mlcity_name,
            mlstate_name=envio_bd.mlstate_name,
            mlreceiver_name=envio_bd.mlreceiver_name,
            mlreceiver_phone=envio_bd.mlreceiver_phone,
            mlestimated_delivery_limit=convert_to_argentina_tz(envio_bd.mlestimated_delivery_limit),
            mlstatus=estado_real,  # ESTADO REAL desde scriptEnvios
            mllogistic_type=envio_bd.mllogistic_type,
            mlshipping_mode=envio_bd.mlshipping_mode,
            mlturbo=envio_bd.mlturbo,
            mlself_service=envio_bd.mlself_service,
            mlcross_docking=envio_bd.mlcross_docking,
            tipo_envio='turbo',
            asignado=asignacion is not None,
            motoquero_id=asignacion.motoquero_id if asignacion else None,
            motoquero_nombre=asignacion.motoquero.nombre if asignacion and asignacion.motoquero else None
        ))
    
    return resultado


# ==================== ENDPOINTS: MOTOQUEROS ====================

@router.get("/turbo/motoqueros", response_model=List[MotoqueroResponse])
async def obtener_motoqueros(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    solo_activos: bool = Query(True, description="Solo motoqueros activos")
):
    """Obtiene la lista de motoqueros."""
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    query = db.query(Motoquero)
    if solo_activos:
        query = query.filter(Motoquero.activo.is_(True))
    
    motoqueros = query.order_by(Motoquero.nombre).all()
    return motoqueros


@router.post("/turbo/motoqueros", response_model=MotoqueroResponse)
async def crear_motoquero(
    motoquero: MotoqueroCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Crea un nuevo motoquero."""
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    nuevo_motoquero = Motoquero(**motoquero.model_dump())
    db.add(nuevo_motoquero)
    db.commit()
    db.refresh(nuevo_motoquero)
    
    return nuevo_motoquero


@router.put("/turbo/motoqueros/{motoquero_id}", response_model=MotoqueroResponse)
async def actualizar_motoquero(
    motoquero_id: int,
    motoquero: MotoqueroCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Actualiza un motoquero existente."""
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    db_motoquero = db.query(Motoquero).filter(Motoquero.id == motoquero_id).first()
    if not db_motoquero:
        raise HTTPException(status_code=404, detail="Motoquero no encontrado")
    
    for key, value in motoquero.model_dump().items():
        setattr(db_motoquero, key, value)
    
    db.commit()
    db.refresh(db_motoquero)
    
    return db_motoquero


@router.delete("/turbo/motoqueros/{motoquero_id}", response_model=DeleteResponse)
async def desactivar_motoquero(
    motoquero_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Desactiva un motoquero (no lo elimina físicamente)."""
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    db_motoquero = db.query(Motoquero).filter(Motoquero.id == motoquero_id).first()
    if not db_motoquero:
        raise HTTPException(status_code=404, detail="Motoquero no encontrado")
    
    db_motoquero.activo = False
    db.commit()
    
    return DeleteResponse(message="Motoquero desactivado", success=True)


# ==================== ENDPOINTS: ZONAS ====================

@router.get("/turbo/zonas", response_model=List[ZonaRepartoResponse])
async def obtener_zonas(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    solo_activas: bool = Query(True, description="Solo zonas activas")
):
    """Obtiene la lista de zonas de reparto."""
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    query = db.query(ZonaReparto)
    if solo_activas:
        query = query.filter(ZonaReparto.activa.is_(True))
    
    zonas = query.order_by(ZonaReparto.nombre).all()
    return zonas


@router.post("/turbo/zonas", response_model=ZonaRepartoResponse)
async def crear_zona(
    zona: ZonaRepartoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Crea una nueva zona de reparto."""
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    nueva_zona = ZonaReparto(
        **zona.model_dump(),
        creado_por=current_user.id
    )
    db.add(nueva_zona)
    db.commit()
    db.refresh(nueva_zona)
    
    return nueva_zona


@router.delete("/turbo/zonas/{zona_id}", response_model=DeleteResponse)
async def eliminar_zona(
    zona_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Desactiva una zona (no la elimina físicamente)."""
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    db_zona = db.query(ZonaReparto).filter(ZonaReparto.id == zona_id).first()
    if not db_zona:
        raise HTTPException(status_code=404, detail="Zona no encontrada")
    
    db_zona.activa = False
    db.commit()
    
    return DeleteResponse(message="Zona desactivada", success=True)


@router.post("/turbo/zonas/auto-generar", response_model=List[ZonaRepartoResponse])
async def auto_generar_zonas(
    cantidad_motoqueros: int = Query(..., description="Cantidad de zonas a generar"),
    eliminar_anteriores: bool = Query(False, description="Eliminar zonas auto-generadas anteriores"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Auto-genera zonas de reparto usando K-Means clustering sobre envíos geocodificados.
    
    Algoritmo:
    1. Obtiene envíos Turbo pendientes (sin asignar)
    2. Filtra solo los geocodificados (lat/lng válidos)
    3. Valida que al menos 70% estén geocodificados
    4. Aplica K-Means para agrupar en K clusters (K = cantidad_motoqueros)
    5. Genera polígono ConvexHull por cada cluster
    6. Balancea automáticamente cantidad de paquetes por zona
    
    Args:
        cantidad_motoqueros: Cantidad de zonas a crear (1 zona por motoquero)
        eliminar_anteriores: Si True, desactiva zonas auto-generadas previas
        
    Returns:
        Lista de zonas creadas con distribución equitativa de envíos
    """
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    if cantidad_motoqueros < 1 or cantidad_motoqueros > 6:
        raise HTTPException(
            status_code=400, 
            detail="Cantidad debe estar entre 1 y 6"
        )
    
    try:
        logger.info(f"🤖 Auto-generando {cantidad_motoqueros} zonas con K-Means clustering...")
        
        # 1. Obtener envíos Turbo SIN asignar
        envios_sin_asignar = db.query(MercadoLibreOrderShipping).filter(
            and_(
                MercadoLibreOrderShipping.mlshipping_method_id == '515282',
                MercadoLibreOrderShipping.mlstatus.in_(['ready_to_ship', 'not_delivered']),
                ~MercadoLibreOrderShipping.mlshippingid.in_(
                    db.query(AsignacionTurbo.mlshippingid).filter(
                        AsignacionTurbo.estado != 'cancelado'
                    )
                )
            )
        ).all()
        
        if not envios_sin_asignar:
            raise HTTPException(
                status_code=400,
                detail="No hay envíos Turbo pendientes para asignar"
            )
        
        logger.info(f"📦 {len(envios_sin_asignar)} envíos Turbo sin asignar")
        
        # 2. Filtrar envíos geocodificados (lat/lng válidos)
        envios_coords = []
        for envio in envios_sin_asignar:
            # Construir dirección normalizada
            direccion = f"{envio.mlstreet_name} {envio.mlstreet_number}, {envio.mlcity_name}".strip()
            
            # Buscar en cache de geocoding
            direccion_hash = GeocodingCache.hash_direccion(direccion)
            cache = db.query(GeocodingCache).filter(
                GeocodingCache.direccion_hash == direccion_hash
            ).first()
            
            if cache and cache.latitud and cache.longitud:
                envios_coords.append((float(cache.latitud), float(cache.longitud), envio.mlm_id))
        
        # 3. Validar porcentaje de geocodificación
        es_valido, mensaje = validar_envios_geocodificados(
            total_envios=len(envios_sin_asignar),
            envios_geocodificados=len(envios_coords),
            porcentaje_minimo=0.7
        )
        
        if not es_valido:
            raise HTTPException(status_code=400, detail=mensaje)
        
        logger.info(mensaje)
        
        # 4. Eliminar zonas auto-generadas anteriores si se solicita
        if eliminar_anteriores:
            zonas_auto = db.query(ZonaReparto).filter(
                ZonaReparto.nombre.like('%Auto%')
            ).all()
            for zona in zonas_auto:
                zona.activa = False
            db.commit()
            logger.info(f"🗑️ Desactivadas {len(zonas_auto)} zonas automáticas anteriores")
        
        # 5. Generar zonas usando K-Means
        zonas_data = generar_zonas_kmeans(
            envios_coords=envios_coords,
            cantidad_zonas=cantidad_motoqueros
        )
        
        if not zonas_data:
            raise HTTPException(
                status_code=500,
                detail="No se pudieron generar zonas. Verificar logs del servidor."
            )
        
        # 6. Guardar en BD
        zonas_creadas = []
        for zona_data in zonas_data:
            nueva_zona = ZonaReparto(
                nombre=zona_data['nombre'],
                descripcion=zona_data['descripcion'],
                poligono=zona_data['poligono'],
                color=zona_data['color'],
                activa=True,
                creado_por=current_user.id
            )
            db.add(nueva_zona)
            zonas_creadas.append(nueva_zona)
        
        db.commit()
        
        # Refrescar para obtener IDs
        for zona in zonas_creadas:
            db.refresh(zona)
        
        logger.info(f"✅ {len(zonas_creadas)} zonas auto-generadas con K-Means")
        return zonas_creadas
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error auto-generando zonas: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error generando zonas: {str(e)}"
        )


# ==================== ENDPOINTS: ASIGNACIONES ====================

@router.post("/turbo/asignacion/manual", response_model=List[AsignacionResponse])
async def asignar_envios_manual(
    asignacion: AsignacionRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Asigna envíos Turbo a un motoquero manualmente.
    """
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    # Validar que el motoquero existe
    motoquero = db.query(Motoquero).filter(Motoquero.id == asignacion.motoquero_id).first()
    if not motoquero:
        raise HTTPException(status_code=404, detail="Motoquero no encontrado")
    
    # Validar zona si se especificó
    if asignacion.zona_id:
        zona = db.query(ZonaReparto).filter(ZonaReparto.id == asignacion.zona_id).first()
        if not zona:
            raise HTTPException(status_code=404, detail="Zona no encontrada")
    
    asignaciones_creadas = []
    
    for mlshippingid in asignacion.mlshippingids:
        # Obtener datos del envío
        envio = db.query(MercadoLibreOrderShipping).filter(
            MercadoLibreOrderShipping.mlshippingid == mlshippingid
        ).first()
        
        if not envio:
            continue  # Skip si no existe
        
        # Verificar si ya está asignado
        asignacion_existente = db.query(AsignacionTurbo).filter(
            AsignacionTurbo.mlshippingid == mlshippingid,
            AsignacionTurbo.estado != 'cancelado'
        ).first()
        
        if asignacion_existente:
            # Reasignar
            asignacion_existente.motoquero_id = asignacion.motoquero_id
            asignacion_existente.zona_id = asignacion.zona_id
            asignacion_existente.asignado_por = asignacion.asignado_por
            asignacion_existente.asignado_at = datetime.now(ARGENTINA_TZ)
            db_asignacion = asignacion_existente
        else:
            # Crear nueva asignación
            # Construir dirección
            direccion_partes = []
            if envio.mlstreet_name:
                direccion_partes.append(envio.mlstreet_name)
            if envio.mlstreet_number:
                direccion_partes.append(envio.mlstreet_number)
            if envio.mlcity_name:
                direccion_partes.append(envio.mlcity_name)
            direccion = ", ".join(direccion_partes) or envio.mlreceiver_address or "Dirección no disponible"
            
            db_asignacion = AsignacionTurbo(
                mlshippingid=mlshippingid,
                motoquero_id=asignacion.motoquero_id,
                zona_id=asignacion.zona_id,
                direccion=direccion[:500],  # Truncar a 500 chars
                estado='pendiente',
                asignado_por=asignacion.asignado_por
            )
            db.add(db_asignacion)
        
        asignaciones_creadas.append(db_asignacion)
    
    db.commit()
    
    # Refrescar para obtener IDs
    for a in asignaciones_creadas:
        db.refresh(a)
    
    return asignaciones_creadas


@router.get("/turbo/asignaciones/resumen", response_model=List[EnvioPorMotoqueroStat])
async def obtener_resumen_asignaciones(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene resumen de asignaciones agrupadas por motoquero.
    """
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    # Query agrupada
    resumen = db.query(
        Motoquero.id,
        Motoquero.nombre,
        func.count(AsignacionTurbo.id).label('total_envios'),
        func.max(AsignacionTurbo.asignado_at).label('ultima_asignacion')
    ).join(
        AsignacionTurbo, AsignacionTurbo.motoquero_id == Motoquero.id
    ).filter(
        Motoquero.activo.is_(True),
        AsignacionTurbo.estado != 'cancelado'
    ).group_by(
        Motoquero.id, Motoquero.nombre
    ).all()
    
    return [
        EnvioPorMotoqueroStat(
            motoquero_id=r.id,
            nombre=r.nombre,
            total_envios=r.total_envios,
            ultima_asignacion=r.ultima_asignacion
        )
        for r in resumen
    ]


@router.get("/turbo/estadisticas", response_model=EstadisticasResponse)
async def obtener_estadisticas(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    dias_atras: int = Query(30, ge=1, le=90, description="Días hacia atrás para consultar scriptEnvios")
):
    """
    Obtiene estadísticas generales del sistema de Turbo Routing.
    
    IMPORTANTE: Usa scriptEnvios para contar envíos pendientes REALES (no datos stale).
    """
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    # 1. Obtener solo IDs de envíos Turbo desde BD (query optimizada)
    turbo_ids_query = db.query(MercadoLibreOrderShipping.mlshippingid).filter(
        MercadoLibreOrderShipping.mlshipping_method_id == '515282'
    ).all()
    turbo_ids_set = {str(sid[0]) for sid in turbo_ids_query}
    
    # 2. Obtener datos actualizados desde scriptEnvios (CON CACHE)
    envios_erp = await obtener_envios_desde_erp(dias_atras)
    
    # 3. Pre-filtrar scriptEnvios: solo estados pendientes
    envios_pendientes_erp = [
        e for e in envios_erp 
        if e.get("Estado", "").lower() in ['ready_to_ship', 'not_delivered']
    ]
    
    # 4. Contar envíos Turbo pendientes (cruce optimizado con set)
    envios_pendientes_ids = {
        str(e.get("Número de Envío", ""))
        for e in envios_pendientes_erp
        if str(e.get("Número de Envío", "")) in turbo_ids_set
    }
    
    # 5. Filtrar asignados (query optimizada con set)
    asignados_ids_query = db.query(AsignacionTurbo.mlshippingid).filter(
        AsignacionTurbo.estado != 'cancelado'
    ).all()
    asignados_ids_set = {str(a[0]) for a in asignados_ids_query}
    
    # Contar solo los NO asignados (operación de sets: O(n) en lugar de O(n²))
    total_pendientes = len(envios_pendientes_ids - asignados_ids_set)
    
    # Total asignados
    total_asignados = len(asignados_ids_set)
    
    # Motoqueros activos
    total_motoqueros = db.query(func.count(Motoquero.id)).filter(Motoquero.activo.is_(True)).scalar() or 0
    
    # Zonas activas
    total_zonas = db.query(func.count(ZonaReparto.id)).filter(ZonaReparto.activa.is_(True)).scalar() or 0
    
    # Asignaciones hoy (fecha actual en Argentina)
    hoy_inicio = datetime.now(ARGENTINA_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    asignaciones_hoy = db.query(func.count(AsignacionTurbo.id)).filter(
        AsignacionTurbo.asignado_at >= hoy_inicio,
        AsignacionTurbo.estado != 'cancelado'
    ).scalar() or 0
    
    return EstadisticasResponse(
        total_envios_pendientes=total_pendientes,
        total_envios_asignados=total_asignados,
        total_motoqueros_activos=total_motoqueros,
        total_zonas_activas=total_zonas,
        asignaciones_hoy=asignaciones_hoy
    )


@router.post("/turbo/cache/invalidar", response_model=DeleteResponse)
async def invalidar_cache_envios(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Invalida el cache de scriptEnvios para forzar actualización inmediata.
    Útil después de asignar envíos o cuando se necesitan datos frescos.
    """
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    _envios_cache["timestamp"] = None
    _envios_cache["data"] = []
    
    return DeleteResponse(message="Cache invalidado correctamente", success=True)


# ==================== ENDPOINTS: GEOCODING ====================

@router.post("/turbo/geocoding/envio/{shipment_id}", response_model=dict)
async def geocodificar_envio(
    shipment_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Geocodifica un envío específico usando su dirección.
    Guarda el resultado en la tabla geocoding_cache y actualiza asignaciones_turbo si existe.
    """
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    # Buscar envío en BD
    envio = db.query(MercadoLibreOrderShipping).filter(
        MercadoLibreOrderShipping.mlshippingid == shipment_id
    ).first()
    
    if not envio:
        raise HTTPException(status_code=404, detail="Envío no encontrado")
    
    # Construir dirección
    direccion_partes = []
    if envio.mlstreet_name:
        direccion_partes.append(envio.mlstreet_name)
    if envio.mlstreet_number:
        direccion_partes.append(envio.mlstreet_number)
    
    direccion = " ".join(direccion_partes) if direccion_partes else None
    ciudad = envio.mlcity_name or "Buenos Aires"
    
    if not direccion:
        raise HTTPException(status_code=400, detail="Envío sin dirección válida")
    
    # Geocodificar
    coords = await geocode_address(direccion, ciudad=ciudad, db=db)
    
    if not coords:
        raise HTTPException(status_code=404, detail="No se pudo geocodificar la dirección")
    
    latitud, longitud = coords
    
    # Actualizar asignación si existe
    asignacion = db.query(AsignacionTurbo).filter(
        AsignacionTurbo.mlshippingid == shipment_id,
        AsignacionTurbo.estado != 'cancelado'
    ).first()
    
    if asignacion:
        asignacion.latitud = latitud
        asignacion.longitud = longitud
        asignacion.direccion = f"{direccion}, {ciudad}"
        db.commit()
    
    return {
        "shipment_id": shipment_id,
        "direccion": f"{direccion}, {ciudad}",
        "latitud": latitud,
        "longitud": longitud,
        "actualizado_en_asignacion": asignacion is not None
    }


@router.post("/turbo/geocoding/batch", response_model=dict)
async def geocodificar_batch(
    shipment_ids: list[str],
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Geocodifica múltiples envíos en batch.
    IMPORTANTE: Esto puede tomar tiempo. Mapbox permite ~10 req/seg.
    """
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    if len(shipment_ids) > 100:
        raise HTTPException(status_code=400, detail="Máximo 100 envíos por batch")
    
    resultados = {
        "total": len(shipment_ids),
        "exitosos": 0,
        "fallidos": 0,
        "detalles": []
    }
    
    for shipment_id in shipment_ids:
        # Buscar envío
        envio = db.query(MercadoLibreOrderShipping).filter(
            MercadoLibreOrderShipping.mlshippingid == shipment_id
        ).first()
        
        if not envio:
            resultados["fallidos"] += 1
            resultados["detalles"].append({
                "shipment_id": shipment_id,
                "status": "error",
                "mensaje": "Envío no encontrado"
            })
            continue
        
        # Construir dirección
        direccion_partes = []
        if envio.mlstreet_name:
            direccion_partes.append(envio.mlstreet_name)
        if envio.mlstreet_number:
            direccion_partes.append(envio.mlstreet_number)
        
        direccion = " ".join(direccion_partes) if direccion_partes else None
        ciudad = envio.mlcity_name or "Buenos Aires"
        
        if not direccion:
            resultados["fallidos"] += 1
            resultados["detalles"].append({
                "shipment_id": shipment_id,
                "status": "error",
                "mensaje": "Sin dirección válida"
            })
            continue
        
        # Geocodificar
        coords = await geocode_address(direccion, ciudad=ciudad, db=db)
        
        if not coords:
            resultados["fallidos"] += 1
            resultados["detalles"].append({
                "shipment_id": shipment_id,
                "status": "error",
                "mensaje": "No se pudo geocodificar"
            })
            continue
        
        latitud, longitud = coords
        
        # Actualizar asignación si existe
        asignacion = db.query(AsignacionTurbo).filter(
            AsignacionTurbo.mlshippingid == shipment_id,
            AsignacionTurbo.estado != 'cancelado'
        ).first()
        
        if asignacion:
            asignacion.latitud = latitud
            asignacion.longitud = longitud
            asignacion.direccion = f"{direccion}, {ciudad}"
        
        resultados["exitosos"] += 1
        resultados["detalles"].append({
            "shipment_id": shipment_id,
            "status": "success",
            "latitud": latitud,
            "longitud": longitud
        })
        
        # Rate limiting: Mapbox permite ~10 req/seg (100ms delay)
        await asyncio.sleep(0.1)
    
    db.commit()
    
    return resultados


@router.post("/turbo/geocoding/batch-ml", response_model=dict)
async def geocodificar_batch_ml_webhook(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Geocodifica TODOS los envíos Turbo sin asignar usando ML Webhook API.
    
    Ventajas sobre Mapbox:
    - 100% precisión (ML ya hizo el geocoding)
    - 0 costo (API interna)
    - Más rápido (sin rate limiting externo)
    
    Algoritmo:
    1. Obtiene envíos Turbo sin asignar
    2. Por cada envío, llama a ML Webhook con mlshippingid
    3. Extrae lat/lng del JSON
    4. Guarda en geocoding_cache
    
    Returns:
        Estadísticas de geocodificación batch
    """
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    logger.info("🚀 Iniciando geocoding batch desde ML Webhook...")
    
    # 1. Obtener envíos Turbo SIN asignar  
    envios_sin_asignar = db.query(MercadoLibreOrderShipping).filter(
        and_(
            MercadoLibreOrderShipping.mlshipping_method_id == '515282',
            MercadoLibreOrderShipping.mlstatus.in_(['ready_to_ship', 'not_delivered']),
            ~MercadoLibreOrderShipping.mlshippingid.in_(
                db.query(AsignacionTurbo.mlshippingid).filter(
                    AsignacionTurbo.estado != 'cancelado'
                )
            )
        )
    ).all()
    
    total_envios = len(envios_sin_asignar)
    
    if total_envios == 0:
        return {
            "total": 0,
            "exitosos": 0,
            "fallidos": 0,
            "sin_shipping_id": 0,
            "sin_coordenadas": 0,
            "mensaje": "No hay envíos Turbo pendientes"
        }
    
    logger.info(f"📦 {total_envios} envíos Turbo sin asignar")
    
    # Contadores
    exitosos = 0
    fallidos = 0
    sin_shipping_id = 0
    sin_coordenadas = 0
    
    # 2. Procesar cada envío
    for envio in envios_sin_asignar:
        try:
            # Validar que tenga shipping_id
            if not envio.mlshippingid:
                sin_shipping_id += 1
                logger.warning(f"Envío sin mlshippingid: mlo_id={envio.mlo_id}")
                continue
            
            # Llamar a ML Webhook
            data = await fetch_shipment_data(envio.mlshippingid)
            
            if not data:
                fallidos += 1
                continue
            
            # Extraer coordenadas
            lat, lng = extraer_coordenadas(data)
            
            if lat is None or lng is None:
                sin_coordenadas += 1
                logger.warning(
                    f"Envío {envio.mlshippingid} sin coordenadas en ML Webhook"
                )
                continue
            
            # Construir dirección normalizada
            direccion_completa = extraer_direccion_completa(data)
            
            if not direccion_completa:
                # Fallback: usar datos de la BD
                direccion_completa = f"{envio.mlstreet_name} {envio.mlstreet_number}, {envio.mlcity_name}".strip()
            
            # Guardar en cache de geocoding (merge = insert or update)
            cache_entry = GeocodingCache(
                direccion_normalizada=direccion_completa,
                latitud=lat,
                longitud=lng,
                fuente='ml_webhook',
                precision='ROOFTOP'  # ML Webhook siempre da alta precisión
            )
            
            # Merge: si existe la dirección, actualiza; si no, inserta
            existing = db.query(GeocodingCache).filter(
                GeocodingCache.direccion_normalizada == direccion_completa
            ).first()
            
            if existing:
                existing.latitud = lat
                existing.longitud = lng
                existing.fuente = 'ml_webhook'
                existing.precision = 'ROOFTOP'
            else:
                db.add(cache_entry)
            
            exitosos += 1
            
            # Log cada 10 envíos
            if exitosos % 10 == 0:
                logger.info(f"✅ Geocodificados: {exitosos}/{total_envios}")
            
            # Pequeño delay para no saturar (ML Webhook es rápido, pero moderamos)
            await asyncio.sleep(0.05)  # 50ms = ~20 req/seg
            
        except Exception as e:
            fallidos += 1
            logger.error(
                f"Error geocodificando envío {envio.mlshippingid}: {e}",
                exc_info=True
            )
            continue
    
    # Commit final
    db.commit()
    
    logger.info(
        f"✅ Geocoding batch completado: "
        f"{exitosos} exitosos, {fallidos} fallidos, "
        f"{sin_shipping_id} sin ID, {sin_coordenadas} sin coords"
    )
    
    return {
        "total": total_envios,
        "exitosos": exitosos,
        "fallidos": fallidos,
        "sin_shipping_id": sin_shipping_id,
        "sin_coordenadas": sin_coordenadas,
        "porcentaje_exito": round((exitosos / total_envios * 100), 2) if total_envios > 0 else 0
    }

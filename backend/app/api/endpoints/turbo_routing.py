"""
Endpoint para gestión de routing de envíos Turbo de MercadoLibre.
Sistema de asignación de envíos a motoqueros con zonas y optimización de rutas.
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
import pytz
import httpx
import logging

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.motoquero import Motoquero
from app.models.zona_reparto import ZonaReparto
from app.models.asignacion_turbo import AsignacionTurbo
from app.models.geocoding_cache import GeocodingCache
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.services.permisos_service import verificar_permiso

router = APIRouter()
logger = logging.getLogger(__name__)

# URL del gbp-parser interno
GBP_PARSER_URL = "http://localhost:8000/api/gbp-parser"

# Timezone de Argentina
ARGENTINA_TZ = pytz.timezone('America/Argentina/Buenos_Aires')

# Cache en memoria para scriptEnvios (evitar martillar el ERP)
_envios_cache: Dict[str, Any] = {
    "data": [],
    "timestamp": None,
    "ttl_seconds": 300  # 5 minutos
}


def convert_to_argentina_tz(utc_dt):
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
                GBP_PARSER_URL,
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
    current_user: dict = Depends(get_current_user)
):
    """Crea una nueva zona de reparto."""
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    nueva_zona = ZonaReparto(
        **zona.model_dump(),
        creado_por=current_user.get('id')
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

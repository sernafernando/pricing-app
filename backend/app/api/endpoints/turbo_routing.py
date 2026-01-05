"""
Endpoint para gestión de routing de envíos Turbo de MercadoLibre.
Sistema de asignación de envíos a motoqueros con zonas y optimización de rutas.
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import pytz

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.motoquero import Motoquero
from app.models.zona_reparto import ZonaReparto
from app.models.asignacion_turbo import AsignacionTurbo
from app.models.geocoding_cache import GeocodingCache
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.services.permisos_service import verificar_permiso

router = APIRouter()

# Timezone de Argentina
ARGENTINA_TZ = pytz.timezone('America/Argentina/Buenos_Aires')


def convert_to_argentina_tz(utc_dt):
    """Convierte un datetime UTC a timezone de Argentina"""
    if not utc_dt:
        return None
    if utc_dt.tzinfo is None:
        utc_dt = pytz.utc.localize(utc_dt)
    return utc_dt.astimezone(ARGENTINA_TZ)


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


class EstadisticasResponse(BaseModel):
    """Estadísticas generales de Turbo Routing"""
    total_envios_pendientes: int
    total_envios_asignados: int
    total_motoqueros_activos: int
    total_zonas_activas: int
    envios_por_motoquero: List[dict]


# ==================== ENDPOINTS: ENVÍOS TURBO ====================

@router.get("/turbo/envios/pendientes", response_model=List[EnvioTurboResponse])
async def obtener_envios_turbo_pendientes(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    incluir_asignados: bool = Query(False, description="Incluir envíos ya asignados"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """
    Obtiene envíos Turbo pendientes desde tb_mercadolibre_orders_shipping.
    Filtra por mlshipping_method_id = '515282' (Turbo).
    """
    # Verificar permiso
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso para gestionar Turbo Routing")
    
    # Query base: envíos Turbo
    query = db.query(MercadoLibreOrderShipping).filter(
        MercadoLibreOrderShipping.mlshipping_method_id == '515282',
        MercadoLibreOrderShipping.mlstatus.notin_(['cancelled', 'delivered'])
    )
    
    # Si no incluir asignados, excluir los que ya tienen asignación
    if not incluir_asignados:
        asignados_ids = db.query(AsignacionTurbo.mlshippingid).filter(
            AsignacionTurbo.estado != 'cancelado'
        ).all()
        asignados_ids = [a.mlshippingid for a in asignados_ids]
        if asignados_ids:
            query = query.filter(~MercadoLibreOrderShipping.mlshippingid.in_(asignados_ids))
    
    # Ordenar por fecha límite de entrega (urgentes primero)
    query = query.order_by(MercadoLibreOrderShipping.mlestimated_delivery_limit.asc())
    
    envios = query.offset(offset).limit(limit).all()
    
    # Obtener asignaciones existentes
    asignaciones_map = {}
    if incluir_asignados:
        asignaciones = db.query(AsignacionTurbo).filter(
            AsignacionTurbo.mlshippingid.in_([e.mlshippingid for e in envios])
        ).all()
        for asig in asignaciones:
            asignaciones_map[asig.mlshippingid] = asig
    
    # Construir respuesta
    resultado = []
    for envio in envios:
        asignacion = asignaciones_map.get(envio.mlshippingid)
        
        # Construir dirección completa
        direccion_partes = []
        if envio.mlstreet_name:
            direccion_partes.append(envio.mlstreet_name)
        if envio.mlstreet_number:
            direccion_partes.append(envio.mlstreet_number)
        if envio.mlzip_code:
            direccion_partes.append(f"CP {envio.mlzip_code}")
        if envio.mlcity_name:
            direccion_partes.append(envio.mlcity_name)
        direccion_completa = ", ".join(direccion_partes) or "Dirección no disponible"
        
        resultado.append(EnvioTurboResponse(
            mlshippingid=envio.mlshippingid,
            mlo_id=envio.mlo_id,
            direccion_completa=direccion_completa,
            mlstreet_name=envio.mlstreet_name,
            mlstreet_number=envio.mlstreet_number,
            mlzip_code=envio.mlzip_code,
            mlcity_name=envio.mlcity_name,
            mlstate_name=envio.mlstate_name,
            mlreceiver_name=envio.mlreceiver_name,
            mlreceiver_phone=envio.mlreceiver_phone,
            mlestimated_delivery_limit=convert_to_argentina_tz(envio.mlestimated_delivery_limit),
            mlstatus=envio.mlstatus,
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
        query = query.filter(Motoquero.activo == True)
    
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
    
    nuevo_motoquero = Motoquero(**motoquero.dict())
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
    
    for key, value in motoquero.dict().items():
        setattr(db_motoquero, key, value)
    
    db.commit()
    db.refresh(db_motoquero)
    
    return db_motoquero


@router.delete("/turbo/motoqueros/{motoquero_id}")
async def eliminar_motoquero(
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
    
    return {"status": "ok", "message": "Motoquero desactivado"}


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
        query = query.filter(ZonaReparto.activa == True)
    
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
        **zona.dict(),
        creado_por=current_user.get('id')
    )
    db.add(nueva_zona)
    db.commit()
    db.refresh(nueva_zona)
    
    return nueva_zona


@router.delete("/turbo/zonas/{zona_id}")
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
    
    return {"status": "ok", "message": "Zona desactivada"}


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


@router.get("/turbo/asignaciones/resumen", response_model=List[dict])
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
        func.count(func.nullif(AsignacionTurbo.estado, 'entregado')).label('pendientes')
    ).join(
        AsignacionTurbo, AsignacionTurbo.motoquero_id == Motoquero.id
    ).filter(
        Motoquero.activo == True,
        AsignacionTurbo.estado != 'cancelado'
    ).group_by(
        Motoquero.id, Motoquero.nombre
    ).all()
    
    return [
        {
            "motoquero_id": r.id,
            "nombre": r.nombre,
            "total_envios": r.total_envios,
            "pendientes": r.pendientes
        }
        for r in resumen
    ]


@router.get("/turbo/estadisticas", response_model=EstadisticasResponse)
async def obtener_estadisticas(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Obtiene estadísticas generales del sistema de Turbo Routing."""
    if not verificar_permiso(db, current_user, 'ordenes.gestionar_turbo_routing'):
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    # Total envíos Turbo pendientes (sin asignar)
    asignados_ids = db.query(AsignacionTurbo.mlshippingid).filter(
        AsignacionTurbo.estado != 'cancelado'
    ).all()
    asignados_ids = [a.mlshippingid for a in asignados_ids]
    
    total_pendientes = db.query(func.count(MercadoLibreOrderShipping.mlshippingid)).filter(
        MercadoLibreOrderShipping.mlshipping_method_id == '515282',
        MercadoLibreOrderShipping.mlstatus.notin_(['cancelled', 'delivered']),
        ~MercadoLibreOrderShipping.mlshippingid.in_(asignados_ids) if asignados_ids else True
    ).scalar() or 0
    
    # Total asignados
    total_asignados = db.query(func.count(AsignacionTurbo.id)).filter(
        AsignacionTurbo.estado != 'cancelado'
    ).scalar() or 0
    
    # Motoqueros activos
    total_motoqueros = db.query(func.count(Motoquero.id)).filter(Motoquero.activo == True).scalar() or 0
    
    # Zonas activas
    total_zonas = db.query(func.count(ZonaReparto.id)).filter(ZonaReparto.activa == True).scalar() or 0
    
    # Envíos por motoquero
    envios_por_motoquero_data = db.query(
        Motoquero.nombre,
        func.count(AsignacionTurbo.id).label('total')
    ).join(
        AsignacionTurbo, AsignacionTurbo.motoquero_id == Motoquero.id
    ).filter(
        AsignacionTurbo.estado != 'cancelado'
    ).group_by(Motoquero.nombre).all()
    
    envios_por_motoquero = [
        {"motoquero": r.nombre, "total": r.total}
        for r in envios_por_motoquero_data
    ]
    
    return EstadisticasResponse(
        total_envios_pendientes=total_pendientes,
        total_envios_asignados=total_asignados,
        total_motoqueros_activos=total_motoqueros,
        total_zonas_activas=total_zonas,
        envios_por_motoquero=envios_por_motoquero
    )

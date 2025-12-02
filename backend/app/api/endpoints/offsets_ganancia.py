from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import date
from pydantic import BaseModel

from app.core.database import get_db
from app.models.offset_ganancia import OffsetGanancia
from app.models.usuario import Usuario
from app.models.cur_exch_history import CurExchHistory
from app.api.deps import get_current_user

router = APIRouter()


class OffsetGananciaCreate(BaseModel):
    marca: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria_id: Optional[int] = None
    item_id: Optional[int] = None
    item_ids: Optional[List[int]] = None  # Para múltiples productos
    tipo_offset: str = 'monto_fijo'  # 'monto_fijo', 'monto_por_unidad', 'porcentaje_costo'
    monto: Optional[float] = None
    moneda: str = 'ARS'  # 'ARS', 'USD'
    tipo_cambio: Optional[float] = None
    porcentaje: Optional[float] = None
    descripcion: Optional[str] = None
    fecha_desde: date
    fecha_hasta: Optional[date] = None


class OffsetGananciaUpdate(BaseModel):
    marca: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria_id: Optional[int] = None
    item_id: Optional[int] = None
    tipo_offset: Optional[str] = None
    monto: Optional[float] = None
    moneda: Optional[str] = None
    tipo_cambio: Optional[float] = None
    porcentaje: Optional[float] = None
    descripcion: Optional[str] = None
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None


class OffsetGananciaResponse(BaseModel):
    id: int
    marca: Optional[str]
    categoria: Optional[str]
    subcategoria_id: Optional[int]
    item_id: Optional[int]
    tipo_offset: str = 'monto_fijo'
    monto: Optional[float]
    moneda: str = 'ARS'
    tipo_cambio: Optional[float]
    porcentaje: Optional[float]
    descripcion: Optional[str]
    fecha_desde: date
    fecha_hasta: Optional[date]
    usuario_nombre: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/offsets-ganancia", response_model=List[OffsetGananciaResponse])
async def listar_offsets(
    marca: Optional[str] = None,
    categoria: Optional[str] = None,
    subcategoria_id: Optional[int] = None,
    item_id: Optional[int] = None,
    solo_vigentes: bool = False,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista offsets de ganancia con filtros opcionales"""
    query = db.query(OffsetGanancia)

    if marca:
        query = query.filter(OffsetGanancia.marca == marca)
    if categoria:
        query = query.filter(OffsetGanancia.categoria == categoria)
    if subcategoria_id:
        query = query.filter(OffsetGanancia.subcategoria_id == subcategoria_id)
    if item_id:
        query = query.filter(OffsetGanancia.item_id == item_id)

    if solo_vigentes:
        hoy = date.today()
        query = query.filter(
            and_(
                OffsetGanancia.fecha_desde <= hoy,
                or_(
                    OffsetGanancia.fecha_hasta.is_(None),
                    OffsetGanancia.fecha_hasta >= hoy
                )
            )
        )

    offsets = query.order_by(OffsetGanancia.fecha_creacion.desc()).all()

    return [
        OffsetGananciaResponse(
            id=o.id,
            marca=o.marca,
            categoria=o.categoria,
            subcategoria_id=o.subcategoria_id,
            item_id=o.item_id,
            tipo_offset=o.tipo_offset or 'monto_fijo',
            monto=o.monto,
            moneda=o.moneda or 'ARS',
            tipo_cambio=o.tipo_cambio,
            porcentaje=o.porcentaje,
            descripcion=o.descripcion,
            fecha_desde=o.fecha_desde,
            fecha_hasta=o.fecha_hasta,
            usuario_nombre=o.usuario.nombre if o.usuario else None
        )
        for o in offsets
    ]


@router.post("/offsets-ganancia")
async def crear_offset(
    offset: OffsetGananciaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Crea un nuevo offset de ganancia. Si se pasan múltiples item_ids, crea uno por cada producto."""
    # Validar tipo de offset
    if offset.tipo_offset == 'porcentaje_costo' and offset.porcentaje is None:
        raise HTTPException(400, "Debe especificar el porcentaje para tipo porcentaje_costo")
    if offset.tipo_offset in ['monto_fijo', 'monto_por_unidad'] and offset.monto is None:
        raise HTTPException(400, "Debe especificar el monto para este tipo de offset")

    # Si hay múltiples productos, crear un offset por cada uno
    if offset.item_ids and len(offset.item_ids) > 0:
        offsets_creados = []
        for item_id in offset.item_ids:
            nuevo_offset = OffsetGanancia(
                item_id=item_id,
                tipo_offset=offset.tipo_offset,
                monto=offset.monto,
                moneda=offset.moneda,
                tipo_cambio=offset.tipo_cambio,
                porcentaje=offset.porcentaje,
                descripcion=offset.descripcion,
                fecha_desde=offset.fecha_desde,
                fecha_hasta=offset.fecha_hasta,
                usuario_id=current_user.id
            )
            db.add(nuevo_offset)
            offsets_creados.append(nuevo_offset)

        db.commit()
        for o in offsets_creados:
            db.refresh(o)

        return {"mensaje": f"Se crearon {len(offsets_creados)} offsets", "cantidad": len(offsets_creados)}

    # Validar que al menos un nivel esté definido para offset individual
    niveles = [offset.marca, offset.categoria, offset.subcategoria_id, offset.item_id]
    niveles_definidos = [n for n in niveles if n is not None]

    if len(niveles_definidos) == 0:
        raise HTTPException(400, "Debe especificar al menos un nivel (marca, categoría, subcategoría o producto)")

    if len(niveles_definidos) > 1:
        raise HTTPException(400, "Solo puede especificar un nivel por offset")

    nuevo_offset = OffsetGanancia(
        marca=offset.marca,
        categoria=offset.categoria,
        subcategoria_id=offset.subcategoria_id,
        item_id=offset.item_id,
        tipo_offset=offset.tipo_offset,
        monto=offset.monto,
        moneda=offset.moneda,
        tipo_cambio=offset.tipo_cambio,
        porcentaje=offset.porcentaje,
        descripcion=offset.descripcion,
        fecha_desde=offset.fecha_desde,
        fecha_hasta=offset.fecha_hasta,
        usuario_id=current_user.id
    )

    db.add(nuevo_offset)
    db.commit()
    db.refresh(nuevo_offset)

    return OffsetGananciaResponse(
        id=nuevo_offset.id,
        marca=nuevo_offset.marca,
        categoria=nuevo_offset.categoria,
        subcategoria_id=nuevo_offset.subcategoria_id,
        item_id=nuevo_offset.item_id,
        tipo_offset=nuevo_offset.tipo_offset or 'monto_fijo',
        monto=nuevo_offset.monto,
        moneda=nuevo_offset.moneda or 'ARS',
        tipo_cambio=nuevo_offset.tipo_cambio,
        porcentaje=nuevo_offset.porcentaje,
        descripcion=nuevo_offset.descripcion,
        fecha_desde=nuevo_offset.fecha_desde,
        fecha_hasta=nuevo_offset.fecha_hasta,
        usuario_nombre=current_user.nombre
    )


@router.put("/offsets-ganancia/{offset_id}", response_model=OffsetGananciaResponse)
async def actualizar_offset(
    offset_id: int,
    offset_update: OffsetGananciaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Actualiza un offset existente"""
    offset = db.query(OffsetGanancia).filter(OffsetGanancia.id == offset_id).first()

    if not offset:
        raise HTTPException(404, "Offset no encontrado")

    # Si se actualiza el nivel de aplicación, limpiar los otros niveles
    # Solo uno debe tener valor a la vez
    niveles_enviados = [
        offset_update.marca is not None,
        offset_update.categoria is not None,
        offset_update.subcategoria_id is not None,
        offset_update.item_id is not None
    ]
    if any(niveles_enviados):
        # Limpiar todos los niveles primero
        offset.marca = None
        offset.categoria = None
        offset.subcategoria_id = None
        offset.item_id = None
        # Asignar el nuevo nivel
        if offset_update.marca is not None:
            offset.marca = offset_update.marca
        if offset_update.categoria is not None:
            offset.categoria = offset_update.categoria
        if offset_update.subcategoria_id is not None:
            offset.subcategoria_id = offset_update.subcategoria_id
        if offset_update.item_id is not None:
            offset.item_id = offset_update.item_id

    if offset_update.tipo_offset is not None:
        offset.tipo_offset = offset_update.tipo_offset
    if offset_update.monto is not None:
        offset.monto = offset_update.monto
    if offset_update.moneda is not None:
        offset.moneda = offset_update.moneda
    if offset_update.tipo_cambio is not None:
        offset.tipo_cambio = offset_update.tipo_cambio
    if offset_update.porcentaje is not None:
        offset.porcentaje = offset_update.porcentaje
    if offset_update.descripcion is not None:
        offset.descripcion = offset_update.descripcion
    if offset_update.fecha_desde is not None:
        offset.fecha_desde = offset_update.fecha_desde
    if offset_update.fecha_hasta is not None:
        offset.fecha_hasta = offset_update.fecha_hasta

    db.commit()
    db.refresh(offset)

    return OffsetGananciaResponse(
        id=offset.id,
        marca=offset.marca,
        categoria=offset.categoria,
        subcategoria_id=offset.subcategoria_id,
        item_id=offset.item_id,
        tipo_offset=offset.tipo_offset or 'monto_fijo',
        monto=offset.monto,
        moneda=offset.moneda or 'ARS',
        tipo_cambio=offset.tipo_cambio,
        porcentaje=offset.porcentaje,
        descripcion=offset.descripcion,
        fecha_desde=offset.fecha_desde,
        fecha_hasta=offset.fecha_hasta,
        usuario_nombre=offset.usuario.nombre if offset.usuario else None
    )


@router.delete("/offsets-ganancia/{offset_id}")
async def eliminar_offset(
    offset_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Elimina un offset"""
    offset = db.query(OffsetGanancia).filter(OffsetGanancia.id == offset_id).first()

    if not offset:
        raise HTTPException(404, "Offset no encontrado")

    db.delete(offset)
    db.commit()

    return {"mensaje": "Offset eliminado"}


@router.get("/tipo-cambio-hoy")
async def obtener_tipo_cambio(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el tipo de cambio USD/ARS más reciente"""
    tipo_cambio = db.query(CurExchHistory).filter(
        CurExchHistory.curr_id_1 == 2,  # USD
        CurExchHistory.curr_id_2 == 1   # ARS
    ).order_by(CurExchHistory.ceh_cd.desc()).first()

    if tipo_cambio:
        return {
            "tipo_cambio": float(tipo_cambio.ceh_exchange),
            "fecha": tipo_cambio.ceh_cd.isoformat() if tipo_cambio.ceh_cd else None
        }

    return {"tipo_cambio": 1000.0, "fecha": None}  # Default fallback

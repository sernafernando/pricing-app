from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import date
from pydantic import BaseModel

from app.core.database import get_db
from app.models.offset_ganancia import OffsetGanancia
from app.models.usuario import Usuario
from app.api.deps import get_current_user

router = APIRouter()


class OffsetGananciaCreate(BaseModel):
    marca: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria_id: Optional[int] = None
    item_id: Optional[int] = None
    monto: float
    descripcion: Optional[str] = None
    fecha_desde: date
    fecha_hasta: Optional[date] = None


class OffsetGananciaUpdate(BaseModel):
    monto: Optional[float] = None
    descripcion: Optional[str] = None
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None


class OffsetGananciaResponse(BaseModel):
    id: int
    marca: Optional[str]
    categoria: Optional[str]
    subcategoria_id: Optional[int]
    item_id: Optional[int]
    monto: float
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
            monto=o.monto,
            descripcion=o.descripcion,
            fecha_desde=o.fecha_desde,
            fecha_hasta=o.fecha_hasta,
            usuario_nombre=o.usuario.nombre if o.usuario else None
        )
        for o in offsets
    ]


@router.post("/offsets-ganancia", response_model=OffsetGananciaResponse)
async def crear_offset(
    offset: OffsetGananciaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Crea un nuevo offset de ganancia"""
    # Validar que al menos un nivel esté definido
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
        monto=offset.monto,
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
        monto=nuevo_offset.monto,
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

    if offset_update.monto is not None:
        offset.monto = offset_update.monto
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
        monto=offset.monto,
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

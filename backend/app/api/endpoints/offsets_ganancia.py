from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, text
from typing import List, Optional
from datetime import date
from pydantic import BaseModel

from app.core.database import get_db
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.usuario import Usuario
from app.models.cur_exch_history import CurExchHistory
from app.api.deps import get_current_user

router = APIRouter()


class OffsetGrupoCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None


class OffsetGrupoResponse(BaseModel):
    id: int
    nombre: str
    descripcion: Optional[str]

    class Config:
        from_attributes = True


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
    # Nuevos campos para grupos y límites
    grupo_id: Optional[int] = None
    max_unidades: Optional[int] = None
    max_monto_usd: Optional[float] = None
    # Canales de aplicación
    aplica_ml: bool = True
    aplica_fuera: bool = True


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
    # Nuevos campos para grupos y límites
    grupo_id: Optional[int] = None
    max_unidades: Optional[int] = None
    max_monto_usd: Optional[float] = None
    # Canales de aplicación
    aplica_ml: Optional[bool] = None
    aplica_fuera: Optional[bool] = None


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
    # Nuevos campos
    grupo_id: Optional[int] = None
    grupo_nombre: Optional[str] = None
    max_unidades: Optional[int] = None
    max_monto_usd: Optional[float] = None
    # Canales de aplicación
    aplica_ml: bool = True
    aplica_fuera: bool = True

    class Config:
        from_attributes = True


@router.get("/offset-grupos", response_model=List[OffsetGrupoResponse])
async def listar_grupos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista todos los grupos de offsets"""
    grupos = db.query(OffsetGrupo).order_by(OffsetGrupo.nombre).all()
    return grupos


@router.post("/offset-grupos", response_model=OffsetGrupoResponse)
async def crear_grupo(
    grupo: OffsetGrupoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Crea un nuevo grupo de offsets"""
    nuevo_grupo = OffsetGrupo(
        nombre=grupo.nombre,
        descripcion=grupo.descripcion,
        usuario_id=current_user.id
    )
    db.add(nuevo_grupo)
    db.commit()
    db.refresh(nuevo_grupo)
    return nuevo_grupo


@router.delete("/offset-grupos/{grupo_id}")
async def eliminar_grupo(
    grupo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Elimina un grupo de offsets (solo si no tiene offsets asociados)"""
    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(404, "Grupo no encontrado")

    # Verificar si tiene offsets asociados
    offsets_count = db.query(OffsetGanancia).filter(OffsetGanancia.grupo_id == grupo_id).count()
    if offsets_count > 0:
        raise HTTPException(400, f"No se puede eliminar el grupo, tiene {offsets_count} offsets asociados")

    db.delete(grupo)
    db.commit()
    return {"mensaje": "Grupo eliminado"}


@router.get("/offsets-ganancia", response_model=List[OffsetGananciaResponse])
async def listar_offsets(
    marca: Optional[str] = None,
    categoria: Optional[str] = None,
    subcategoria_id: Optional[int] = None,
    item_id: Optional[int] = None,
    grupo_id: Optional[int] = None,
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
    if grupo_id:
        query = query.filter(OffsetGanancia.grupo_id == grupo_id)

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
            usuario_nombre=o.usuario.nombre if o.usuario else None,
            grupo_id=o.grupo_id,
            grupo_nombre=o.grupo.nombre if o.grupo else None,
            max_unidades=o.max_unidades,
            max_monto_usd=o.max_monto_usd,
            aplica_ml=o.aplica_ml if o.aplica_ml is not None else True,
            aplica_fuera=o.aplica_fuera if o.aplica_fuera is not None else True
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

    # Validar grupo si se especifica
    if offset.grupo_id:
        grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == offset.grupo_id).first()
        if not grupo:
            raise HTTPException(400, "El grupo especificado no existe")

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
                grupo_id=offset.grupo_id,
                max_unidades=offset.max_unidades,
                max_monto_usd=offset.max_monto_usd,
                aplica_ml=offset.aplica_ml,
                aplica_fuera=offset.aplica_fuera,
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
        grupo_id=offset.grupo_id,
        max_unidades=offset.max_unidades,
        max_monto_usd=offset.max_monto_usd,
        aplica_ml=offset.aplica_ml,
        aplica_fuera=offset.aplica_fuera,
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
        usuario_nombre=current_user.nombre,
        grupo_id=nuevo_offset.grupo_id,
        grupo_nombre=nuevo_offset.grupo.nombre if nuevo_offset.grupo else None,
        max_unidades=nuevo_offset.max_unidades,
        max_monto_usd=nuevo_offset.max_monto_usd,
        aplica_ml=nuevo_offset.aplica_ml if nuevo_offset.aplica_ml is not None else True,
        aplica_fuera=nuevo_offset.aplica_fuera if nuevo_offset.aplica_fuera is not None else True
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
    if offset_update.grupo_id is not None:
        # Validar que el grupo exista
        if offset_update.grupo_id > 0:
            grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == offset_update.grupo_id).first()
            if not grupo:
                raise HTTPException(400, "El grupo especificado no existe")
        offset.grupo_id = offset_update.grupo_id if offset_update.grupo_id > 0 else None
    if offset_update.max_unidades is not None:
        offset.max_unidades = offset_update.max_unidades if offset_update.max_unidades > 0 else None
    if offset_update.max_monto_usd is not None:
        offset.max_monto_usd = offset_update.max_monto_usd if offset_update.max_monto_usd > 0 else None
    if offset_update.aplica_ml is not None:
        offset.aplica_ml = offset_update.aplica_ml
    if offset_update.aplica_fuera is not None:
        offset.aplica_fuera = offset_update.aplica_fuera

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
        usuario_nombre=offset.usuario.nombre if offset.usuario else None,
        grupo_id=offset.grupo_id,
        grupo_nombre=offset.grupo.nombre if offset.grupo else None,
        max_unidades=offset.max_unidades,
        max_monto_usd=offset.max_monto_usd,
        aplica_ml=offset.aplica_ml if offset.aplica_ml is not None else True,
        aplica_fuera=offset.aplica_fuera if offset.aplica_fuera is not None else True
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
    # Traer el TC más reciente sin filtrar por curr_id (la tabla solo tiene USD/ARS)
    tipo_cambio = db.query(CurExchHistory).order_by(
        CurExchHistory.ceh_cd.desc()
    ).first()

    if tipo_cambio:
        return {
            "tipo_cambio": float(tipo_cambio.ceh_exchange),
            "fecha": tipo_cambio.ceh_cd.isoformat() if tipo_cambio.ceh_cd else None
        }

    return {"tipo_cambio": 1000.0, "fecha": None}  # Default fallback


class ProductoBusquedaGeneral(BaseModel):
    item_id: int
    codigo: str
    descripcion: str
    marca: Optional[str] = None


@router.get("/buscar-productos-erp", response_model=List[ProductoBusquedaGeneral])
async def buscar_productos_erp(
    q: str = Query(..., min_length=2, description="Buscar por código o descripción"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Busca productos en el ERP por código o descripción (todos, no solo los que tienen ventas)"""
    query = """
    SELECT DISTINCT i.item_id, i.item_code, i.item_desc, b.brand_desc
    FROM tb_item i
    LEFT JOIN tb_brand b ON b.comp_id = i.comp_id AND b.brand_id = i.brand_id
    WHERE (i.item_code ILIKE :buscar OR i.item_desc ILIKE :buscar)
    ORDER BY i.item_code
    LIMIT 50
    """

    result = db.execute(text(query), {"buscar": f"%{q}%"}).fetchall()

    return [
        ProductoBusquedaGeneral(
            item_id=r.item_id,
            codigo=r.item_code or str(r.item_id),
            descripcion=r.item_desc or "",
            marca=r.brand_desc
        )
        for r in result
    ]

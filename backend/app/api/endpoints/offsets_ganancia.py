from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, text
from typing import List, Optional
from datetime import date
from pydantic import BaseModel

from app.core.database import get_db
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.offset_individual_consumo import OffsetIndividualConsumo, OffsetIndividualResumen
from app.models.usuario import Usuario
from app.models.cur_exch_history import CurExchHistory
from app.api.deps import get_current_user

router = APIRouter()


class OffsetGrupoFiltroCreate(BaseModel):
    marca: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria_id: Optional[int] = None
    item_id: Optional[int] = None


class OffsetGrupoFiltroResponse(BaseModel):
    id: int
    grupo_id: int
    marca: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria_id: Optional[int] = None
    item_id: Optional[int] = None
    producto_descripcion: Optional[str] = None

    class Config:
        from_attributes = True


class OffsetGrupoCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    filtros: Optional[List[OffsetGrupoFiltroCreate]] = None


class OffsetGrupoResponse(BaseModel):
    id: int
    nombre: str
    descripcion: Optional[str]
    filtros: List[OffsetGrupoFiltroResponse] = []

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
    aplica_tienda_nube: bool = True


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
    aplica_tienda_nube: Optional[bool] = None


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
    aplica_tienda_nube: bool = True

    class Config:
        from_attributes = True


@router.get("/offset-grupos", response_model=List[OffsetGrupoResponse])
async def listar_grupos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista todos los grupos de offsets con sus filtros"""
    grupos = db.query(OffsetGrupo).order_by(OffsetGrupo.nombre).all()

    resultado = []
    for grupo in grupos:
        filtros_response = []
        for f in grupo.filtros:
            filtro_dict = {
                "id": f.id,
                "grupo_id": f.grupo_id,
                "marca": f.marca,
                "categoria": f.categoria,
                "subcategoria_id": f.subcategoria_id,
                "item_id": f.item_id,
                "producto_descripcion": f.producto.descripcion if f.producto else None
            }
            filtros_response.append(filtro_dict)

        resultado.append({
            "id": grupo.id,
            "nombre": grupo.nombre,
            "descripcion": grupo.descripcion,
            "filtros": filtros_response
        })

    return resultado


@router.post("/offset-grupos")
async def crear_grupo(
    grupo: OffsetGrupoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Crea un nuevo grupo de offsets con filtros opcionales"""
    nuevo_grupo = OffsetGrupo(
        nombre=grupo.nombre,
        descripcion=grupo.descripcion,
        usuario_id=current_user.id
    )
    db.add(nuevo_grupo)
    db.flush()  # Para obtener el ID

    # Crear filtros si se enviaron
    filtros_creados = []
    if grupo.filtros:
        for filtro_data in grupo.filtros:
            # Validar que al menos un campo esté definido
            if not any([filtro_data.marca, filtro_data.categoria, filtro_data.subcategoria_id, filtro_data.item_id]):
                continue

            nuevo_filtro = OffsetGrupoFiltro(
                grupo_id=nuevo_grupo.id,
                marca=filtro_data.marca,
                categoria=filtro_data.categoria,
                subcategoria_id=filtro_data.subcategoria_id,
                item_id=filtro_data.item_id
            )
            db.add(nuevo_filtro)
            filtros_creados.append(nuevo_filtro)

    db.commit()
    db.refresh(nuevo_grupo)

    # Construir respuesta
    filtros_response = []
    for f in nuevo_grupo.filtros:
        filtros_response.append({
            "id": f.id,
            "grupo_id": f.grupo_id,
            "marca": f.marca,
            "categoria": f.categoria,
            "subcategoria_id": f.subcategoria_id,
            "item_id": f.item_id,
            "producto_descripcion": f.producto.descripcion if f.producto else None
        })

    return {
        "id": nuevo_grupo.id,
        "nombre": nuevo_grupo.nombre,
        "descripcion": nuevo_grupo.descripcion,
        "filtros": filtros_response
    }


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

    # Los filtros se eliminan automáticamente por el cascade
    db.delete(grupo)
    db.commit()
    return {"mensaje": "Grupo eliminado"}


# ==================== ENDPOINTS PARA FILTROS DE GRUPO ====================

@router.post("/offset-grupos/{grupo_id}/filtros")
async def agregar_filtro_a_grupo(
    grupo_id: int,
    filtro: OffsetGrupoFiltroCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Agrega un filtro a un grupo existente"""
    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(404, "Grupo no encontrado")

    # Validar que al menos un campo esté definido
    if not any([filtro.marca, filtro.categoria, filtro.subcategoria_id, filtro.item_id]):
        raise HTTPException(400, "Debe especificar al menos un campo (marca, categoría, subcategoría o producto)")

    nuevo_filtro = OffsetGrupoFiltro(
        grupo_id=grupo_id,
        marca=filtro.marca,
        categoria=filtro.categoria,
        subcategoria_id=filtro.subcategoria_id,
        item_id=filtro.item_id
    )
    db.add(nuevo_filtro)
    db.commit()
    db.refresh(nuevo_filtro)

    return {
        "id": nuevo_filtro.id,
        "grupo_id": nuevo_filtro.grupo_id,
        "marca": nuevo_filtro.marca,
        "categoria": nuevo_filtro.categoria,
        "subcategoria_id": nuevo_filtro.subcategoria_id,
        "item_id": nuevo_filtro.item_id,
        "producto_descripcion": nuevo_filtro.producto.descripcion if nuevo_filtro.producto else None
    }


@router.delete("/offset-grupos/{grupo_id}/filtros/{filtro_id}")
async def eliminar_filtro_de_grupo(
    grupo_id: int,
    filtro_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Elimina un filtro de un grupo"""
    filtro = db.query(OffsetGrupoFiltro).filter(
        OffsetGrupoFiltro.id == filtro_id,
        OffsetGrupoFiltro.grupo_id == grupo_id
    ).first()

    if not filtro:
        raise HTTPException(404, "Filtro no encontrado")

    db.delete(filtro)
    db.commit()
    return {"mensaje": "Filtro eliminado"}


@router.put("/offset-grupos/{grupo_id}/filtros")
async def actualizar_filtros_grupo(
    grupo_id: int,
    filtros: List[OffsetGrupoFiltroCreate],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Reemplaza todos los filtros de un grupo con los nuevos"""
    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(404, "Grupo no encontrado")

    # Eliminar filtros existentes
    db.query(OffsetGrupoFiltro).filter(OffsetGrupoFiltro.grupo_id == grupo_id).delete()

    # Crear nuevos filtros
    filtros_creados = []
    for filtro_data in filtros:
        if not any([filtro_data.marca, filtro_data.categoria, filtro_data.subcategoria_id, filtro_data.item_id]):
            continue

        nuevo_filtro = OffsetGrupoFiltro(
            grupo_id=grupo_id,
            marca=filtro_data.marca,
            categoria=filtro_data.categoria,
            subcategoria_id=filtro_data.subcategoria_id,
            item_id=filtro_data.item_id
        )
        db.add(nuevo_filtro)
        filtros_creados.append(nuevo_filtro)

    db.commit()

    # Refrescar para obtener las relaciones
    for f in filtros_creados:
        db.refresh(f)

    return {
        "mensaje": f"Se actualizaron {len(filtros_creados)} filtros",
        "filtros": [
            {
                "id": f.id,
                "grupo_id": f.grupo_id,
                "marca": f.marca,
                "categoria": f.categoria,
                "subcategoria_id": f.subcategoria_id,
                "item_id": f.item_id,
                "producto_descripcion": f.producto.descripcion if f.producto else None
            }
            for f in filtros_creados
        ]
    }


@router.get("/offset-grupos/{grupo_id}/filtros")
async def obtener_filtros_grupo(
    grupo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene todos los filtros de un grupo"""
    from app.models.tb_subcategory import TBSubCategory

    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(404, "Grupo no encontrado")

    # Obtener nombres de subcategorías desde tb_subcategory
    subcat_ids = [f.subcategoria_id for f in grupo.filtros if f.subcategoria_id]
    subcategorias_map = {}
    if subcat_ids:
        subcats = db.query(TBSubCategory).filter(TBSubCategory.subcat_id.in_(subcat_ids)).all()
        subcategorias_map = {s.subcat_id: s.subcat_desc for s in subcats}

    return [
        {
            "id": f.id,
            "grupo_id": f.grupo_id,
            "marca": f.marca,
            "categoria": f.categoria,
            "subcategoria_id": f.subcategoria_id,
            "subcategoria_nombre": subcategorias_map.get(f.subcategoria_id) if f.subcategoria_id else None,
            "item_id": f.item_id,
            "producto_descripcion": f.producto.descripcion if f.producto else None
        }
        for f in grupo.filtros
    ]


@router.get("/offset-filtros-opciones")
async def obtener_opciones_filtros(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene las opciones disponibles para filtros con sus relaciones.
    Devuelve marcas, categorías y subcategorías con información de relación
    para poder filtrar en cascada en el frontend.
    """
    from app.models.producto import ProductoERP
    from app.models.subcategoria import Subcategoria

    # Obtener todas las combinaciones únicas de marca-categoría-subcategoría
    # No filtramos por activo para incluir todos los productos
    combinaciones = db.query(
        ProductoERP.marca,
        ProductoERP.categoria,
        ProductoERP.subcategoria_id
    ).filter(
        ProductoERP.marca.isnot(None)
    ).distinct().all()

    # Construir estructura de relaciones
    marcas = set()
    categorias = set()
    subcategorias_ids = set()

    # Relaciones: qué categorías tiene cada marca, qué subcategorías tiene cada categoría
    categorias_por_marca = {}
    subcategorias_por_categoria = {}
    marcas_por_categoria = {}

    for combo in combinaciones:
        marca = combo.marca
        categoria = combo.categoria
        subcat_id = combo.subcategoria_id

        if marca:
            marcas.add(marca)
            if marca not in categorias_por_marca:
                categorias_por_marca[marca] = set()
            if categoria:
                categorias_por_marca[marca].add(categoria)

        if categoria:
            categorias.add(categoria)
            if categoria not in subcategorias_por_categoria:
                subcategorias_por_categoria[categoria] = set()
            if subcat_id:
                subcategorias_por_categoria[categoria].add(subcat_id)
            if categoria not in marcas_por_categoria:
                marcas_por_categoria[categoria] = set()
            if marca:
                marcas_por_categoria[categoria].add(marca)

        if subcat_id:
            subcategorias_ids.add(subcat_id)

    # Obtener nombres de subcategorías desde tb_subcategory
    from app.models.tb_subcategory import TBSubCategory
    subcategorias_info = {}
    if subcategorias_ids:
        subcats = db.query(TBSubCategory).filter(TBSubCategory.subcat_id.in_(subcategorias_ids)).all()
        for s in subcats:
            subcategorias_info[s.subcat_id] = s.subcat_desc

    # Convertir sets a listas ordenadas
    return {
        "marcas": sorted(list(marcas)),
        "categorias": sorted(list(categorias)),
        "subcategorias": [
            {"id": sid, "nombre": subcategorias_info.get(sid, f"Subcat {sid}")}
            for sid in sorted(subcategorias_ids)
        ],
        "categorias_por_marca": {m: sorted(list(cats)) for m, cats in categorias_por_marca.items()},
        "subcategorias_por_categoria": {c: sorted(list(subs)) for c, subs in subcategorias_por_categoria.items()},
        "marcas_por_categoria": {c: sorted(list(ms)) for c, ms in marcas_por_categoria.items()}
    }


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
            aplica_fuera=o.aplica_fuera if o.aplica_fuera is not None else True,
            aplica_tienda_nube=o.aplica_tienda_nube if o.aplica_tienda_nube is not None else True
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
                aplica_tienda_nube=offset.aplica_tienda_nube,
                usuario_id=current_user.id
            )
            db.add(nuevo_offset)
            offsets_creados.append(nuevo_offset)

        db.commit()
        for o in offsets_creados:
            db.refresh(o)

        return {"mensaje": f"Se crearon {len(offsets_creados)} offsets", "cantidad": len(offsets_creados)}

    # Validar que al menos un nivel esté definido para offset individual (solo si no es de grupo)
    niveles = [offset.marca, offset.categoria, offset.subcategoria_id, offset.item_id]
    niveles_definidos = [n for n in niveles if n is not None]

    # Si es offset de grupo, no necesita niveles individuales
    if offset.grupo_id:
        # Offset de grupo: no debe tener niveles individuales definidos
        if len(niveles_definidos) > 0:
            raise HTTPException(400, "Los offsets de grupo no deben especificar marca, categoría, subcategoría o producto individual")
    else:
        # Offset individual: debe tener exactamente un nivel
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
        aplica_tienda_nube=offset.aplica_tienda_nube,
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
        aplica_fuera=nuevo_offset.aplica_fuera if nuevo_offset.aplica_fuera is not None else True,
        aplica_tienda_nube=nuevo_offset.aplica_tienda_nube if nuevo_offset.aplica_tienda_nube is not None else True
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
    if offset_update.aplica_tienda_nube is not None:
        offset.aplica_tienda_nube = offset_update.aplica_tienda_nube

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
        aplica_fuera=offset.aplica_fuera if offset.aplica_fuera is not None else True,
        aplica_tienda_nube=offset.aplica_tienda_nube if offset.aplica_tienda_nube is not None else True
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
    costo_unitario: Optional[float] = None
    moneda_costo: Optional[str] = None


@router.get("/buscar-productos-erp")
async def buscar_productos_erp(
    q: str = Query(..., min_length=2, description="Buscar por código o descripción"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Busca productos en productos_erp por código o descripción, con costo actual"""
    query = """
    SELECT
        p.item_id,
        p.codigo,
        p.descripcion,
        p.marca,
        p.costo,
        p.moneda_costo
    FROM productos_erp p
    WHERE (p.codigo ILIKE :buscar OR p.descripcion ILIKE :buscar)
    ORDER BY p.codigo
    LIMIT 50
    """

    result = db.execute(text(query), {"buscar": f"%{q}%"}).fetchall()

    return [
        {
            "item_id": r.item_id,
            "codigo": r.codigo or str(r.item_id),
            "descripcion": r.descripcion or "",
            "marca": r.marca,
            "costo_unitario": float(r.costo) if r.costo else None,
            "moneda_costo": r.moneda_costo
        }
        for r in result
    ]


# ==================== ENDPOINTS PARA CONSUMO DE GRUPOS ====================

class OffsetGrupoConsumoResponse(BaseModel):
    id: int
    grupo_id: int
    grupo_nombre: Optional[str] = None
    id_operacion: Optional[int] = None
    venta_fuera_id: Optional[int] = None
    tipo_venta: str
    fecha_venta: str
    item_id: Optional[int] = None
    cantidad: int
    offset_id: int
    monto_offset_aplicado: float
    monto_offset_usd: Optional[float] = None
    cotizacion_dolar: Optional[float] = None

    class Config:
        from_attributes = True


class OffsetGrupoResumenResponse(BaseModel):
    id: int
    grupo_id: int
    grupo_nombre: str
    total_unidades: int
    total_monto_ars: float
    total_monto_usd: float
    cantidad_ventas: int
    limite_alcanzado: Optional[str] = None
    fecha_limite_alcanzado: Optional[str] = None
    # Límites del grupo (de los offsets)
    max_unidades: Optional[int] = None
    max_monto_usd: Optional[float] = None
    porcentaje_consumido_unidades: Optional[float] = None
    porcentaje_consumido_monto: Optional[float] = None

    class Config:
        from_attributes = True


@router.get("/offset-grupos/{grupo_id}/consumo")
async def obtener_consumo_grupo(
    grupo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el detalle de consumo de un grupo de offsets"""
    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(404, "Grupo no encontrado")

    # Obtener consumos del grupo
    consumos = db.query(OffsetGrupoConsumo).filter(
        OffsetGrupoConsumo.grupo_id == grupo_id
    ).order_by(OffsetGrupoConsumo.fecha_venta.desc()).limit(100).all()

    return {
        "grupo": {
            "id": grupo.id,
            "nombre": grupo.nombre,
            "descripcion": grupo.descripcion
        },
        "consumos": [
            {
                "id": c.id,
                "grupo_id": c.grupo_id,
                "id_operacion": c.id_operacion,
                "venta_fuera_id": c.venta_fuera_id,
                "tipo_venta": c.tipo_venta,
                "fecha_venta": c.fecha_venta.isoformat() if c.fecha_venta else None,
                "item_id": c.item_id,
                "cantidad": c.cantidad,
                "offset_id": c.offset_id,
                "monto_offset_aplicado": float(c.monto_offset_aplicado) if c.monto_offset_aplicado else 0,
                "monto_offset_usd": float(c.monto_offset_usd) if c.monto_offset_usd else None,
                "cotizacion_dolar": float(c.cotizacion_dolar) if c.cotizacion_dolar else None
            }
            for c in consumos
        ]
    }


@router.get("/offset-grupos-resumen")
async def obtener_resumen_grupos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el resumen de consumo de todos los grupos con límites"""
    # Obtener grupos que tienen offsets con límites
    grupos_con_limites = db.query(OffsetGrupo).join(
        OffsetGanancia, OffsetGrupo.id == OffsetGanancia.grupo_id
    ).filter(
        or_(
            OffsetGanancia.max_unidades.isnot(None),
            OffsetGanancia.max_monto_usd.isnot(None)
        )
    ).distinct().all()

    resultado = []
    for grupo in grupos_con_limites:
        # Obtener resumen si existe
        resumen = db.query(OffsetGrupoResumen).filter(
            OffsetGrupoResumen.grupo_id == grupo.id
        ).first()

        # Obtener límites del offset (asumimos que todos los offsets del grupo tienen el mismo límite)
        offset_con_limite = db.query(OffsetGanancia).filter(
            OffsetGanancia.grupo_id == grupo.id,
            or_(
                OffsetGanancia.max_unidades.isnot(None),
                OffsetGanancia.max_monto_usd.isnot(None)
            )
        ).first()

        max_unidades = offset_con_limite.max_unidades if offset_con_limite else None
        max_monto_usd = offset_con_limite.max_monto_usd if offset_con_limite else None

        if resumen:
            total_unidades = resumen.total_unidades or 0
            total_monto_usd = float(resumen.total_monto_usd or 0)

            resultado.append({
                "grupo_id": grupo.id,
                "grupo_nombre": grupo.nombre,
                "total_unidades": total_unidades,
                "total_monto_ars": float(resumen.total_monto_ars or 0),
                "total_monto_usd": total_monto_usd,
                "cantidad_ventas": resumen.cantidad_ventas or 0,
                "limite_alcanzado": resumen.limite_alcanzado,
                "fecha_limite_alcanzado": resumen.fecha_limite_alcanzado.isoformat() if resumen.fecha_limite_alcanzado else None,
                "max_unidades": max_unidades,
                "max_monto_usd": max_monto_usd,
                "porcentaje_consumido_unidades": (total_unidades / max_unidades * 100) if max_unidades else None,
                "porcentaje_consumido_monto": (total_monto_usd / max_monto_usd * 100) if max_monto_usd else None
            })
        else:
            resultado.append({
                "grupo_id": grupo.id,
                "grupo_nombre": grupo.nombre,
                "total_unidades": 0,
                "total_monto_ars": 0,
                "total_monto_usd": 0,
                "cantidad_ventas": 0,
                "limite_alcanzado": None,
                "fecha_limite_alcanzado": None,
                "max_unidades": max_unidades,
                "max_monto_usd": max_monto_usd,
                "porcentaje_consumido_unidades": 0 if max_unidades else None,
                "porcentaje_consumido_monto": 0 if max_monto_usd else None
            })

    return resultado


@router.post("/offset-grupos/{grupo_id}/recalcular")
async def recalcular_consumo_grupo(
    grupo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Recalcula el consumo de un grupo desde cero.
    Lee las ventas ML y fuera de ML y recalcula todo el consumo del grupo.
    Soporta tanto offsets con item_id directo como filtros de grupo (marca, categoría, etc.)
    """
    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(404, "Grupo no encontrado")

    # Eliminar consumos existentes del grupo
    db.query(OffsetGrupoConsumo).filter(OffsetGrupoConsumo.grupo_id == grupo_id).delete()

    # Obtener offsets del grupo
    offsets_grupo = db.query(OffsetGanancia).filter(
        OffsetGanancia.grupo_id == grupo_id
    ).all()

    if not offsets_grupo:
        return {"mensaje": "No hay offsets en este grupo", "consumos_creados": 0}

    # Obtener filtros del grupo
    filtros_grupo = db.query(OffsetGrupoFiltro).filter(
        OffsetGrupoFiltro.grupo_id == grupo_id
    ).all()

    print(f"[DEBUG] Grupo {grupo_id} - {len(filtros_grupo)} filtros encontrados:")
    for f in filtros_grupo:
        print(f"[DEBUG]   Filtro: marca={f.marca}, categoria={f.categoria}, item_id={f.item_id}")

    # Determinar fecha de inicio (la más antigua de los offsets)
    fecha_inicio = min(o.fecha_desde for o in offsets_grupo)
    print(f"[DEBUG] Fecha inicio: {fecha_inicio}")

    # Obtener item_ids directos de los offsets
    item_ids_directos = [o.item_id for o in offsets_grupo if o.item_id]

    # Obtener tipo cambio actual para conversiones
    tc_actual = db.query(CurExchHistory).order_by(CurExchHistory.ceh_cd.desc()).first()
    cotizacion = float(tc_actual.ceh_exchange) if tc_actual else 1000.0

    consumos_creados = 0
    total_unidades = 0
    total_monto_ars = 0
    total_monto_usd = 0
    operaciones_procesadas = set()  # Para evitar duplicados

    # Tomar el primer offset del grupo para obtener tipo y valores (asumimos todos tienen el mismo tipo)
    offset_ref = offsets_grupo[0]

    def calcular_monto_offset(offset, cantidad, costo, cot):
        """Calcula el monto del offset según su tipo"""
        if offset.tipo_offset == 'monto_fijo':
            monto_offset = float(offset.monto or 0)
            if offset.moneda == 'USD':
                return monto_offset * cot, monto_offset
            else:
                return monto_offset, monto_offset / cot if cot > 0 else 0
        elif offset.tipo_offset == 'monto_por_unidad':
            monto_por_u = float(offset.monto or 0)
            if offset.moneda == 'USD':
                return monto_por_u * cantidad * cot, monto_por_u * cantidad
            else:
                return monto_por_u * cantidad, monto_por_u * cantidad / cot if cot > 0 else 0
        elif offset.tipo_offset == 'porcentaje_costo':
            porcentaje = float(offset.porcentaje or 0)
            monto_ars = costo * (porcentaje / 100)
            return monto_ars, monto_ars / cot if cot > 0 else 0
        return 0, 0

    def venta_matchea_filtros(marca, categoria, item_id):
        """Verifica si una venta matchea con algún filtro del grupo"""
        if not filtros_grupo:
            return False
        for f in filtros_grupo:
            matchea = True
            if f.marca and f.marca != marca:
                matchea = False
            if f.categoria and f.categoria != categoria:
                matchea = False
            if f.item_id and f.item_id != item_id:
                matchea = False
            if matchea:
                return True
        return False

    # ============================================
    # Procesar ventas ML con item_ids directos
    # ============================================
    if item_ids_directos:
        ventas_ml_query = text("""
            SELECT
                m.id_operacion,
                m.fecha_venta,
                m.item_id,
                m.cantidad,
                m.costo_total_sin_iva,
                m.cotizacion_dolar,
                m.marca,
                m.categoria
            FROM ml_ventas_metricas m
            WHERE m.item_id = ANY(:item_ids)
            AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)

        ventas_ml = db.execute(ventas_ml_query, {
            "item_ids": item_ids_directos,
            "fecha_inicio": fecha_inicio
        }).fetchall()

        for venta in ventas_ml:
            offset_aplicable = next(
                (o for o in offsets_grupo if o.item_id == venta.item_id),
                None
            )
            if not offset_aplicable:
                continue

            cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
            costo = float(venta.costo_total_sin_iva) if venta.costo_total_sin_iva else 0
            monto_offset_ars, monto_offset_usd = calcular_monto_offset(offset_aplicable, venta.cantidad, costo, cot)

            if monto_offset_ars == 0 and monto_offset_usd == 0:
                continue

            consumo = OffsetGrupoConsumo(
                grupo_id=grupo_id,
                id_operacion=venta.id_operacion,
                tipo_venta='ml',
                fecha_venta=venta.fecha_venta,
                item_id=venta.item_id,
                cantidad=venta.cantidad,
                offset_id=offset_aplicable.id,
                monto_offset_aplicado=monto_offset_ars,
                monto_offset_usd=monto_offset_usd,
                cotizacion_dolar=cot
            )
            db.add(consumo)
            operaciones_procesadas.add(('ml', venta.id_operacion))
            consumos_creados += 1
            total_unidades += venta.cantidad
            total_monto_ars += monto_offset_ars
            total_monto_usd += monto_offset_usd

    # ============================================
    # Procesar ventas ML con filtros de grupo
    # ============================================
    if filtros_grupo:
        # Construir query dinámica basada en filtros
        condiciones_filtro = []
        for f in filtros_grupo:
            conds = []
            if f.marca:
                conds.append(f"m.marca = '{f.marca}'")
            if f.categoria:
                conds.append(f"m.categoria = '{f.categoria}'")
            if f.item_id:
                conds.append(f"m.item_id = {f.item_id}")
            if conds:
                condiciones_filtro.append(f"({' AND '.join(conds)})")

        if condiciones_filtro:
            where_filtros = " OR ".join(condiciones_filtro)
            print(f"[DEBUG] Ventas ML - WHERE: {where_filtros}")
            ventas_ml_filtros_query = text(f"""
                SELECT
                    m.id_operacion,
                    m.fecha_venta,
                    m.item_id,
                    m.cantidad,
                    m.costo_total_sin_iva,
                    m.cotizacion_dolar,
                    m.marca,
                    m.categoria
                FROM ml_ventas_metricas m
                WHERE ({where_filtros})
                AND m.fecha_venta >= :fecha_inicio
                ORDER BY m.fecha_venta
            """)

            ventas_ml_filtros = db.execute(ventas_ml_filtros_query, {
                "fecha_inicio": fecha_inicio
            }).fetchall()
            print(f"[DEBUG] Ventas ML encontradas: {len(ventas_ml_filtros)}")

            for venta in ventas_ml_filtros:
                # Skip si ya se procesó
                if ('ml', venta.id_operacion) in operaciones_procesadas:
                    continue

                cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
                costo = float(venta.costo_total_sin_iva) if venta.costo_total_sin_iva else 0
                monto_offset_ars, monto_offset_usd = calcular_monto_offset(offset_ref, venta.cantidad, costo, cot)

                if monto_offset_ars == 0 and monto_offset_usd == 0:
                    continue

                consumo = OffsetGrupoConsumo(
                    grupo_id=grupo_id,
                    id_operacion=venta.id_operacion,
                    tipo_venta='ml',
                    fecha_venta=venta.fecha_venta,
                    item_id=venta.item_id,
                    cantidad=venta.cantidad,
                    offset_id=offset_ref.id,
                    monto_offset_aplicado=monto_offset_ars,
                    monto_offset_usd=monto_offset_usd,
                    cotizacion_dolar=cot
                )
                db.add(consumo)
                operaciones_procesadas.add(('ml', venta.id_operacion))
                consumos_creados += 1
                total_unidades += venta.cantidad
                total_monto_ars += monto_offset_ars
                total_monto_usd += monto_offset_usd

    # ============================================
    # Procesar ventas fuera de ML con item_ids directos
    # ============================================
    if item_ids_directos:
        ventas_fuera_query = text("""
            SELECT
                v.id,
                v.fecha_venta,
                v.item_id,
                v.cantidad,
                v.costo_total,
                v.cotizacion_dolar,
                v.marca,
                v.categoria
            FROM ventas_fuera_ml_metricas v
            WHERE v.item_id = ANY(:item_ids)
            AND v.fecha_venta >= :fecha_inicio
            ORDER BY v.fecha_venta
        """)

        ventas_fuera = db.execute(ventas_fuera_query, {
            "item_ids": item_ids_directos,
            "fecha_inicio": fecha_inicio
        }).fetchall()

        for venta in ventas_fuera:
            offset_aplicable = next(
                (o for o in offsets_grupo if o.item_id == venta.item_id),
                None
            )
            if not offset_aplicable:
                continue

            cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
            costo = float(venta.costo_total) if venta.costo_total else 0
            monto_offset_ars, monto_offset_usd = calcular_monto_offset(offset_aplicable, venta.cantidad, costo, cot)

            if monto_offset_ars == 0 and monto_offset_usd == 0:
                continue

            consumo = OffsetGrupoConsumo(
                grupo_id=grupo_id,
                venta_fuera_id=venta.id,
                tipo_venta='fuera_ml',
                fecha_venta=venta.fecha_venta,
                item_id=venta.item_id,
                cantidad=venta.cantidad,
                offset_id=offset_aplicable.id,
                monto_offset_aplicado=monto_offset_ars,
                monto_offset_usd=monto_offset_usd,
                cotizacion_dolar=cot
            )
            db.add(consumo)
            operaciones_procesadas.add(('fuera', venta.id))
            consumos_creados += 1
            total_unidades += venta.cantidad
            total_monto_ars += monto_offset_ars
            total_monto_usd += monto_offset_usd

    # ============================================
    # Procesar ventas fuera de ML con filtros de grupo
    # ============================================
    if filtros_grupo:
        condiciones_filtro = []
        for f in filtros_grupo:
            conds = []
            if f.marca:
                conds.append(f"v.marca = '{f.marca}'")
            if f.categoria:
                conds.append(f"v.categoria = '{f.categoria}'")
            if f.item_id:
                conds.append(f"v.item_id = {f.item_id}")
            if conds:
                condiciones_filtro.append(f"({' AND '.join(conds)})")

        if condiciones_filtro:
            where_filtros = " OR ".join(condiciones_filtro)
            print(f"[DEBUG] Ventas fuera ML - WHERE: {where_filtros}")
            ventas_fuera_filtros_query = text(f"""
                SELECT
                    v.id,
                    v.fecha_venta,
                    v.item_id,
                    v.cantidad,
                    v.costo_total,
                    v.cotizacion_dolar,
                    v.marca,
                    v.categoria
                FROM ventas_fuera_ml_metricas v
                WHERE ({where_filtros})
                AND v.fecha_venta >= :fecha_inicio
                ORDER BY v.fecha_venta
            """)

            ventas_fuera_filtros = db.execute(ventas_fuera_filtros_query, {
                "fecha_inicio": fecha_inicio
            }).fetchall()
            print(f"[DEBUG] Ventas fuera ML encontradas: {len(ventas_fuera_filtros)}")

            for venta in ventas_fuera_filtros:
                if ('fuera', venta.id) in operaciones_procesadas:
                    continue

                cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
                costo = float(venta.costo_total) if venta.costo_total else 0
                monto_offset_ars, monto_offset_usd = calcular_monto_offset(offset_ref, venta.cantidad, costo, cot)

                if monto_offset_ars == 0 and monto_offset_usd == 0:
                    continue

                consumo = OffsetGrupoConsumo(
                    grupo_id=grupo_id,
                    venta_fuera_id=venta.id,
                    tipo_venta='fuera_ml',
                    fecha_venta=venta.fecha_venta,
                    item_id=venta.item_id,
                    cantidad=venta.cantidad,
                    offset_id=offset_ref.id,
                    monto_offset_aplicado=monto_offset_ars,
                    monto_offset_usd=monto_offset_usd,
                    cotizacion_dolar=cot
                )
                db.add(consumo)
                operaciones_procesadas.add(('fuera', venta.id))
                consumos_creados += 1
                total_unidades += venta.cantidad
                total_monto_ars += monto_offset_ars
                total_monto_usd += monto_offset_usd

    # Actualizar o crear resumen
    resumen = db.query(OffsetGrupoResumen).filter(
        OffsetGrupoResumen.grupo_id == grupo_id
    ).first()

    # Verificar si se alcanzó algún límite
    offset_con_limite = next(
        (o for o in offsets_grupo if o.max_unidades or o.max_monto_usd),
        None
    )

    limite_alcanzado = None
    if offset_con_limite:
        if offset_con_limite.max_unidades and total_unidades >= offset_con_limite.max_unidades:
            limite_alcanzado = 'unidades'
        elif offset_con_limite.max_monto_usd and total_monto_usd >= offset_con_limite.max_monto_usd:
            limite_alcanzado = 'monto'

    if resumen:
        resumen.total_unidades = total_unidades
        resumen.total_monto_ars = total_monto_ars
        resumen.total_monto_usd = total_monto_usd
        resumen.cantidad_ventas = consumos_creados
        resumen.limite_alcanzado = limite_alcanzado
    else:
        resumen = OffsetGrupoResumen(
            grupo_id=grupo_id,
            total_unidades=total_unidades,
            total_monto_ars=total_monto_ars,
            total_monto_usd=total_monto_usd,
            cantidad_ventas=consumos_creados,
            limite_alcanzado=limite_alcanzado
        )
        db.add(resumen)

    db.commit()

    return {
        "mensaje": f"Recálculo completado para grupo {grupo.nombre}",
        "consumos_creados": consumos_creados,
        "total_unidades": total_unidades,
        "total_monto_ars": total_monto_ars,
        "total_monto_usd": total_monto_usd,
        "limite_alcanzado": limite_alcanzado
    }


# ==================== ENDPOINTS PARA CONSUMO DE OFFSETS INDIVIDUALES ====================

@router.get("/offset-individuales-resumen")
async def obtener_resumen_offsets_individuales(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el resumen de consumo de todos los offsets individuales con límites"""
    # Obtener offsets individuales (sin grupo) que tienen límites
    offsets_con_limites = db.query(OffsetGanancia).filter(
        OffsetGanancia.grupo_id.is_(None),
        or_(
            OffsetGanancia.max_unidades.isnot(None),
            OffsetGanancia.max_monto_usd.isnot(None)
        )
    ).all()

    resultado = []
    for offset in offsets_con_limites:
        # Determinar nivel del offset
        if offset.item_id:
            nivel = "producto"
            nombre = f"Producto {offset.item_id}"
        elif offset.marca:
            nivel = "marca"
            nombre = offset.marca
        elif offset.categoria:
            nivel = "categoria"
            nombre = offset.categoria
        elif offset.subcategoria_id:
            nivel = "subcategoria"
            nombre = f"Subcategoría {offset.subcategoria_id}"
        else:
            nivel = "otro"
            nombre = "Offset"

        # Obtener resumen si existe
        resumen = db.query(OffsetIndividualResumen).filter(
            OffsetIndividualResumen.offset_id == offset.id
        ).first()

        if resumen:
            total_unidades = resumen.total_unidades or 0
            total_monto_usd = float(resumen.total_monto_usd or 0)

            resultado.append({
                "offset_id": offset.id,
                "descripcion": offset.descripcion or nombre,
                "nivel": nivel,
                "nombre_nivel": nombre,
                "total_unidades": total_unidades,
                "total_monto_ars": float(resumen.total_monto_ars or 0),
                "total_monto_usd": total_monto_usd,
                "cantidad_ventas": resumen.cantidad_ventas or 0,
                "limite_alcanzado": resumen.limite_alcanzado,
                "fecha_limite_alcanzado": resumen.fecha_limite_alcanzado.isoformat() if resumen.fecha_limite_alcanzado else None,
                "max_unidades": offset.max_unidades,
                "max_monto_usd": float(offset.max_monto_usd) if offset.max_monto_usd else None,
                "porcentaje_consumido_unidades": (total_unidades / offset.max_unidades * 100) if offset.max_unidades else None,
                "porcentaje_consumido_monto": (total_monto_usd / float(offset.max_monto_usd) * 100) if offset.max_monto_usd else None
            })
        else:
            resultado.append({
                "offset_id": offset.id,
                "descripcion": offset.descripcion or nombre,
                "nivel": nivel,
                "nombre_nivel": nombre,
                "total_unidades": 0,
                "total_monto_ars": 0,
                "total_monto_usd": 0,
                "cantidad_ventas": 0,
                "limite_alcanzado": None,
                "fecha_limite_alcanzado": None,
                "max_unidades": offset.max_unidades,
                "max_monto_usd": float(offset.max_monto_usd) if offset.max_monto_usd else None,
                "porcentaje_consumido_unidades": 0 if offset.max_unidades else None,
                "porcentaje_consumido_monto": 0 if offset.max_monto_usd else None
            })

    return resultado


@router.get("/offsets/{offset_id}/consumo")
async def obtener_consumo_offset_individual(
    offset_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el detalle de consumo de un offset individual"""
    offset = db.query(OffsetGanancia).filter(OffsetGanancia.id == offset_id).first()
    if not offset:
        raise HTTPException(404, "Offset no encontrado")

    # Determinar si es de grupo o individual
    if offset.grupo_id:
        # Es de grupo, obtener consumos del grupo
        consumos = db.query(OffsetGrupoConsumo).filter(
            OffsetGrupoConsumo.offset_id == offset_id
        ).order_by(OffsetGrupoConsumo.fecha_venta.desc()).limit(100).all()

        return {
            "offset": {
                "id": offset.id,
                "descripcion": offset.descripcion,
                "tipo": "grupo",
                "grupo_id": offset.grupo_id
            },
            "consumos": [
                {
                    "id": c.id,
                    "id_operacion": c.id_operacion,
                    "venta_fuera_id": c.venta_fuera_id,
                    "tipo_venta": c.tipo_venta,
                    "fecha_venta": c.fecha_venta.isoformat() if c.fecha_venta else None,
                    "item_id": c.item_id,
                    "cantidad": c.cantidad,
                    "monto_offset_aplicado": float(c.monto_offset_aplicado) if c.monto_offset_aplicado else 0,
                    "monto_offset_usd": float(c.monto_offset_usd) if c.monto_offset_usd else None
                }
                for c in consumos
            ]
        }
    else:
        # Es individual
        consumos = db.query(OffsetIndividualConsumo).filter(
            OffsetIndividualConsumo.offset_id == offset_id
        ).order_by(OffsetIndividualConsumo.fecha_venta.desc()).limit(100).all()

        return {
            "offset": {
                "id": offset.id,
                "descripcion": offset.descripcion,
                "tipo": "individual",
                "item_id": offset.item_id,
                "marca": offset.marca,
                "categoria": offset.categoria,
                "subcategoria_id": offset.subcategoria_id
            },
            "consumos": [
                {
                    "id": c.id,
                    "id_operacion": c.id_operacion,
                    "venta_fuera_id": c.venta_fuera_id,
                    "tipo_venta": c.tipo_venta,
                    "fecha_venta": c.fecha_venta.isoformat() if c.fecha_venta else None,
                    "item_id": c.item_id,
                    "cantidad": c.cantidad,
                    "monto_offset_aplicado": float(c.monto_offset_aplicado) if c.monto_offset_aplicado else 0,
                    "monto_offset_usd": float(c.monto_offset_usd) if c.monto_offset_usd else None
                }
                for c in consumos
            ]
        }


@router.post("/offsets/{offset_id}/recalcular")
async def recalcular_consumo_offset_individual(
    offset_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Recalcula el consumo de un offset individual desde cero."""
    offset = db.query(OffsetGanancia).filter(
        OffsetGanancia.id == offset_id,
        OffsetGanancia.grupo_id.is_(None)  # Solo offsets individuales
    ).first()

    if not offset:
        raise HTTPException(404, "Offset individual no encontrado")

    # Verificar que tenga límites
    if not offset.max_unidades and not offset.max_monto_usd:
        raise HTTPException(400, "Este offset no tiene límites configurados")

    # Eliminar consumos existentes
    db.query(OffsetIndividualConsumo).filter(
        OffsetIndividualConsumo.offset_id == offset_id
    ).delete()

    # Obtener cotización
    tc_actual = db.query(CurExchHistory).order_by(CurExchHistory.ceh_cd.desc()).first()
    cotizacion = float(tc_actual.ceh_exchange) if tc_actual else 1000.0

    fecha_inicio = offset.fecha_desde

    # Construir query según el nivel del offset
    if offset.item_id:
        ventas_query = text("""
            SELECT m.id_operacion, m.fecha_venta, m.item_id, m.cantidad,
                   m.costo_total_sin_iva, m.cotizacion_dolar
            FROM ml_ventas_metricas m
            WHERE m.item_id = :item_id AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)
        params = {"item_id": offset.item_id, "fecha_inicio": fecha_inicio}
    elif offset.marca and not offset.categoria and not offset.subcategoria_id:
        ventas_query = text("""
            SELECT m.id_operacion, m.fecha_venta, m.item_id, m.cantidad,
                   m.costo_total_sin_iva, m.cotizacion_dolar
            FROM ml_ventas_metricas m
            WHERE m.marca = :marca AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)
        params = {"marca": offset.marca, "fecha_inicio": fecha_inicio}
    elif offset.categoria and not offset.marca and not offset.subcategoria_id:
        ventas_query = text("""
            SELECT m.id_operacion, m.fecha_venta, m.item_id, m.cantidad,
                   m.costo_total_sin_iva, m.cotizacion_dolar
            FROM ml_ventas_metricas m
            WHERE m.categoria = :categoria AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)
        params = {"categoria": offset.categoria, "fecha_inicio": fecha_inicio}
    elif offset.subcategoria_id:
        ventas_query = text("""
            SELECT m.id_operacion, m.fecha_venta, m.item_id, m.cantidad,
                   m.costo_total_sin_iva, m.cotizacion_dolar
            FROM ml_ventas_metricas m
            WHERE m.subcategoria = (SELECT subcat_desc FROM tb_subcategory WHERE subcat_id = :subcat_id LIMIT 1)
            AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)
        params = {"subcat_id": offset.subcategoria_id, "fecha_inicio": fecha_inicio}
    else:
        raise HTTPException(400, "Offset sin criterio válido")

    ventas = db.execute(ventas_query, params).fetchall()

    consumos_creados = 0
    total_unidades = 0
    total_monto_ars = 0.0
    total_monto_usd = 0.0

    for venta in ventas:
        cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
        costo_unitario = (float(venta.costo_total_sin_iva) / venta.cantidad) if venta.cantidad and venta.costo_total_sin_iva else 0

        # Calcular monto según tipo de offset
        if offset.tipo_offset == 'monto_fijo':
            monto = float(offset.monto or 0)
            if offset.moneda == 'USD':
                monto_ars = monto * cot
                monto_usd = monto
            else:
                monto_ars = monto
                monto_usd = monto / cot if cot > 0 else 0
        elif offset.tipo_offset == 'monto_por_unidad':
            monto_por_u = float(offset.monto or 0)
            if offset.moneda == 'USD':
                monto_ars = monto_por_u * venta.cantidad * cot
                monto_usd = monto_por_u * venta.cantidad
            else:
                monto_ars = monto_por_u * venta.cantidad
                monto_usd = monto_por_u * venta.cantidad / cot if cot > 0 else 0
        elif offset.tipo_offset == 'porcentaje_costo':
            porcentaje = float(offset.porcentaje or 0)
            monto_ars = costo_unitario * venta.cantidad * (porcentaje / 100)
            monto_usd = monto_ars / cot if cot > 0 else 0
        else:
            continue

        consumo = OffsetIndividualConsumo(
            offset_id=offset_id,
            id_operacion=venta.id_operacion,
            tipo_venta='ml',
            fecha_venta=venta.fecha_venta,
            item_id=venta.item_id,
            cantidad=venta.cantidad,
            monto_offset_aplicado=monto_ars,
            monto_offset_usd=monto_usd,
            cotizacion_dolar=cot
        )
        db.add(consumo)
        consumos_creados += 1
        total_unidades += venta.cantidad
        total_monto_ars += monto_ars
        total_monto_usd += monto_usd

    # Actualizar o crear resumen
    resumen = db.query(OffsetIndividualResumen).filter(
        OffsetIndividualResumen.offset_id == offset_id
    ).first()

    limite_alcanzado = None
    if offset.max_unidades and total_unidades >= offset.max_unidades:
        limite_alcanzado = 'unidades'
    elif offset.max_monto_usd and total_monto_usd >= float(offset.max_monto_usd):
        limite_alcanzado = 'monto'

    if resumen:
        resumen.total_unidades = total_unidades
        resumen.total_monto_ars = total_monto_ars
        resumen.total_monto_usd = total_monto_usd
        resumen.cantidad_ventas = consumos_creados
        resumen.limite_alcanzado = limite_alcanzado
    else:
        resumen = OffsetIndividualResumen(
            offset_id=offset_id,
            total_unidades=total_unidades,
            total_monto_ars=total_monto_ars,
            total_monto_usd=total_monto_usd,
            cantidad_ventas=consumos_creados,
            limite_alcanzado=limite_alcanzado
        )
        db.add(resumen)

    db.commit()

    return {
        "mensaje": f"Recálculo completado para offset {offset.descripcion or offset.id}",
        "consumos_creados": consumos_creados,
        "total_unidades": total_unidades,
        "total_monto_ars": total_monto_ars,
        "total_monto_usd": total_monto_usd,
        "limite_alcanzado": limite_alcanzado
    }


@router.get("/offsets-con-limites-resumen")
async def obtener_resumen_todos_offsets_con_limites(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene un resumen combinado de todos los offsets con límites (grupos e individuales)"""
    resultado = {
        "grupos": [],
        "individuales": [],
        "totales": {
            "total_grupos": 0,
            "total_individuales": 0,
            "grupos_con_limite_alcanzado": 0,
            "individuales_con_limite_alcanzado": 0
        }
    }

    # Obtener grupos con límites
    grupos_con_limites = db.query(OffsetGrupo).join(
        OffsetGanancia, OffsetGrupo.id == OffsetGanancia.grupo_id
    ).filter(
        or_(
            OffsetGanancia.max_unidades.isnot(None),
            OffsetGanancia.max_monto_usd.isnot(None)
        )
    ).distinct().all()

    for grupo in grupos_con_limites:
        resumen = db.query(OffsetGrupoResumen).filter(
            OffsetGrupoResumen.grupo_id == grupo.id
        ).first()

        offset_limite = db.query(OffsetGanancia).filter(
            OffsetGanancia.grupo_id == grupo.id,
            or_(
                OffsetGanancia.max_unidades.isnot(None),
                OffsetGanancia.max_monto_usd.isnot(None)
            )
        ).first()

        grupo_info = {
            "tipo": "grupo",
            "id": grupo.id,
            "nombre": grupo.nombre,
            "total_unidades": resumen.total_unidades if resumen else 0,
            "total_monto_usd": float(resumen.total_monto_usd) if resumen and resumen.total_monto_usd else 0,
            "max_unidades": offset_limite.max_unidades if offset_limite else None,
            "max_monto_usd": float(offset_limite.max_monto_usd) if offset_limite and offset_limite.max_monto_usd else None,
            "limite_alcanzado": resumen.limite_alcanzado if resumen else None
        }
        resultado["grupos"].append(grupo_info)

        if resumen and resumen.limite_alcanzado:
            resultado["totales"]["grupos_con_limite_alcanzado"] += 1

    resultado["totales"]["total_grupos"] = len(grupos_con_limites)

    # Obtener offsets individuales con límites
    offsets_individuales = db.query(OffsetGanancia).filter(
        OffsetGanancia.grupo_id.is_(None),
        or_(
            OffsetGanancia.max_unidades.isnot(None),
            OffsetGanancia.max_monto_usd.isnot(None)
        )
    ).all()

    for offset in offsets_individuales:
        resumen = db.query(OffsetIndividualResumen).filter(
            OffsetIndividualResumen.offset_id == offset.id
        ).first()

        # Determinar nivel
        if offset.item_id:
            nivel = "producto"
        elif offset.marca:
            nivel = "marca"
        elif offset.categoria:
            nivel = "categoria"
        else:
            nivel = "subcategoria"

        offset_info = {
            "tipo": "individual",
            "id": offset.id,
            "descripcion": offset.descripcion,
            "nivel": nivel,
            "total_unidades": resumen.total_unidades if resumen else 0,
            "total_monto_usd": float(resumen.total_monto_usd) if resumen and resumen.total_monto_usd else 0,
            "max_unidades": offset.max_unidades,
            "max_monto_usd": float(offset.max_monto_usd) if offset.max_monto_usd else None,
            "limite_alcanzado": resumen.limite_alcanzado if resumen else None
        }
        resultado["individuales"].append(offset_info)

        if resumen and resumen.limite_alcanzado:
            resultado["totales"]["individuales_con_limite_alcanzado"] += 1

    resultado["totales"]["total_individuales"] = len(offsets_individuales)

    return resultado

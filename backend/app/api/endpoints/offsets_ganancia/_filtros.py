from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.usuario import Usuario
from app.api.deps import get_current_user
from app.services.permisos_service import verificar_permiso

from ._schemas import OffsetGrupoFiltroCreate

router = APIRouter()


@router.post("/offset-grupos/{grupo_id}/filtros")
def agregar_filtro_a_grupo(
    grupo_id: int,
    filtro: OffsetGrupoFiltroCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Agrega un filtro a un grupo existente"""
    if not verificar_permiso(db, current_user, "config.editar_constantes"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar offsets de ganancia")
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
        item_id=filtro.item_id,
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
        "producto_descripcion": nuevo_filtro.producto.descripcion if nuevo_filtro.producto else None,
    }


@router.delete("/offset-grupos/{grupo_id}/filtros/{filtro_id}")
def eliminar_filtro_de_grupo(
    grupo_id: int, filtro_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Elimina un filtro de un grupo"""
    if not verificar_permiso(db, current_user, "config.editar_constantes"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar offsets de ganancia")
    filtro = (
        db.query(OffsetGrupoFiltro)
        .filter(OffsetGrupoFiltro.id == filtro_id, OffsetGrupoFiltro.grupo_id == grupo_id)
        .first()
    )

    if not filtro:
        raise HTTPException(404, "Filtro no encontrado")

    db.delete(filtro)
    db.commit()
    return {"mensaje": "Filtro eliminado"}


@router.put("/offset-grupos/{grupo_id}/filtros")
def actualizar_filtros_grupo(
    grupo_id: int,
    filtros: List[OffsetGrupoFiltroCreate],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Reemplaza todos los filtros de un grupo con los nuevos"""
    if not verificar_permiso(db, current_user, "config.editar_constantes"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar offsets de ganancia")
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
            item_id=filtro_data.item_id,
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
                "producto_descripcion": f.producto.descripcion if f.producto else None,
            }
            for f in filtros_creados
        ],
    }


@router.get("/offset-grupos/{grupo_id}/filtros")
def obtener_filtros_grupo(
    grupo_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
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
            "producto_descripcion": f.producto.descripcion if f.producto else None,
        }
        for f in grupo.filtros
    ]


@router.get("/offset-filtros-opciones")
def obtener_opciones_filtros(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """
    Obtiene las opciones disponibles para filtros con sus relaciones.
    Devuelve marcas, categorías y subcategorías con información de relación
    para poder filtrar en cascada en el frontend.
    """
    from app.models.producto import ProductoERP

    # Obtener todas las combinaciones únicas de marca-categoría-subcategoría
    # No filtramos por activo para incluir todos los productos
    combinaciones = (
        db.query(ProductoERP.marca, ProductoERP.categoria, ProductoERP.subcategoria_id)
        .filter(ProductoERP.marca.isnot(None))
        .distinct()
        .all()
    )

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
            {"id": sid, "nombre": subcategorias_info.get(sid, f"Subcat {sid}")} for sid in sorted(subcategorias_ids)
        ],
        "categorias_por_marca": {m: sorted(list(cats)) for m, cats in categorias_por_marca.items()},
        "subcategorias_por_categoria": {c: sorted(list(subs)) for c, subs in subcategorias_por_categoria.items()},
        "marcas_por_categoria": {c: sorted(list(ms)) for c, ms in marcas_por_categoria.items()},
    }

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload
from typing import Dict, List, Optional

from app.core.database import get_db
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.sell_out import FK_SELL_OUT_CAMPANA_GRUPOS_GRUPO_ID, SellOutCampana, SellOutCampanaGrupo
from app.models.usuario import Usuario
from app.api.deps import get_current_user
from app.services.permisos_service import verificar_permiso
from app.services.sell_out.alcance import productos_con_cambio, productos_por_grupo

from ._schemas import (
    AlcanceGrupo,
    AlcancePrevio,
    AlcancePrevioIn,
    GruposEliminados,
    GruposEliminarIn,
    OffsetGrupoCreate,
    OffsetGrupoEditado,
    OffsetGrupoResponse,
    OffsetGrupoUpdate,
)

router = APIRouter()

PERMISO_GRUPOS = "config.editar_constantes"
# Reads the Grupos tab without editing it (owner: "hoy no existe un permiso para que se vean los grupos").
PERMISO_VER_GRUPOS = "grupos.ver"
_SIN_PERMISO = "No tienes permiso para gestionar offsets de ganancia"


_GRUPO_EN_SELL_OUT = (
    "El grupo está asignado a una campaña de sell out. Quite el grupo de la campaña antes de eliminarlo."
)


def _viola_fk_sell_out(exc: IntegrityError) -> bool:
    """True only when the violated constraint is the sell-out campaign FK to the group.

    Postgres (psycopg2) names it in `diag.constraint_name`; without it (e.g. SQLite) the
    constraint name has to appear in the driver message.
    """
    constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint_name is not None:
        return constraint_name == FK_SELL_OUT_CAMPANA_GRUPOS_GRUPO_ID
    return FK_SELL_OUT_CAMPANA_GRUPOS_GRUPO_ID in str(exc.orig)


def _motivos_para_conservar(db: Session, grupo_ids: List[int]) -> Dict[int, str]:
    """Why each group cannot be deleted, as the delete answers it; a group nothing holds is absent. Four queries
    whatever the number of groups, so the bulk delete reads them all at once."""
    # Verificar si tiene offsets asociados
    offsets = dict(
        db.query(OffsetGanancia.grupo_id, func.count(OffsetGanancia.id))
        .filter(OffsetGanancia.grupo_id.in_(grupo_ids))
        .group_by(OffsetGanancia.grupo_id)
    )
    # sell_out_campana_grupos points here with RESTRICT: answer clearly instead of a database error,
    # naming the active campaigns (a voided one also holds the group: the generic message)
    campanas: Dict[int, List[tuple]] = {}
    for grupo_id, nombre, estado in (
        db.query(SellOutCampanaGrupo.grupo_id, SellOutCampana.nombre, SellOutCampana.estado)
        .join(SellOutCampana, SellOutCampana.id == SellOutCampanaGrupo.campana_id)
        .filter(SellOutCampanaGrupo.grupo_id.in_(grupo_ids))
        .order_by(SellOutCampanaGrupo.grupo_id, SellOutCampana.nombre)
    ):
        campanas.setdefault(grupo_id, []).append((nombre, estado))
    # offset_grupo_consumo / offset_grupo_resumen record what the legacy offsets already applied in sales:
    # history, not a cache to drop, so the group stays (instead of the FK's 500).
    con_consumo = {
        gid
        for (gid,) in db.query(OffsetGrupoConsumo.grupo_id)
        .filter(OffsetGrupoConsumo.grupo_id.in_(grupo_ids))
        .distinct()
    } | {
        gid
        for (gid,) in db.query(OffsetGrupoResumen.grupo_id)
        .filter(OffsetGrupoResumen.grupo_id.in_(grupo_ids))
        .distinct()
    }
    motivos = {}
    for grupo_id in grupo_ids:
        motivo = _motivo(offsets.get(grupo_id, 0), campanas.get(grupo_id, []), grupo_id in con_consumo)
        if motivo:
            motivos[grupo_id] = motivo
    return motivos


def _motivo(offsets_count: int, estados: List[tuple], con_consumo: bool) -> Optional[str]:
    """The delete's answer from what holds the group, in the delete's order; None when nothing does."""
    if offsets_count > 0:
        return f"No se puede eliminar el grupo, tiene {offsets_count} offsets asociados"
    activas = [nombre for nombre, estado in estados if estado == "activa"]
    if activas:
        nombres = ", ".join(f"«{nombre}»" for nombre in activas)
        una = len(activas) == 1
        a_quien = "a la campaña de sell out activa" if una else "a las campañas de sell out activas"
        de_cual = "de la campaña" if una else "de las campañas"
        return f"El grupo está asignado {a_quien} {nombres}. Quite el grupo {de_cual} antes de eliminarlo."
    if estados:
        # History-safe: a voided campaign's link stays (its past results name the group), so the group stays too.
        anuladas = ", ".join(f"«{nombre}»" for nombre, _ in estados)
        a_cual = "a la campaña de sell out anulada" if len(estados) == 1 else "a las campañas de sell out anuladas"
        return (
            f"El grupo está vinculado {a_cual} {anuladas}. "
            "Queda guardado porque es parte de su historial: no se puede eliminar."
        )
    if con_consumo:
        return (
            "No se puede eliminar el grupo: tiene consumo de offsets registrado "
            "(el historial de lo que ya se aplicó en ventas)."
        )
    return None


@router.get("/offset-grupos", response_model=List[OffsetGrupoResponse])
def listar_grupos(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Lista los grupos de offsets con sus filtros; los ocultos (los de cada línea de un tactical) no."""
    grupos = db.query(OffsetGrupo).filter(OffsetGrupo.oculto.is_(False)).order_by(OffsetGrupo.nombre).all()

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
                "producto_descripcion": f.producto.descripcion if f.producto else None,
            }
            filtros_response.append(filtro_dict)

        resultado.append(
            {"id": grupo.id, "nombre": grupo.nombre, "descripcion": grupo.descripcion, "filtros": filtros_response}
        )

    return resultado


@router.get("/offset-grupos-alcance", response_model=List[AlcanceGrupo])
def alcance_grupos(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)) -> List[dict]:
    """Per group: how many products it reaches (the sell-out campaign rule) and the campaigns using it.
    Two queries whatever the number of groups (the Grupos panel of Sell in / Sell out). Read with `grupos.ver`, or
    with the permission that edits them."""
    if not (
        verificar_permiso(db, current_user, PERMISO_VER_GRUPOS) or verificar_permiso(db, current_user, PERMISO_GRUPOS)
    ):
        raise HTTPException(status_code=403, detail=_SIN_PERMISO)
    productos = productos_por_grupo(db)
    campanas: Dict[int, List[dict]] = {}
    rows = (
        db.query(OffsetGrupo.id, SellOutCampana.id, SellOutCampana.nombre, SellOutCampana.estado)
        .outerjoin(SellOutCampanaGrupo, SellOutCampanaGrupo.grupo_id == OffsetGrupo.id)
        .outerjoin(SellOutCampana, SellOutCampana.id == SellOutCampanaGrupo.campana_id)
        .filter(OffsetGrupo.oculto.is_(False))
        .order_by(OffsetGrupo.id, SellOutCampana.estado, SellOutCampana.fecha_desde.desc(), SellOutCampana.id)
    )
    for grupo_id, campana_id, nombre, estado in rows:
        lista = campanas.setdefault(grupo_id, [])
        if campana_id is not None:
            lista.append({"id": campana_id, "nombre": nombre, "estado": estado})
    return [{"grupo_id": gid, "productos": productos.get(gid, 0), "campanas": lista} for gid, lista in campanas.items()]


@router.post("/offset-grupos/{grupo_id}/alcance-previo", response_model=AlcancePrevio)
def alcance_previo(
    grupo_id: int,
    cambio: AlcancePrevioIn,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Products the group reaches now and with one filter row added and/or removed, without saving: the Grupos
    panel shows it before a filter change re-queues the active campaigns that use the group."""
    if not verificar_permiso(db, current_user, PERMISO_GRUPOS):
        raise HTTPException(status_code=403, detail=_SIN_PERMISO)
    if not db.query(OffsetGrupo.id).filter(OffsetGrupo.id == grupo_id, OffsetGrupo.oculto.is_(False)).first():
        raise HTTPException(404, "Grupo no encontrado")
    agregar = cambio.agregar.model_dump() if cambio.agregar else None
    return {
        "antes": productos_con_cambio(db, grupo_id),
        "despues": productos_con_cambio(db, grupo_id, agregar, cambio.quitar_filtro_id),
    }


@router.patch("/offset-grupos/{grupo_id}", response_model=OffsetGrupoEditado)
def editar_grupo(
    grupo_id: int,
    cambios: OffsetGrupoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Renombra o describe un grupo (sus filtros se editan aparte)."""
    if not verificar_permiso(db, current_user, PERMISO_GRUPOS):
        raise HTTPException(status_code=403, detail=_SIN_PERMISO)
    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id, OffsetGrupo.oculto.is_(False)).first()
    if not grupo:
        raise HTTPException(404, "Grupo no encontrado")
    if "nombre" in cambios.model_fields_set:
        nombre = (cambios.nombre or "").strip()
        if not nombre:
            raise HTTPException(422, "El nombre del grupo no puede quedar vacío.")
        grupo.nombre = nombre
    if "descripcion" in cambios.model_fields_set:
        grupo.descripcion = (cambios.descripcion or "").strip() or None
    db.commit()
    return {"id": grupo.id, "nombre": grupo.nombre, "descripcion": grupo.descripcion}


@router.post("/offset-grupos")
def crear_grupo(
    grupo: OffsetGrupoCreate, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Crea un nuevo grupo de offsets con filtros opcionales"""
    if not verificar_permiso(db, current_user, "config.editar_constantes"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar offsets de ganancia")
    nuevo_grupo = OffsetGrupo(nombre=grupo.nombre, descripcion=grupo.descripcion, usuario_id=current_user.id)
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
                item_id=filtro_data.item_id,
            )
            db.add(nuevo_filtro)
            filtros_creados.append(nuevo_filtro)

    db.commit()
    db.refresh(nuevo_grupo)

    # Construir respuesta
    filtros_response = []
    for f in nuevo_grupo.filtros:
        filtros_response.append(
            {
                "id": f.id,
                "grupo_id": f.grupo_id,
                "marca": f.marca,
                "categoria": f.categoria,
                "subcategoria_id": f.subcategoria_id,
                "item_id": f.item_id,
                "producto_descripcion": f.producto.descripcion if f.producto else None,
            }
        )

    return {
        "id": nuevo_grupo.id,
        "nombre": nuevo_grupo.nombre,
        "descripcion": nuevo_grupo.descripcion,
        "filtros": filtros_response,
    }


@router.delete("/offset-grupos/{grupo_id}")
def eliminar_grupo(grupo_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Elimina un grupo de offsets (solo si no tiene offsets asociados)"""
    if not verificar_permiso(db, current_user, "config.editar_constantes"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar offsets de ganancia")
    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id, OffsetGrupo.oculto.is_(False)).first()
    if not grupo:
        raise HTTPException(404, "Grupo no encontrado")

    motivo = _motivos_para_conservar(db, [grupo_id]).get(grupo_id)
    if motivo:
        raise HTTPException(400, motivo)

    # Los filtros se eliminan automáticamente por el cascade
    db.delete(grupo)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # A campaign linked between the check above and this commit: the RESTRICT FK stops it.
        # Any other constraint is a real error, not a sell-out conflict.
        if not _viola_fk_sell_out(exc):
            raise
        raise HTTPException(400, _GRUPO_EN_SELL_OUT) from exc
    return {"mensaje": "Grupo eliminado"}


@router.post("/offset-grupos/eliminar", response_model=GruposEliminados)
def eliminar_grupos(
    pedido: GruposEliminarIn, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> dict:
    """Deletes at once every group the single delete would delete; each other one stays, with the single delete's
    reason. A campaign that takes a group meanwhile keeps only that group (its RESTRICT FK, one savepoint each)."""
    if not verificar_permiso(db, current_user, PERMISO_GRUPOS):
        raise HTTPException(status_code=403, detail=_SIN_PERMISO)
    ids = list(dict.fromkeys(pedido.ids))
    # A tactical line's hidden group is not the tab's to delete: it answers as unknown.
    grupos = {
        g.id: g
        for g in db.query(OffsetGrupo)
        .options(selectinload(OffsetGrupo.filtros))  # the delete cascades to them: loaded once, not per group
        .filter(OffsetGrupo.id.in_(ids), OffsetGrupo.oculto.is_(False))
    }
    motivos = _motivos_para_conservar(db, list(grupos))
    eliminados: List[int] = []
    rechazados: List[dict] = []
    for grupo_id in ids:
        grupo = grupos.get(grupo_id)
        if grupo is None:
            rechazados.append({"id": grupo_id, "nombre": None, "motivo": "Grupo no encontrado"})
            continue
        motivo = motivos.get(grupo_id)
        if motivo is None:
            punto = db.begin_nested()
            try:
                db.delete(grupo)
                db.flush()
                punto.commit()
                eliminados.append(grupo_id)
                continue
            except IntegrityError as exc:
                punto.rollback()
                if not _viola_fk_sell_out(exc):
                    raise
                motivo = _GRUPO_EN_SELL_OUT
        rechazados.append({"id": grupo_id, "nombre": grupo.nombre, "motivo": motivo})
    db.commit()
    return {"eliminados": eliminados, "rechazados": rechazados}

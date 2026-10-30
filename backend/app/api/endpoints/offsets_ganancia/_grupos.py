from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import Dict, List

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
    OffsetGrupoCreate,
    OffsetGrupoEditado,
    OffsetGrupoResponse,
    OffsetGrupoUpdate,
)

router = APIRouter()

PERMISO_GRUPOS = "config.editar_constantes"
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


@router.get("/offset-grupos", response_model=List[OffsetGrupoResponse])
def listar_grupos(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
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
    Two queries whatever the number of groups (the Grupos panel of Sell in / Sell out)."""
    if not verificar_permiso(db, current_user, PERMISO_GRUPOS):
        raise HTTPException(status_code=403, detail=_SIN_PERMISO)
    productos = productos_por_grupo(db)
    campanas: Dict[int, List[dict]] = {}
    rows = (
        db.query(OffsetGrupo.id, SellOutCampana.id, SellOutCampana.nombre, SellOutCampana.estado)
        .outerjoin(SellOutCampanaGrupo, SellOutCampanaGrupo.grupo_id == OffsetGrupo.id)
        .outerjoin(SellOutCampana, SellOutCampana.id == SellOutCampanaGrupo.campana_id)
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
    if not db.query(OffsetGrupo.id).filter(OffsetGrupo.id == grupo_id).first():
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
    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id).first()
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
    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(404, "Grupo no encontrado")

    # Verificar si tiene offsets asociados
    offsets_count = db.query(OffsetGanancia).filter(OffsetGanancia.grupo_id == grupo_id).count()
    if offsets_count > 0:
        raise HTTPException(400, f"No se puede eliminar el grupo, tiene {offsets_count} offsets asociados")

    # sell_out_campana_grupos points here with RESTRICT: answer clearly instead of a database error,
    # naming the active campaigns (a voided one also holds the group: the generic message)
    estados = (
        db.query(SellOutCampana.nombre, SellOutCampana.estado)
        .join(SellOutCampanaGrupo, SellOutCampanaGrupo.campana_id == SellOutCampana.id)
        .filter(SellOutCampanaGrupo.grupo_id == grupo_id)
        .order_by(SellOutCampana.nombre)
        .all()
    )
    activas = [nombre for nombre, estado in estados if estado == "activa"]
    if activas:
        nombres = ", ".join(f"«{nombre}»" for nombre in activas)
        una = len(activas) == 1
        a_quien = "a la campaña de sell out activa" if una else "a las campañas de sell out activas"
        de_cual = "de la campaña" if una else "de las campañas"
        raise HTTPException(
            400, f"El grupo está asignado {a_quien} {nombres}. Quite el grupo {de_cual} antes de eliminarlo."
        )
    if estados:
        # History-safe: a voided campaign's link stays (its past results name the group), so the group stays too.
        anuladas = ", ".join(f"«{nombre}»" for nombre, _ in estados)
        a_cual = "a la campaña de sell out anulada" if len(estados) == 1 else "a las campañas de sell out anuladas"
        raise HTTPException(
            400,
            f"El grupo está vinculado {a_cual} {anuladas}. "
            "Queda guardado porque es parte de su historial: no se puede eliminar.",
        )

    # offset_grupo_consumo / offset_grupo_resumen record what the legacy offsets already applied in sales:
    # history, not a cache to drop, so the group stays (instead of the FK's 500).
    consumo = db.query(OffsetGrupoConsumo.id).filter(OffsetGrupoConsumo.grupo_id == grupo_id).first()
    resumen = db.query(OffsetGrupoResumen.id).filter(OffsetGrupoResumen.grupo_id == grupo_id).first()
    if consumo or resumen:
        raise HTTPException(
            400,
            "No se puede eliminar el grupo: tiene consumo de offsets registrado "
            "(el historial de lo que ya se aplicó en ventas).",
        )

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

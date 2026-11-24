from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import date

from app.core.database import get_db
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.sell_out import SellOutCampana
from app.models.usuario import Usuario
from app.api.deps import get_current_user
from app.routers.sell_in_compras import aprobar_o_409, requiere_aprobar
from app.services.permisos_service import verificar_permiso
from app.services.sell_in import aprobacion

from ._schemas import OffsetGananciaCreate, OffsetGananciaUpdate, OffsetGananciaResponse

router = APIRouter()


def _validar_offset_negativo_sin_limite(
    tipo_offset: Optional[str],
    monto: Optional[float],
    porcentaje: Optional[float],
    max_unidades: Optional[int],
    max_monto_usd: Optional[float],
) -> None:
    """A negative-valued offset (of any tipo_offset) may not carry a consumption limit.

    This capless-by-construction invariant is what keeps negative offsets away from
    the ``max(0, ...)`` availability clamps in the rentabilidad endpoints. The sign
    lives in ``monto`` for monto_fijo/monto_por_unidad and in ``porcentaje`` for
    porcentaje_costo, so we pick the field by tipo_offset.
    """
    tipo = tipo_offset or "monto_fijo"
    if tipo == "porcentaje_costo":
        es_negativo = porcentaje is not None and porcentaje < 0
    else:  # monto_fijo, monto_por_unidad
        es_negativo = monto is not None and monto < 0

    # `is not None`, not truthiness: max_unidades/max_monto_usd == 0 is still a
    # limit as far as the rentabilidad endpoints see it (they check `is not None`),
    # and POST does not normalize 0 -> None like PUT does. Truthiness would let a
    # negative offset with a 0-limit slip through into the max(0, ...) clamp path.
    if es_negativo and (max_unidades is not None or max_monto_usd is not None):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Un offset con valor negativo (tipo '{tipo}') no puede tener "
                "límites de consumo (max_unidades / max_monto_usd). Los offsets "
                "negativos se aplican siempre en su totalidad."
            ),
        )


# What an offset applies (tacticals approval S10): an edit of any of these sends an approved offset back to
# `pendiente`; the description alone does not.
_DINERO = (
    "marca",
    "categoria",
    "subcategoria_id",
    "item_id",
    "tipo_offset",
    "monto",
    "moneda",
    "tipo_cambio",
    "porcentaje",
    "fecha_desde",
    "fecha_hasta",
    "grupo_id",
    "max_unidades",
    "max_monto_usd",
    "aplica_ml",
    "aplica_fuera",
    "aplica_tienda_nube",
)


def _dinero(offset: OffsetGanancia) -> dict:
    return {campo: getattr(offset, campo) for campo in _DINERO}


def _respuesta(db: Session, o: OffsetGanancia) -> OffsetGananciaResponse:
    return OffsetGananciaResponse(
        id=o.id,
        marca=o.marca,
        categoria=o.categoria,
        subcategoria_id=o.subcategoria_id,
        item_id=o.item_id,
        tipo_offset=o.tipo_offset or "monto_fijo",
        monto=o.monto,
        moneda=o.moneda or "ARS",
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
        monto_consumido=o.monto_consumido,
        aplica_ml=o.aplica_ml if o.aplica_ml is not None else True,
        aplica_fuera=o.aplica_fuera if o.aplica_fuera is not None else True,
        aplica_tienda_nube=o.aplica_tienda_nube if o.aplica_tienda_nube is not None else True,
        campana_id=_campanas_por_offset(db, [o.id]).get(o.id),
        estado=o.estado,
    )


def _campanas_por_offset(db: Session, offset_ids: List[int]) -> dict:
    """Sell-out campaign each offset was migrated to (T15), by offset id."""
    if not offset_ids:
        return {}
    rows = (
        db.query(SellOutCampana.offset_origen_id, SellOutCampana.id)
        .filter(SellOutCampana.offset_origen_id.in_(offset_ids))
        .all()
    )
    return dict(rows)


@router.get("/offsets-ganancia", response_model=List[OffsetGananciaResponse])
def listar_offsets(
    marca: Optional[str] = None,
    categoria: Optional[str] = None,
    subcategoria_id: Optional[int] = None,
    item_id: Optional[int] = None,
    grupo_id: Optional[int] = None,
    solo_vigentes: bool = False,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
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
            OffsetGanancia.estado == aprobacion.ACTIVA,  # a pending offset applies to nothing (S10)
            and_(
                OffsetGanancia.fecha_desde <= hoy,
                or_(OffsetGanancia.fecha_hasta.is_(None), OffsetGanancia.fecha_hasta >= hoy),
            ),
        )

    offsets = query.order_by(OffsetGanancia.fecha_creacion.desc()).all()
    campanas = _campanas_por_offset(db, [o.id for o in offsets])

    return [
        OffsetGananciaResponse(
            id=o.id,
            marca=o.marca,
            categoria=o.categoria,
            subcategoria_id=o.subcategoria_id,
            item_id=o.item_id,
            tipo_offset=o.tipo_offset or "monto_fijo",
            monto=o.monto,
            moneda=o.moneda or "ARS",
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
            monto_consumido=o.monto_consumido,
            aplica_ml=o.aplica_ml if o.aplica_ml is not None else True,
            aplica_fuera=o.aplica_fuera if o.aplica_fuera is not None else True,
            aplica_tienda_nube=o.aplica_tienda_nube if o.aplica_tienda_nube is not None else True,
            campana_id=campanas.get(o.id),
            estado=o.estado,
        )
        for o in offsets
    ]


@router.post("/offsets-ganancia")
def crear_offset(
    offset: OffsetGananciaCreate, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Crea un nuevo offset de ganancia. Si se pasan múltiples item_ids, crea uno por cada producto. Queda
    `pendiente` (tacticals approval S10): no aplica a nada hasta que se aprueba (`POST .../{id}/aprobar`)."""
    if not verificar_permiso(db, current_user, "config.editar_constantes"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar offsets de ganancia")
    # Validar tipo de offset
    if offset.tipo_offset == "porcentaje_costo" and offset.porcentaje is None:
        raise HTTPException(400, "Debe especificar el porcentaje para tipo porcentaje_costo")
    if offset.tipo_offset in ["monto_fijo", "monto_por_unidad"] and offset.monto is None:
        raise HTTPException(400, "Debe especificar el monto para este tipo de offset")

    # Un offset de valor negativo no puede tener límites de consumo (guarda ambos
    # caminos: multi-item y offset individual).
    _validar_offset_negativo_sin_limite(
        offset.tipo_offset, offset.monto, offset.porcentaje, offset.max_unidades, offset.max_monto_usd
    )

    # Validar grupo si se especifica
    if offset.grupo_id:
        grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == offset.grupo_id, OffsetGrupo.oculto.is_(False)).first()
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
                usuario_id=current_user.id,
                estado=aprobacion.PENDIENTE,
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
            raise HTTPException(
                400, "Los offsets de grupo no deben especificar marca, categoría, subcategoría o producto individual"
            )
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
        usuario_id=current_user.id,
        estado=aprobacion.PENDIENTE,
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
        tipo_offset=nuevo_offset.tipo_offset or "monto_fijo",
        monto=nuevo_offset.monto,
        moneda=nuevo_offset.moneda or "ARS",
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
        monto_consumido=nuevo_offset.monto_consumido,
        aplica_ml=nuevo_offset.aplica_ml if nuevo_offset.aplica_ml is not None else True,
        aplica_fuera=nuevo_offset.aplica_fuera if nuevo_offset.aplica_fuera is not None else True,
        aplica_tienda_nube=nuevo_offset.aplica_tienda_nube if nuevo_offset.aplica_tienda_nube is not None else True,
        estado=nuevo_offset.estado,
    )


@router.put("/offsets-ganancia/{offset_id}", response_model=OffsetGananciaResponse)
def actualizar_offset(
    offset_id: int,
    offset_update: OffsetGananciaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Actualiza un offset existente. Si cambia lo que aplica (todo menos la descripción) y estaba aprobado, vuelve a
    `pendiente` (tacticals approval S10)."""
    if not verificar_permiso(db, current_user, "config.editar_constantes"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar offsets de ganancia")
    # Locked: an approval running at the same time waits for this edit (and sees it), instead of approving the old
    # values the edit then overwrites (S10).
    offset = db.query(OffsetGanancia).filter(OffsetGanancia.id == offset_id).with_for_update().first()

    if not offset:
        raise HTTPException(404, "Offset no encontrado")
    antes = _dinero(offset)

    # Si se actualiza el nivel de aplicación, limpiar los otros niveles
    # Solo uno debe tener valor a la vez
    niveles_enviados = [
        offset_update.marca is not None,
        offset_update.categoria is not None,
        offset_update.subcategoria_id is not None,
        offset_update.item_id is not None,
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
            grupo = (
                db.query(OffsetGrupo)
                .filter(OffsetGrupo.id == offset_update.grupo_id, OffsetGrupo.oculto.is_(False))
                .first()
            )
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

    # Revalidar con los valores efectivos post-merge: atrapa toda ruta que deje el
    # offset en negativo + límite (volver negativo el monto/porcentaje, switchear
    # tipo_offset sobre un campo negativo, o agregar un límite a un negativo).
    _validar_offset_negativo_sin_limite(
        offset.tipo_offset, offset.monto, offset.porcentaje, offset.max_unidades, offset.max_monto_usd
    )
    # Flushed first: the send-back reloads the row locked (`populate_existing`), and production sessions do not
    # autoflush, so an unflushed edit would be thrown away and only `pendiente` stored.
    db.flush()
    aprobacion.a_pendiente_si_cambia(db, offset, antes, _dinero(offset), (), current_user.id)

    db.commit()
    db.refresh(offset)

    return OffsetGananciaResponse(
        id=offset.id,
        marca=offset.marca,
        categoria=offset.categoria,
        subcategoria_id=offset.subcategoria_id,
        item_id=offset.item_id,
        tipo_offset=offset.tipo_offset or "monto_fijo",
        monto=offset.monto,
        moneda=offset.moneda or "ARS",
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
        monto_consumido=offset.monto_consumido,
        aplica_ml=offset.aplica_ml if offset.aplica_ml is not None else True,
        aplica_fuera=offset.aplica_fuera if offset.aplica_fuera is not None else True,
        aplica_tienda_nube=offset.aplica_tienda_nube if offset.aplica_tienda_nube is not None else True,
        campana_id=_campanas_por_offset(db, [offset.id]).get(offset.id),
        estado=offset.estado,
    )


@router.post("/offsets-ganancia/{offset_id}/aprobar", response_model=OffsetGananciaResponse)
def aprobar_offset(offset_id: int, user: Usuario = Depends(requiere_aprobar), db: Session = Depends(get_db)):
    """Approve a pending offset (tacticals approval S10): it starts applying to rentabilidad and to the consumption
    of the sales that come next. `tacticals.aprobar`; 409 when it is already approved."""
    return _respuesta(db, aprobar_o_409(db, OffsetGanancia, offset_id, user.id))


@router.delete("/offsets-ganancia/{offset_id}")
def eliminar_offset(offset_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Elimina un offset"""
    if not verificar_permiso(db, current_user, "config.editar_constantes"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar offsets de ganancia")
    offset = db.query(OffsetGanancia).filter(OffsetGanancia.id == offset_id).first()

    if not offset:
        raise HTTPException(404, "Offset no encontrado")

    db.delete(offset)
    db.commit()

    return {"mensaje": "Offset eliminado"}

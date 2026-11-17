"""Mass undo of logistics changes: a selection of labels (S2) or a whole bulk assignment (S3).

Both apply the single undo rule (`motivo_no_deshacer_con`) label by label: a label goes back to the
`logistica_anterior_id` of the change being undone, only while it still holds that change's `logistica_nueva_id` and
the logística it would put back is active (or NULL). Labels that fail it are skipped and reported with the reason;
the others change in the same transaction, recorded by the history trigger with origen "deshacer".

A bulk assignment has no id of its own: the trigger stamps every row of one `asignar-masivo` UPDATE with the same
`cambiado_en` (`now()` is the transaction start), the same user and the same target, all with origen "masivo". That
group is the operation, and its smallest history id is the operation id. It works for the history recorded before
this module existed, so bulk mistakes made earlier can be reverted too.
"""

from collections import defaultdict
from typing import Dict, List, Optional, Set

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.etiqueta_envio_logistica_historial import EtiquetaEnvioLogisticaHistorial
from app.models.logistica import Logistica
from app.models.usuario import Usuario
from app.services.etiquetas.logistica_historial_consulta import motivo_no_deshacer_con
from app.services.etiquetas.logistica_historial_origen import marcar_origen_logistica

_Historial = EtiquetaEnvioLogisticaHistorial

ORIGEN_MASIVO = "masivo"
LIMITE_OPERACIONES = 30

NO_EXISTE = "La etiqueta no existe."
CAMBIO_POSTERIOR = "La etiqueta cambió de logística después de esta operación."


class Resultado:
    """Labels reverted and labels skipped, grouped by reason."""

    def __init__(self) -> None:
        self.revertidas: List[str] = []
        self.no_revertidas: Dict[str, List[str]] = defaultdict(list)

    def a_dict(self) -> dict:
        motivos = [
            {"motivo": motivo, "cantidad": len(ids), "shipping_ids": sorted(ids)}
            for motivo, ids in sorted(self.no_revertidas.items(), key=lambda m: (-len(m[1]), m[0]))
        ]
        return {
            "revertidas": len(self.revertidas),
            "no_revertidas": sum(m["cantidad"] for m in motivos),
            "no_revertidas_por_motivo": motivos,
        }


def _bloquear(db: Session, shipping_ids: Set[str]) -> Dict[str, EtiquetaEnvio]:
    # Row locks in a fixed order: a concurrent undo or assignment of the same labels waits instead of racing the check.
    etiquetas = (
        db.query(EtiquetaEnvio)
        .filter(EtiquetaEnvio.shipping_id.in_(shipping_ids))
        .order_by(EtiquetaEnvio.shipping_id)
        .with_for_update(of=EtiquetaEnvio)
        .all()
    )
    return {e.shipping_id: e for e in etiquetas}


def _ultimos_cambios(db: Session, shipping_ids: Set[str]) -> Dict[str, EtiquetaEnvioLogisticaHistorial]:
    """Latest history row of each label (same order as `ultimo_cambio`), in one query."""
    orden = (
        func.row_number()
        .over(partition_by=_Historial.shipping_id, order_by=(_Historial.cambiado_en.desc(), _Historial.id.desc()))
        .label("orden")
    )
    sub = db.query(_Historial.id, orden).filter(_Historial.shipping_id.in_(shipping_ids)).subquery()
    filas = db.query(_Historial).join(sub, sub.c.id == _Historial.id).filter(sub.c.orden == 1).all()
    return {h.shipping_id: h for h in filas}


def _activas(db: Session) -> Set[int]:
    return {id_ for (id_,) in db.query(Logistica.id).filter(Logistica.activa.is_(True)).all()}


def _aplicar(
    db: Session,
    destinos: Dict[str, Optional[int]],
    etiquetas: Dict[str, EtiquetaEnvio],
    usuario_id: int,
    operador_id: Optional[int],
) -> None:
    if not destinos:
        return
    marcar_origen_logistica(db, "deshacer", usuario_id=usuario_id, operador_id=operador_id)
    for shipping_id, destino in destinos.items():
        etiquetas[shipping_id].logistica_id = destino


def deshacer_seleccion(
    db: Session, shipping_ids: List[str], usuario_id: int, operador_id: Optional[int] = None
) -> Resultado:
    """S2: undo the last change of each selected label (flushed, not committed)."""
    pedidas = set(shipping_ids)
    etiquetas = _bloquear(db, pedidas)
    ultimos = _ultimos_cambios(db, set(etiquetas))
    activas = _activas(db)

    resultado = Resultado()
    destinos: Dict[str, Optional[int]] = {}
    for shipping_id in sorted(pedidas):
        etiqueta = etiquetas.get(shipping_id)
        if etiqueta is None:
            resultado.no_revertidas[NO_EXISTE].append(shipping_id)
            continue
        ultimo = ultimos.get(shipping_id)
        motivo = motivo_no_deshacer_con(etiqueta.logistica_id, ultimo, activas)
        if motivo is not None:
            resultado.no_revertidas[motivo].append(shipping_id)
            continue
        destinos[shipping_id] = ultimo.logistica_anterior_id
        resultado.revertidas.append(shipping_id)

    _aplicar(db, destinos, etiquetas, usuario_id, operador_id)
    db.flush()
    return resultado


def listar_operaciones(db: Session, limite: int = LIMITE_OPERACIONES) -> List[dict]:
    """S3: the latest bulk assignments, newest first: who, when, target logística and how many labels changed."""
    grupos = (
        db.query(
            func.min(_Historial.id).label("id"),
            _Historial.usuario_id,
            _Historial.cambiado_en,
            _Historial.logistica_nueva_id,
            func.count(_Historial.id).label("etiquetas"),
        )
        .filter(_Historial.origen == ORIGEN_MASIVO)
        .group_by(_Historial.usuario_id, _Historial.cambiado_en, _Historial.logistica_nueva_id)
        .order_by(_Historial.cambiado_en.desc(), func.min(_Historial.id).desc())
        .limit(limite)
        .subquery()
    )
    filas = (
        db.query(
            grupos.c.id,
            grupos.c.cambiado_en,
            grupos.c.logistica_nueva_id,
            grupos.c.etiquetas,
            Usuario.nombre.label("usuario_nombre"),
            Logistica.nombre.label("logistica_nombre"),
            Logistica.color.label("logistica_color"),
        )
        .outerjoin(Usuario, Usuario.id == grupos.c.usuario_id)
        .outerjoin(Logistica, Logistica.id == grupos.c.logistica_nueva_id)
        .order_by(grupos.c.cambiado_en.desc(), grupos.c.id.desc())
        .all()
    )
    return [
        {
            "id": f.id,
            "usuario_nombre": f.usuario_nombre,
            "cambiado_en": f.cambiado_en,
            "logistica": (
                None
                if f.logistica_nueva_id is None
                else {"id": f.logistica_nueva_id, "nombre": f.logistica_nombre, "color": f.logistica_color}
            ),
            "etiquetas": f.etiquetas,
        }
        for f in filas
    ]


def filas_de_operacion(db: Session, operacion_id: int) -> Optional[List[EtiquetaEnvioLogisticaHistorial]]:
    """History rows of the bulk assignment that contains `operacion_id`, or None when it is not one."""
    fila = db.query(_Historial).filter(_Historial.id == operacion_id, _Historial.origen == ORIGEN_MASIVO).first()
    if fila is None:
        return None
    return (
        db.query(_Historial)
        .filter(
            _Historial.origen == ORIGEN_MASIVO,
            _Historial.cambiado_en == fila.cambiado_en,
            _Historial.usuario_id.is_not_distinct_from(fila.usuario_id),
            _Historial.logistica_nueva_id.is_not_distinct_from(fila.logistica_nueva_id),
        )
        .all()
    )


def deshacer_operacion(
    db: Session,
    filas: List[EtiquetaEnvioLogisticaHistorial],
    usuario_id: int,
    operador_id: Optional[int] = None,
) -> Resultado:
    """S3: revert every label of one bulk assignment whose last change is still that assignment (flushed)."""
    por_etiqueta = {h.shipping_id: h for h in filas}
    etiquetas = _bloquear(db, set(por_etiqueta))
    ultimos = _ultimos_cambios(db, set(etiquetas))
    activas = _activas(db)

    resultado = Resultado()
    destinos: Dict[str, Optional[int]] = {}
    for shipping_id in sorted(por_etiqueta):
        etiqueta = etiquetas.get(shipping_id)
        if etiqueta is None:
            resultado.no_revertidas[NO_EXISTE].append(shipping_id)
            continue
        fila = por_etiqueta[shipping_id]
        ultimo = ultimos.get(shipping_id)
        if ultimo is None or ultimo.id != fila.id:
            resultado.no_revertidas[CAMBIO_POSTERIOR].append(shipping_id)
            continue
        motivo = motivo_no_deshacer_con(etiqueta.logistica_id, fila, activas)
        if motivo is not None:
            resultado.no_revertidas[motivo].append(shipping_id)
            continue
        destinos[shipping_id] = fila.logistica_anterior_id
        resultado.revertidas.append(shipping_id)

    _aplicar(db, destinos, etiquetas, usuario_id, operador_id)
    db.flush()
    return resultado

"""Reading the logistics history of a label and deciding whether its last change can be undone.

Undo puts back `logistica_anterior_id` of the label's latest history row. It only applies while the label still
holds that row's `logistica_nueva_id` (otherwise someone changed it without a record and the history is stale) and
the logística it would put back is active, or NULL ("Sin asignar"). The GET shows the same verdict the POST
enforces, so both read it from `motivo_no_deshacer`.
"""

from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session, aliased

from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.etiqueta_envio_logistica_historial import EtiquetaEnvioLogisticaHistorial
from app.models.logistica import Logistica
from app.models.operador import Operador
from app.models.usuario import Usuario

LIMITE_HISTORIAL = 200

SIN_CAMBIOS = "La etiqueta no tiene cambios de logística para deshacer."
CAMBIO_SIN_REGISTRO = "La logística cambió desde el último registro; recargá el historial."
ANTERIOR_INACTIVA = "La logística anterior está inactiva."

_Historial = EtiquetaEnvioLogisticaHistorial


def _orden_mas_nuevo_primero():
    return desc(_Historial.cambiado_en), desc(_Historial.id)


def ultimo_cambio(db: Session, shipping_id: str) -> Optional[EtiquetaEnvioLogisticaHistorial]:
    """Latest history row of the label, or None when it never changed."""
    return (
        db.query(_Historial).filter(_Historial.shipping_id == shipping_id).order_by(*_orden_mas_nuevo_primero()).first()
    )


def motivo_no_deshacer(
    db: Session, etiqueta: EtiquetaEnvio, ultimo: Optional[EtiquetaEnvioLogisticaHistorial]
) -> Optional[str]:
    """Why the latest change cannot be undone (the 409 message), or None when it can."""
    if ultimo is None:
        return SIN_CAMBIOS
    if etiqueta.logistica_id != ultimo.logistica_nueva_id:
        return CAMBIO_SIN_REGISTRO
    if ultimo.logistica_anterior_id is not None:
        activa = db.query(Logistica.activa).filter(Logistica.id == ultimo.logistica_anterior_id).scalar()
        if not activa:
            return ANTERIOR_INACTIVA
    return None


def _logistica_ref(id_: Optional[int], nombre: Optional[str], color: Optional[str]) -> Optional[dict]:
    if id_ is None:
        return None
    return {"id": id_, "nombre": nombre, "color": color}


def historial_de_etiqueta(db: Session, etiqueta: EtiquetaEnvio) -> dict:
    """The label's current logística, the undo verdict and its changes newest first (one query for the list)."""
    anterior = aliased(Logistica)
    nueva = aliased(Logistica)
    filas = (
        db.query(
            _Historial,
            anterior.nombre,
            anterior.color,
            nueva.nombre,
            nueva.color,
            Usuario.nombre,
            Operador.nombre,
        )
        .outerjoin(anterior, anterior.id == _Historial.logistica_anterior_id)
        .outerjoin(nueva, nueva.id == _Historial.logistica_nueva_id)
        .outerjoin(Usuario, Usuario.id == _Historial.usuario_id)
        .outerjoin(Operador, Operador.id == _Historial.operador_id)
        .filter(_Historial.shipping_id == etiqueta.shipping_id)
        .order_by(*_orden_mas_nuevo_primero())
        .limit(LIMITE_HISTORIAL)
        .all()
    )
    cambios = [
        {
            "id": h.id,
            "cambiado_en": h.cambiado_en,
            "origen": h.origen,
            "anterior": _logistica_ref(h.logistica_anterior_id, ant_nombre, ant_color),
            "nueva": _logistica_ref(h.logistica_nueva_id, nue_nombre, nue_color),
            "usuario_nombre": usuario_nombre,
            "operador_nombre": operador_nombre,
        }
        for h, ant_nombre, ant_color, nue_nombre, nue_color, usuario_nombre, operador_nombre in filas
    ]

    actual = None
    if etiqueta.logistica_id is not None:
        logistica = db.query(Logistica).filter(Logistica.id == etiqueta.logistica_id).first()
        if logistica is not None:
            actual = _logistica_ref(logistica.id, logistica.nombre, logistica.color)

    ultimo = filas[0][0] if filas else None
    puede_deshacer = motivo_no_deshacer(db, etiqueta, ultimo) is None
    return {
        "shipping_id": etiqueta.shipping_id,
        "logistica_actual": actual,
        "puede_deshacer": puede_deshacer,
        "deshacer_a": cambios[0]["anterior"] if puede_deshacer else None,
        "cambios": cambios,
    }

"""Bulk edit of sell-out campaigns (edición masiva M1, S2-S5).

Only the filled fields change (`CAMPOS`: `fecha_desde`, `fecha_hasta`, `acumulable`). Each campaign goes, in id
order (the lock order), through the single edit's own step (`campanas.editar_campana_sin_commit`: same lock,
rules, audit row, with `es_masivo`, and queueing) with its full body rebuilt from what is stored
(`campanas.entrada_guardada`) plus the filled fields, so nothing else moves: groups, per-product amounts or
shares, the program, an `al_cobro` payment rate. A campaign that already has the values is `sin_cambio`: no audit
row, no queueing.

All or nothing, in one transaction, like the bulk void (`campanas.anular_campanas`): every refused campaign is
named with its reason (`SellOutEdicionRechazada`): an unknown id, a voided one, dates that would end before they
start, any rule of the step with its own message. A campaign being rebuilt (`SellOutRecalculando`) or a deadlock
with another writer (40P01) stops the loop and makes the refusal a retry, with the bulk void's messages.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.sell_out import SellOutCampana
from app.services.sell_out import campanas as base
from app.services.sell_out.campanas import DEADLOCK, REINTENTAR, SellOutError, SellOutRecalculando

CAMPOS = ("fecha_desde", "fecha_hasta", "acumulable")

Rechazada = tuple[int, Optional[str], str]  # (id, nombre, motivo); nombre None for an unknown id


class SellOutEdicionRechazada(SellOutError):
    """A bulk edit with campaigns that cannot be edited: nothing was edited. `rechazadas` is `[(id, nombre,
    motivo)]`, in id order. `reintentar` is True when one of them was busy (being rebuilt, or locked by another
    writer): a 409 the client can retry, the message naming that campaign; otherwise a 422."""

    def __init__(self, rechazadas: list[Rechazada], mensaje: Optional[str] = None) -> None:
        self.rechazadas = sorted(rechazadas, key=lambda r: r[0])
        self.reintentar = mensaje is not None
        cuantas = "1 no se puede" if len(rechazadas) == 1 else f"{len(rechazadas)} no se pueden"
        super().__init__(mensaje or f"No se editó ninguna campaña: {cuantas} editar.")


def _fecha(dia: date) -> str:
    return dia.strftime("%d/%m/%Y")


def _editar_una(db: Session, campana: SellOutCampana, cambios: dict, usuario_id: int) -> bool:
    """One locked, active campaign: False when it already has the values; else its edit step, True."""
    if all(getattr(campana, campo) == valor for campo, valor in cambios.items()):
        return False
    desde = cambios.get("fecha_desde", campana.fecha_desde)
    hasta = cambios.get("fecha_hasta", campana.fecha_hasta)
    if hasta < desde:
        raise SellOutError(
            f"La campaña {campana.nombre} quedaría con la fecha hasta ({_fecha(hasta)}) "
            f"antes que la fecha desde ({_fecha(desde)})"
        )
    data = base.entrada_guardada(db, campana).model_copy(update=cambios)
    base.editar_campana_sin_commit(db, campana.id, data, usuario_id, es_masivo=True)
    return True


def _aplicar(
    db: Session, campana_ids: list[int], cambios: dict, usuario_id: int
) -> tuple[list[int], list[int], list[Rechazada]]:
    """The bulk edit without committing: `(editadas, sin_cambio, rechazadas)`. A refusal may have rolled the
    session back (the step's own rules do); the loop goes on to name every refused campaign, the outcome of each
    depending only on its own stored values. A busy campaign raises the retry refusal, rolled back."""
    ids = sorted(set(campana_ids))
    nombres = dict(db.query(SellOutCampana.id, SellOutCampana.nombre).filter(SellOutCampana.id.in_(ids)))
    rechazadas: list[Rechazada] = [(cid, None, f"La campaña {cid} no existe") for cid in ids if cid not in nombres]
    editadas: list[int] = []
    sin_cambio: list[int] = []
    for campana_id in (cid for cid in ids if cid in nombres):
        nombre = nombres[campana_id]
        try:
            campana = base.bloquear(db, campana_id)
            (editadas if _editar_una(db, campana, cambios, usuario_id) else sin_cambio).append(campana_id)
        except SellOutRecalculando as exc:  # `_encolar` already rolled back
            mensaje = (
                f"No se editó ninguna campaña: la campaña {campana_id} ({nombre}) se está recalculando. {REINTENTAR}"
            )
            busy = (campana_id, nombre, f"Se está recalculando. {REINTENTAR}")
            raise SellOutEdicionRechazada([busy, *rechazadas], mensaje) from exc
        except SellOutError as exc:  # voided (`SellOutYaAnulada`), inverted dates, any rule of the step
            rechazadas.append((campana_id, nombre, str(exc)))
        except DBAPIError as exc:
            if getattr(exc.orig, "pgcode", None) != DEADLOCK:
                raise
            db.rollback()
            mensaje = (
                f"No se editó ninguna campaña: otra operación está modificando la campaña {campana_id} "
                f"en este momento. {REINTENTAR}"
            )
            busy = (campana_id, nombre, f"Otra operación la está modificando. {REINTENTAR}")
            raise SellOutEdicionRechazada([busy, *rechazadas], mensaje) from exc
    return editadas, sin_cambio, rechazadas


def editar_campanas(db: Session, campana_ids: list[int], cambios: dict, usuario_id: int) -> tuple[list[int], list[int]]:
    """Edit the filled fields of several campaigns in one transaction (module docstring). Returns `(editadas,
    sin_cambio)`, in id order; raises `SellOutEdicionRechazada`, everything rolled back, when any is refused."""
    editadas, sin_cambio, rechazadas = _aplicar(db, campana_ids, cambios, usuario_id)
    if rechazadas:
        db.rollback()
        raise SellOutEdicionRechazada(rechazadas)
    db.commit()
    return editadas, sin_cambio

"""Renovar programa: the next-quarter copy of each campaign of a program's latest period, in one all-or-nothing step
(owner: "Renovar programa" on a program; the per-campaign renewal is `renovacion`).

- **Source period** (orchestrator's rule, 2026-11-04): L is the calendar quarter of the program's latest
  `fecha_hasta` (voided campaigns included). The candidates are the program's non-voided campaigns that are not
  renewed yet and end in quarter L, or in L-1 when a campaign of the program in L names one of L-1 in
  `renovada_de_id` (no backfill: campaigns renewed before the link existed point nowhere, and must not be renewed
  again). The source period is the earliest quarter among the candidates, and its
  candidates are renewed. So one campaign renewed by hand (its copy ends in L) does not hide the rest of L-1, a
  full renewal moves on to the copies, and a quarter older than L-1 is never picked.
- **Already renewed**: another non-voided campaign names it in `renovada_de_id`. No name or date heuristics: a
  renamed copy still counts.
- **Skipped and listed** (`omitidas`): the source period's voided campaigns ("anulada, no se renueva") and its
  already renewed ones.
- **Left out** (`quedan_afuera`): the candidates of the other quarter of the window. They are not renewed in this
  pass, and the preview says so.
- **Each copy** is the per-campaign renewal's draft (`renovacion.borrador`: same copy rules, same program, linked
  through `renovada_de_id`) saved through the create's own step (`campanas.crear_campana_sin_commit`: validation,
  audit row, queueing), all in one transaction.
- **An archived program** renews nothing (`programas.ProgramaError`, a 422); an unknown one is
  `programas.ProgramaNoExiste`.

`previa` writes nothing. `renovar` takes the campaign ids the preview showed: it locks the program row, so two
renewals of one program run one after the other, recomputes the preview, and refuses (`RenovacionDesactualizada`,
nothing created) when the ids differ, so a second click, or a campaign renewed or voided meanwhile, creates no
second copy. Any campaign that cannot be created refuses the whole renewal, naming it.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.sell_out import SellOutCampana, SellOutPrograma
from app.services.sell_out import campanas, programas, renovacion

ANULADA = "anulada, no se renueva"


class RenovacionDesactualizada(campanas.SellOutError):
    """The campaigns sent are not the ones the preview gives now: nothing was created (a 409, preview again)."""


def _trimestre(fecha: date) -> tuple[date, date]:
    """The calendar quarter holding `fecha`: its first and last day."""
    primer_mes = (fecha.month - 1) // 3 * 3 + 1
    return date(fecha.year, primer_mes, 1), date(
        fecha.year, primer_mes + 2, calendar.monthrange(fecha.year, primer_mes + 2)[1]
    )


def _programa(db: Session, programa_id: int, bloquear: bool) -> SellOutPrograma:
    query = db.query(SellOutPrograma).filter(SellOutPrograma.id == programa_id)
    programa = (query.populate_existing().with_for_update() if bloquear else query).first()
    if programa is None:
        raise programas.ProgramaNoExiste(f"El programa {programa_id} no existe.")
    if programa.estado == "archivado":
        raise programas.ProgramaError(f"El programa «{programa.nombre}» está archivado.")
    return programa


def _rechazo(campana: SellOutCampana, exc: Exception) -> campanas.SellOutError:
    return campanas.SellOutError(f"No se renovó ninguna campaña: la campaña {campana.id} ({campana.nombre}): {exc}")


def _indice(fecha: date) -> int:
    """The calendar quarter holding `fecha`, as a number that grows by one per quarter."""
    return fecha.year * 4 + (fecha.month - 1) // 3


def _limites(indice: int) -> tuple[date, date]:
    return _trimestre(date(indice // 4, indice % 4 * 3 + 1, 1))


def previa(db: Session, programa_id: int, *, bloquear: bool = False) -> dict:
    """What renewing the program would do (module docstring), read-only: the source period (`periodo_desde`,
    `periodo_hasta`), the target quarter (`fecha_desde`, `fecha_hasta`), `renovar`, `omitidas` and `quedan_afuera`.
    Dates are None, with nothing to renew, when the program has no campaigns. `bloquear`: lock the program row until
    the transaction ends (`renovar`)."""
    programa = _programa(db, programa_id, bloquear)
    salida: dict = {
        "programa_id": programa.id,
        "programa": programa.nombre,
        "periodo_desde": None,
        "periodo_hasta": None,
        "fecha_desde": None,
        "fecha_hasta": None,
        "renovar": [],
        "omitidas": [],
        "quedan_afuera": [],
    }
    ultima: Optional[date] = (
        db.query(func.max(SellOutCampana.fecha_hasta)).filter(SellOutCampana.programa_id == programa.id).scalar()
    )
    if ultima is None:
        return salida
    ultimo = _indice(ultima)
    ventana = (
        db.query(SellOutCampana)
        .filter(SellOutCampana.programa_id == programa.id, SellOutCampana.fecha_hasta >= _limites(ultimo - 1)[0])
        .order_by(SellOutCampana.id)
        .all()
    )
    copias: dict[int, SellOutCampana] = {}
    for copia in (
        db.query(SellOutCampana)
        .filter(SellOutCampana.renovada_de_id.in_([c.id for c in ventana]), SellOutCampana.estado != "anulada")
        .order_by(SellOutCampana.id)
    ):
        copias.setdefault(copia.renovada_de_id, copia)
    # No backfill: a campaign renewed before the link existed points nowhere, so L-1 counts only while its renewal is
    # under way with links (a campaign of the program in L names one of L-1).
    trimestre = {c.id: _indice(c.fecha_hasta) for c in ventana}
    con_anterior = any(
        copia.programa_id == programa.id and _indice(copia.fecha_hasta) == ultimo and trimestre[original] == ultimo - 1
        for original, copia in copias.items()
    )
    ventana = [c for c in ventana if trimestre[c.id] == ultimo or con_anterior]
    candidatas = [c for c in ventana if c.estado != "anulada" and c.id not in copias]
    origen = min((_indice(c.fecha_hasta) for c in candidatas), default=ultimo)
    salida["periodo_desde"], salida["periodo_hasta"] = _limites(origen)
    salida["fecha_desde"], salida["fecha_hasta"] = _limites(origen + 1)
    for campana in ventana:
        if _indice(campana.fecha_hasta) != origen:
            if campana in candidatas:
                salida["quedan_afuera"].append(
                    {"campana_id": campana.id, "nombre": campana.nombre, "fecha_hasta": campana.fecha_hasta}
                )
            continue
        if campana.estado == "anulada":
            motivo = ANULADA
        elif (copia := copias.get(campana.id)) is not None:
            motivo = f"ya renovada en la campaña {copia.id} ({copia.nombre})"
        else:
            try:
                borrador = renovacion.borrador(db, campana.id)
            except campanas.SellOutError as exc:
                raise _rechazo(campana, exc) from exc
            salida["renovar"].append(
                {"campana_id": campana.id, "nombre": campana.nombre, "nombre_nuevo": borrador.nombre}
            )
            continue
        salida["omitidas"].append({"campana_id": campana.id, "nombre": campana.nombre, "motivo": motivo})
    return salida


@campanas._deadlock_es_ocupada
def renovar(db: Session, programa_id: int, campana_ids: list[int], usuario_id: int) -> dict:
    """Create the copies the preview lists, all or nothing (module docstring), and commit. `campana_ids`: the ones
    the preview showed. Returns `creadas` (`campana_id`, `nueva_id`) in id order and `omitidas` as the preview."""
    plan = previa(db, programa_id, bloquear=True)
    if sorted(set(campana_ids)) != [r["campana_id"] for r in plan["renovar"]]:
        db.rollback()
        raise RenovacionDesactualizada(
            "La renovación del programa cambió desde la vista previa: no se creó ninguna campaña. Revisala de nuevo."
        )
    if not plan["renovar"]:
        db.rollback()
        raise campanas.SellOutError(f"No hay campañas para renovar en el programa «{plan['programa']}».")
    creadas = []
    for fila in plan["renovar"]:
        original = db.get(SellOutCampana, fila["campana_id"])
        try:
            nueva = campanas.crear_campana_sin_commit(db, renovacion.borrador(db, original.id), usuario_id)
        except campanas.SellOutRecalculando:
            raise  # already rolled back: a retry
        except (campanas.SellOutError, programas.ProgramaError) as exc:
            rechazo = _rechazo(original, exc)  # read before the rollback expires it
            db.rollback()
            raise rechazo from exc
        creadas.append({"campana_id": original.id, "nueva_id": nueva.id})
    db.commit()
    return {"creadas": creadas, "omitidas": plan["omitidas"]}

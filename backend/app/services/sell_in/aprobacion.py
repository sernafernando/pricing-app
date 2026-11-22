"""Approval of loads (tacticals approval, owner L30: "tienen que quedar con un filtro de pendientes de aprobación para
que alejandro los revise y los apruebe y que no apliquen de una porque suelen hacer cagadas en la carga").

A line row of the engines (`sell_in_bonos_marca`, `sell_in_compras`, `sell_out_campanas`) is `pendiente` from its load
until it is approved, and again after a money-changing edit (S4, S5). Every money reader takes only `estado =
'activa'`, so a pending row applies to nothing: costo SI, FIFO, the per-sale bonuses, the bonus reconcile, sell out and
markups never see it. This module flips rows between `pendiente` and `activa` and triggers what follows:

- a bonus: its own triggers (`bono_queue`: an UPDATE of `estado` while it is or was active; `costo_si.queue`: any
  UPDATE) queue the `sell_in.bono` reconcile, the per-sale cost bonuses and costo SI, whose drain runs the L15
  callbacks with their backups (`costo_si.despues`);
- a purchase: the `sell_in_compras` UPDATE trigger queues costo SI; the FIFO has no trigger, so it is recomputed here
  with its cost bonuses (`costing.get_costing().recompute` + `bonos_costo.seguir_fifo`, as a load or a void does);
- a campaign: no trigger either, so it is queued for `sell_out.drain` (`campanas._encolar`), whose rebuild drops or
  takes its rows and rebuilds the campaigns sharing its products (as a void does).

A tactical's lines follow their tactical (`app.services.tacticals.aprobar` / `a_pendiente`); a standalone row (no
`tactical_id`) is approved alone (`aprobar_linea`). A purchase a bonus generated (`origen = 'bono_marca'`) is not a
load: the reconcile creates it `activa` from an active bonus and voids it when the bonus stops being active.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional, Union

from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.sell_in import SellInBonoMarca, SellInCompra, SellInCompraItem
from app.models.sell_out import SellOutCampana

ACTIVA = "activa"
PENDIENTE = "pendiente"
ANULADA = "anulada"
# Not voided: what a void, an edit or an approval still acts on.
VIVAS = (ACTIVA, PENDIENTE)
PERMISO = "tacticals.aprobar"

Linea = Union[SellInBonoMarca, SellInCompra, SellOutCampana]
# How each kind is named in the audit values and in a message.
_CLAVE = {SellInBonoMarca: "bono_id", SellInCompra: "compra_id", SellOutCampana: "campana_id"}
NOMBRE = {SellInBonoMarca: "El bono", SellInCompra: "La compra", SellOutCampana: "La campaña"}


class AprobacionError(ValueError):
    """The approval cannot be done as asked; the message is for the operator (a 409)."""


class YaAprobada(AprobacionError):
    pass


class DeUnTactical(AprobacionError):
    """A tactical's line is approved with its tactical, never alone."""


class Anulada(AprobacionError):
    pass


def estado_de_linea(estado_tactical: Optional[str]) -> str:
    """The state a new line of a tactical takes: `activa` only under an approved tactical (an invoice total whose
    invoice arrives after the approval), `pendiente` otherwise."""
    return ACTIVA if estado_tactical == "activo" else PENDIENTE


def cambio_de_dinero(antes: dict, despues: dict, sin: Iterable[str]) -> bool:
    """Whether an edit changed money (S5: amounts, %, units/caps, dates, scope, base/kind): its audit snapshots differ
    in anything but `sin` (name, description, state)."""
    fuera = set(sin) | {"estado"}
    return {k: v for k, v in antes.items() if k not in fuera} != {k: v for k, v in despues.items() if k not in fuera}


def cambiar_lineas(
    db: Session,
    *,
    bono_ids: Iterable[int] = (),
    compra_ids: Iterable[int] = (),
    campana_ids: Iterable[int] = (),
    de: str,
    a: str,
) -> dict[str, list[int]]:
    """Move the given rows that are in `de` to `a` (`pendiente` <-> `activa`), locking them in id order, and trigger
    what follows (module docstring). Rows in another state are left as they are. Does not commit. Returns the ids
    moved per kind."""
    from app.services.sell_in import bonos_costo  # noqa: PLC0415 - bonos_costo imports the engines that import this
    from app.services.sell_in.costing import get_costing  # noqa: PLC0415
    from app.services.sell_out import campanas  # noqa: PLC0415 - campanas imports this module

    movidas: dict[str, list[int]] = {"bono_ids": [], "compra_ids": [], "campana_ids": []}
    for modelo, ids, clave in (
        (SellInBonoMarca, bono_ids, "bono_ids"),
        (SellInCompra, compra_ids, "compra_ids"),
        (SellOutCampana, campana_ids, "campana_ids"),
    ):
        ids = sorted(set(ids))
        if not ids:
            continue
        filas = (
            db.query(modelo)
            .filter(modelo.id.in_(ids), modelo.estado == de)
            .order_by(modelo.id)
            .populate_existing()
            .with_for_update()
            .all()
        )
        for fila in filas:
            fila.estado = a
        movidas[clave] = [fila.id for fila in filas]
    db.flush()
    if movidas["compra_ids"]:
        items = sorted(
            {
                i
                for (i,) in db.query(SellInCompraItem.item_id).filter(
                    SellInCompraItem.compra_id.in_(movidas["compra_ids"])
                )
            }
        )
        get_costing().recompute(db, items, isolate_failures=False)
        bonos_costo.seguir_fifo(db, items)
    if movidas["campana_ids"]:
        campanas._encolar(db, movidas["campana_ids"])
    return movidas


def auditar(db: Session, tipo: TipoAccion, usuario_id: int, valores: dict, motivo: Optional[str] = None) -> None:
    db.add(
        Auditoria(
            item_id=None,
            usuario_id=usuario_id,
            tipo_accion=tipo,
            valores_anteriores=None,
            valores_nuevos=valores,
            es_masivo=False,
            comentario=motivo,
            fecha=datetime.now(timezone.utc).replace(tzinfo=None),  # naive UTC, like the column's default
        )
    )


def _ids(fila: Linea) -> dict:
    tipo = type(fila)
    return {
        "bono_ids": [fila.id] if tipo is SellInBonoMarca else [],
        "compra_ids": [fila.id] if tipo is SellInCompra else [],
        "campana_ids": [fila.id] if tipo is SellOutCampana else [],
    }


def a_pendiente_si_cambia(
    db: Session, fila: Linea, antes: dict, despues: dict, sin: Iterable[str], usuario_id: int
) -> bool:
    """After an engine's edit step of an approved row (S4, S5): a money change sends it back to `pendiente`; when it
    is a tactical's line, the whole tactical goes back (nothing from it applies until approved again). True when it
    went back. A pending row stays pending; a name or description edit keeps it approved."""
    if fila.estado != ACTIVA or not cambio_de_dinero(antes, despues, sin):
        return False
    if fila.tactical_id is not None:
        from app.services import tacticals  # noqa: PLC0415 - tacticals imports the engines that import this

        tacticals.a_pendiente(db, fila.tactical_id, usuario_id, f"{NOMBRE[type(fila)]} {fila.id} se editó")
        return True
    cambiar_lineas(db, **_ids(fila), de=ACTIVA, a=PENDIENTE)
    auditar(db, TipoAccion.TACTICAL_A_PENDIENTE, usuario_id, {_CLAVE[type(fila)]: fila.id})
    return True


def aprobar_linea(db: Session, modelo: type, fila_id: int, usuario_id: int) -> Optional[Linea]:
    """Approve one standalone pending row (`POST /sell-in/bonos/{id}/aprobar`, `/sell-in/compras/{id}/aprobar`,
    `/sell-out/campanas/{id}/aprobar`) and commit: it starts applying. None when it does not exist; `DeUnTactical`
    for a tactical's line (approved with its tactical); `Anulada` / `YaAprobada` otherwise. Self-approval is allowed
    (L31)."""
    try:
        fila = db.query(modelo).filter(modelo.id == fila_id).populate_existing().with_for_update().first()
        if fila is None:
            return None
        nombre = NOMBRE[modelo]
        if fila.tactical_id is not None:
            raise DeUnTactical(
                f"{nombre} {fila_id} es una línea del tactical {fila.tactical_id}: se aprueba desde el tactical"
            )
        if fila.estado == ANULADA:
            raise Anulada(
                f"{nombre} {fila_id} está anulada"
                if modelo is not SellInBonoMarca
                else f"El bono {fila_id} está anulado"
            )
        if fila.estado == ACTIVA:
            raise YaAprobada(f"{nombre} {fila_id} ya está aprobad{'o' if modelo is SellInBonoMarca else 'a'}")
        cambiar_lineas(db, **_ids(fila), de=PENDIENTE, a=ACTIVA)
        auditar(db, TipoAccion.TACTICAL_APROBADO, usuario_id, {_CLAVE[modelo]: fila_id})
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(fila)
    return fila

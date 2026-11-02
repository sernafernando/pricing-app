"""Bulk edit of sell-out campaigns and its preview (edición masiva M1, S2-S5).

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

`previa_edicion` writes nothing. Inside one transaction that it always rolls back, it runs the very same loop, so its
`cambian`, `sin_cambio` and `rechazadas` are what the apply would do. Then it runs the very rebuild the
`sell_out.drain` worker would run for what the apply queues (`asignacion.recalcular` over the edited campaigns,
which takes every active campaign sharing products with them; it neither commits nor touches the queue), and
diffs `sell_out_consumos` before and after, line by line, per campaign:

- `salen`: lines gone, the units lines lost, and the signed money of the lines that leave or shrink;
- `entran`: new lines, the units lines gained, and the signed money of the lines that enter or grow;

money in each campaign's currency, totals per currency, always on the line's side: a deduction's (`monto_total`
below 0) leaving line is negative `salen` money, never positive `entran` money. So caps (an earlier sale taking a later line's units, or
units a shorter range frees going to a later sale already inside), stacking (`acumulable`: the units a
non-stackable campaign holds are taken from the linked campaigns after it) and a fixed total's split (a share
moved between a product's sales, or a share with no sale credited by a sale that enters) come out as the rebuild
does them. A linked campaign whose credit moves is listed in `vinculadas`, `en_seleccion` False when it was not
selected. While any campaign is refused, the apply changes nothing; the numbers are then those of the campaigns
that can be edited, simulated on their own. A rebuild that would fail (a product without VAT, a USD campaign
without a rate) is refused with the reason in Spanish and the campaign's name, as the drain would charge it.

The preview holds what the apply holds, for the whole rebuild: the campaigns' row locks, their queue rows and the
rebuild's per-campaign locks, which it takes before reading the stored lines, so the "before" side is what the
rebuild starts from. Each wait it makes for a lock is bounded by `queue.LOCK_TIMEOUT` (2 s): the selected campaigns'
row locks (another preview or bulk edit holding them), their queue rows (a running drain batch), and the rebuild's
per-campaign locks and the row locks its writes need (a drain rebuilding them). Past the bound, or in a lock cycle
with another writer (40P01), it is the busy 409 «Reintentar en unos segundos», nothing written. The apply bounds
only the queue rows' wait; it waits for the row locks.

Pending work: the rebuild the preview runs starts from the stored lines; a campaign with a queue row before the
preview (a sale, a rate or another change not drained yet) has stored lines that are behind, so its numbers also
include that pending work. Such a campaign is flagged `incluye_pendientes`, and the response carries the notice
«incluye cambios pendientes que no causa esta edición» (`aviso_pendientes`); the numbers stay as the rebuild gives
them (no second rebuild to separate them).
Meanwhile, a single edit of one of those campaigns that has a queue row waits for it and gets the same 409 after
`queue.LOCK_TIMEOUT` (or on a deadlock); one with NO queue row waits on the campaign row itself (the preview's
queue insert holds a key-share lock on it), past those 2 s, until the preview ends.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.producto import ProductoERP
from app.models.sell_out import SellOutCampana, SellOutConsumo, SellOutDirty
from app.services.sell_out import asignacion, queue, reparto
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


def _editar_una(db: Session, campana: SellOutCampana, cambios: dict, usuario_id: int, compartian: list[int]) -> bool:
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
    base.editar_campana_sin_commit(db, campana.id, data, usuario_id, es_masivo=True, compartian=compartian)
    return True


def _aplicar(
    db: Session, campana_ids: list[int], cambios: dict, usuario_id: int, espera: Optional[str] = None
) -> tuple[list[int], list[int], list[Rechazada]]:
    """The bulk edit without committing: `(editadas, sin_cambio, rechazadas)`. A refusal may have rolled the
    session back (the step's own rules do); the loop goes on to name every refused campaign, the outcome of each
    depending only on its own stored values. A busy campaign raises the retry refusal, rolled back. `espera`
    bounds the wait for each campaign's row lock (the preview's `queue.LOCK_TIMEOUT`); the apply waits for it."""
    ids = sorted(set(campana_ids))
    nombres = dict(db.query(SellOutCampana.id, SellOutCampana.nombre).filter(SellOutCampana.id.in_(ids)))
    rechazadas: list[Rechazada] = [(cid, None, f"La campaña {cid} no existe") for cid in ids if cid not in nombres]
    editadas: list[int] = []
    sin_cambio: list[int] = []
    # Links are by product: a date or `acumulable` change moves none, so the whole batch's are read once up front.
    vinculos = asignacion.vinculadas_por_campana(db, [cid for cid in ids if cid in nombres])
    encoladas: set[int] = set()  # queued by an earlier row of this transaction: queueing them again changes nothing
    for campana_id in (cid for cid in ids if cid in nombres):
        nombre = nombres[campana_id]
        try:
            if espera is None:
                campana = base.bloquear(db, campana_id)
            else:
                with queue.lock_timeout(db, espera):
                    campana = base.bloquear(db, campana_id)
            compartian = [c for c in vinculos[campana_id] if c != campana_id and c not in encoladas]
            if _editar_una(db, campana, cambios, usuario_id, compartian):
                editadas.append(campana_id)
                encoladas.update([campana_id, *compartian])
            else:
                sin_cambio.append(campana_id)
        except SellOutRecalculando as exc:  # `_encolar` already rolled back
            mensaje = (
                f"No se editó ninguna campaña: la campaña {campana_id} ({nombre}) se está recalculando. {REINTENTAR}"
            )
            busy = (campana_id, nombre, f"Se está recalculando. {REINTENTAR}")
            raise SellOutEdicionRechazada([busy, *rechazadas], mensaje) from exc
        except SellOutError as exc:  # voided (`SellOutYaAnulada`), inverted dates, any rule of the step
            rechazadas.append((campana_id, nombre, str(exc)))
        except DBAPIError as exc:  # a lock cycle, or (bounded by `espera`) a row another writer holds
            if getattr(exc.orig, "pgcode", None) not in (DEADLOCK, queue.LOCK_NOT_AVAILABLE):
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


Consumos = dict[int, dict[tuple[str, int], tuple[int, Decimal]]]  # campana_id -> (canal, venta_ref) -> (units, money)


def _consumos(db: Session, campana_ids: list[int]) -> Consumos:
    """The campaigns' stored lines, ONE query; every asked campaign is present."""
    salida: Consumos = {cid: {} for cid in campana_ids}
    if campana_ids:
        t = SellOutConsumo
        filas = db.query(t.campana_id, t.canal, t.venta_ref, t.unidades, t.monto).filter(t.campana_id.in_(campana_ids))
        for cid, canal, ref, unidades, monto in filas:
            salida[cid][(canal, ref)] = (int(unidades), Decimal(monto))
    return salida


def _diferencia(antes: dict, despues: dict) -> dict:
    """`{salen, entran}` of one campaign: lines gone or new, the units each line lost or gained, and the signed money
    of the lines that leave, enter, shrink or grow, kept on the line's side (a deduction's leaving -100 line is
    `salen` -100, never +100 entering)."""
    salen = {"lineas": 0, "unidades": 0, "monto": Decimal(0)}
    entran = {"lineas": 0, "unidades": 0, "monto": Decimal(0)}
    for clave in antes.keys() | despues.keys():
        previo, nuevo = antes.get(clave), despues.get(clave)
        unidades = (nuevo[0] if nuevo else 0) - (previo[0] if previo else 0)
        salen["unidades"] += max(-unidades, 0)
        entran["unidades"] += max(unidades, 0)
        if nuevo is None:
            salen["lineas"] += 1
            salen["monto"] += previo[1]
        elif previo is None:
            entran["lineas"] += 1
            entran["monto"] += nuevo[1]
        elif abs(nuevo[1]) < abs(previo[1]):  # the line shrinks: what it no longer credits leaves
            salen["monto"] += previo[1] - nuevo[1]
        elif abs(nuevo[1]) > abs(previo[1]):
            entran["monto"] += nuevo[1] - previo[1]
    return {"salen": salen, "entran": entran}


def _motivo_recalculo(db: Session, exc: asignacion.SellOutAsignacionError) -> str:
    """`exc` for the operator, from its fields (`campana_id`, `causa`, `item_id`, `fecha`): the campaign by its name
    and the reason in Spanish; an invalid split with `campanas.mensaje_reparto`. Read after the rollback."""
    campana = db.get(SellOutCampana, exc.campana_id)
    quien = f"la campaña {campana.nombre}" if campana is not None else f"la campaña {exc.campana_id}"
    if exc.causa == "reparto_invalido" and isinstance(exc.__cause__, reparto.RepartoInvalido):
        porque = base.mensaje_reparto(exc.__cause__)
        return f"La edición no se puede recalcular: en {quien}, {porque[0].lower()}{porque[1:]}"
    if exc.causa == "producto_sin_iva" and exc.item_id is not None:
        producto = db.get(ProductoERP, exc.item_id)
        codigo = f" ({producto.codigo})" if producto is not None and producto.codigo else ""
        porque = f"se carga con IVA y el producto {exc.item_id}{codigo} no tiene IVA"
    elif exc.causa == "producto_sin_iva":
        porque = "se carga con IVA y un producto que alcanza no tiene IVA"
    elif exc.causa == "sin_tipo_cambio" and exc.fecha is not None:
        porque = f"no tiene cotización BNA para convertir la venta del {_fecha(exc.fecha)}"
    elif exc.causa == "sin_tipo_cambio":
        porque = "no tiene cotización BNA para convertir sus ventas"
    elif exc.causa == "monto_negativo":
        porque = "daría un monto negativo, y solo una campaña por monto total puede ser negativa"
    else:
        porque = "tiene un reparto que no se puede aplicar"
    return f"La edición no se puede recalcular: {quien} {porque}"


AVISO_PENDIENTES = "incluye cambios pendientes que no causa esta edición"


def _pendientes(db: Session, campana_ids: list[int]) -> set[int]:
    """The asked campaigns and those linked to them that have a queue row now: their stored lines are behind, so
    the rebuild the preview runs also does that pending work. ONE query over the queue, plus the links."""
    tocadas = asignacion.vinculadas(db, campana_ids)
    if not tocadas:
        return set()
    filas = db.query(SellOutDirty.campana_id).filter(SellOutDirty.campana_id.in_(tocadas))
    return {int(cid) for (cid,) in filas}


def _simular(
    db: Session, campana_ids: list[int], cambios: dict, usuario_id: int
) -> tuple[list[int], list[int], list[Rechazada], dict[int, dict], set[int]]:
    """The loop, then the rebuild the drain would run for it, in the open transaction: `(editadas, sin_cambio,
    rechazadas, {campana_id: {salen, entran}}, pendientes)` over the edited and every linked campaign; `pendientes`
    are those of them with a queue row BEFORE the loop (module docstring). The caller rolls back."""
    pendientes = _pendientes(db, campana_ids)
    editadas, sin_cambio, rechazadas = _aplicar(db, campana_ids, cambios, usuario_id, queue.LOCK_TIMEOUT)
    if rechazadas:  # a refusal may have rolled the loop back: simulate the editable ones on their own
        db.rollback()
        editadas, sin_cambio, otras = _aplicar(db, editadas + sin_cambio, cambios, usuario_id, queue.LOCK_TIMEOUT)
        rechazadas = rechazadas + otras
    tocadas = asignacion.vinculadas(db, editadas)  # what `recalcular` rebuilds: links are by product, not dates
    try:
        # Every wait of the rebuild is bounded like the queue's: the loop's row locks are held meanwhile.
        with queue.lock_timeout(db, queue.LOCK_TIMEOUT):
            if tocadas and db.get_bind().dialect.name == "postgresql":
                # The rebuild's own per-campaign locks, taken BEFORE reading what is stored, so no drain rebuilds
                # them between that read and the simulated rebuild (`recalcular` takes them again: re-entrant).
                db.execute(asignacion.LOCK_SQL, {"ns": asignacion.LOCK_NAMESPACE, "ids": tocadas})
            antes = _consumos(db, tocadas)
            asignacion.recalcular(db, editadas)
            despues = _consumos(db, tocadas)
    except asignacion.SellOutAsignacionError as exc:
        db.rollback()
        raise SellOutError(_motivo_recalculo(db, exc)) from exc
    except DBAPIError as exc:
        if getattr(exc.orig, "pgcode", None) not in (DEADLOCK, queue.LOCK_NOT_AVAILABLE):
            raise
        db.rollback()  # a drain rebuilding them, or a lock cycle with another writer: busy, retry
        raise SellOutRecalculando(
            f"Otra operación está recalculando o modificando estas campañas en este momento. {REINTENTAR}"
        ) from exc
    diferencias = {cid: _diferencia(antes[cid], despues[cid]) for cid in tocadas}
    return editadas, sin_cambio, rechazadas, diferencias, pendientes


def _se_mueve(diferencia: dict) -> bool:
    return any(diferencia["salen"].values()) or any(diferencia["entran"].values())


def _montos(filas: list[dict], lado: str) -> list[dict]:
    por_moneda: dict[str, Decimal] = defaultdict(Decimal)
    for fila in filas:
        if fila[lado]["lineas"] or fila[lado]["unidades"] or fila[lado]["monto"]:
            por_moneda[fila["moneda"]] += fila[lado]["monto"]
    return [{"moneda": m, "monto": por_moneda[m]} for m in sorted(por_moneda)]


def previa_edicion(db: Session, campana_ids: list[int], cambios: dict, usuario_id: int) -> dict:
    """What `editar_campanas` and the rebuild it queues would do, writing nothing (module docstring). Raises the
    same retry refusal when a campaign is busy; the other refusals are listed, not raised."""
    try:
        editadas, sin_cambio, rechazadas, diferencias, pendientes = _simular(db, campana_ids, cambios, usuario_id)
    finally:
        db.rollback()
    seleccion = set(campana_ids)
    movidas = sorted(set(editadas) | {cid for cid, d in diferencias.items() if _se_mueve(d)})
    campanas = {c.id: c for c in db.query(SellOutCampana).filter(SellOutCampana.id.in_(movidas))}
    cambian, vinculadas = [], []
    for cid in movidas:  # read before the rollback below, which expires them (one SELECT each otherwise)
        c = campanas[cid]
        fila = {"id": c.id, "nombre": c.nombre, "moneda": c.moneda, "incluye_pendientes": cid in pendientes}
        if cid in editadas:
            fila.update({campo: cambios.get(campo, getattr(c, campo)) for campo in CAMPOS})
        else:
            fila["en_seleccion"] = cid in seleccion
        fila.update(diferencias.get(cid) or _diferencia({}, {}))
        (cambian if cid in editadas else vinculadas).append(fila)
    db.rollback()  # nothing to keep: release the snapshot instead of holding it until the session closes
    filas = cambian + vinculadas
    totales = {
        "cambian": len(cambian),
        "sin_cambio": len(sin_cambio),
        "rechazadas": len(rechazadas),
        **{
            lado: {
                "lineas": sum(f[lado]["lineas"] for f in filas),
                "unidades": sum(f[lado]["unidades"] for f in filas),
                "montos": _montos(filas, lado),
            }
            for lado in ("salen", "entran")
        },
    }
    return {
        "totales": totales,
        "cambian": cambian,
        "vinculadas": vinculadas,
        "aviso_pendientes": AVISO_PENDIENTES if any(f["incluye_pendientes"] for f in filas) else None,
        "sin_cambio": sin_cambio,
        "rechazadas": [{"id": i, "nombre": n, "motivo": m} for i, n, m in sorted(rechazadas, key=lambda r: r[0])],
    }

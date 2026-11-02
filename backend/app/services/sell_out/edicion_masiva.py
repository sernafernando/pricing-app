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

`previa_edicion` writes nothing: it runs the very same loop and always rolls it back, so its `cambian`,
`sin_cambio` and `rechazadas` are what the apply would do, then reads, for each campaign that changes:

- `salen`: its applied sales (`sell_out_consumos`) dated outside the new dates, in lines, units and amount (in
  the campaign's currency). With no other change they are exactly the lines the rebuild drops. A `monto_total`
  campaign spreads each product's share over the product's sales left in its dates (`reparto.repartir`), so a
  product that keeps at least one sale in the new dates (credited, or entering) keeps its whole share, moved to
  those sales: its leaving lines carry no money out. Only the share of a product left with NO sale in the new
  dates leaves (it becomes the campaign's unassigned money, counted on `fecha_hasta`).
- `entran`: the sales (not returns) of the products it reaches (`alcance.productos`; for a `monto_total` campaign
  only the products with a share, as the allocator does) dated in the days the new dates add, read like the
  allocator reads them (`alcance.ventas`, every channel), without the sales of a percentage campaign whose base is
  not recorded yet (`asignacion.base_desconocida`). Lines and units only: their amount is known after the rebuild
  (on a `monto_total` campaign they dilute the rows already credited, they add no money).
  It is an UPPER bound: when a cap binds, or a non-stackable campaign sharing the products holds the units, the
  rebuild credits less, and an earlier sale that enters may take units from a later line already credited (which
  `salen` does not count, being inside the new dates). Turning `acumulable` alone moves neither.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.sell_out import SellOutCampana, SellOutConsumo
from app.services.sell_out import alcance, asignacion
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


def _dias_nuevos(desde: date, hasta: date, nuevo_desde: date, nuevo_hasta: date) -> list[tuple[date, date]]:
    """The days of [nuevo_desde, nuevo_hasta] outside [desde, hasta], as at most two ranges."""
    rangos = [
        (nuevo_desde, min(nuevo_hasta, desde - timedelta(days=1))),
        (max(nuevo_desde, hasta + timedelta(days=1)), nuevo_hasta),
    ]
    return [(a, b) for a, b in rangos if a <= b]


def _salen(db: Session, campanas: list[SellOutCampana], cambios: dict) -> dict[int, dict]:
    """`{campana_id: {lineas, unidades, monto, por_item, quedan}}` of the applied sales dated outside the new dates,
    ONE query: `por_item` is their amount per product, `quedan` the products with a credited sale inside them."""
    salida = {
        c.id: {"lineas": 0, "unidades": 0, "monto": Decimal(0), "por_item": defaultdict(Decimal), "quedan": set()}
        for c in campanas
    }
    if not campanas:
        return salida
    t = SellOutConsumo
    rows = (
        db.query(t.campana_id, t.item_id, t.fecha_venta, func.count(), func.sum(t.unidades), func.sum(t.monto))
        .filter(t.campana_id.in_(list(salida)))
        .group_by(t.campana_id, t.item_id, t.fecha_venta)
    )
    por_id = {c.id: c for c in campanas}
    for cid, item_id, dia, lineas, unidades, monto in rows:
        c, fila = por_id[cid], salida[cid]
        if cambios.get("fecha_desde", c.fecha_desde) <= dia <= cambios.get("fecha_hasta", c.fecha_hasta):
            fila["quedan"].add(item_id)
            continue
        fila["lineas"] += lineas
        fila["unidades"] += int(unidades)
        fila["monto"] += Decimal(monto)
        fila["por_item"][item_id] += Decimal(monto)
    return salida


def _monto_que_sale(campana: SellOutCampana, salen: dict, entran_items: set) -> Decimal:
    """The money the campaign stops crediting: every leaving line's, except on a `monto_total` campaign, where only
    the share of a product left with no sale in the new dates leaves (module docstring)."""
    if campana.tipo != "monto_total":
        return salen["monto"]
    sigue = salen["quedan"] | entran_items
    return sum((m for item, m in salen["por_item"].items() if item not in sigue), Decimal(0))


def _entran(db: Session, campanas: list[SellOutCampana], cambios: dict) -> tuple[dict[int, dict], dict[int, set]]:
    """`{campana_id: {lineas, unidades}}` of the sales the new dates add (module docstring), and `{campana_id:
    products of those sales}`: one reach query, one shares query and ONE `alcance.ventas` read over every
    campaign's added days."""
    salida = {c.id: {"lineas": 0, "unidades": 0} for c in campanas}
    items_entran: dict[int, set] = {c.id: set() for c in campanas}
    dias = {
        c.id: _dias_nuevos(
            c.fecha_desde,
            c.fecha_hasta,
            cambios.get("fecha_desde", c.fecha_desde),
            cambios.get("fecha_hasta", c.fecha_hasta),
        )
        for c in campanas
    }
    con_dias = [c for c in campanas if dias[c.id]]
    if not con_dias:
        return salida, items_entran
    productos = alcance.productos(db, [c.id for c in con_dias])
    repartos = asignacion.repartos_item(db, con_dias)
    alcanzados = {
        c.id: {i for i in productos.get(c.id, {}) if c.tipo != "monto_total" or i in repartos.get(c.id, {})}
        for c in con_dias
    }
    items = set().union(*alcanzados.values())
    if not items:
        return salida, items_entran
    rangos = [r for c in con_dias for r in dias[c.id]]
    ventas = alcance.ventas(db, items, min(a for a, _ in rangos), max(b for _, b in rangos))
    for c in con_dias:
        for v in ventas:
            if v.unidades <= 0 or v.item_id not in alcanzados[c.id] or asignacion.base_desconocida(c, v):
                continue
            if any(a <= v.fecha <= b for a, b in dias[c.id]):
                salida[c.id]["lineas"] += 1
                salida[c.id]["unidades"] += v.unidades
                items_entran[c.id].add(v.item_id)
    return salida, items_entran


def previa_edicion(db: Session, campana_ids: list[int], cambios: dict, usuario_id: int) -> dict:
    """What `editar_campanas` would do, writing nothing (module docstring): the same loop, always rolled back, then
    the sales that leave and enter each campaign that changes, with the totals (the amount per currency). Raises
    the same retry refusal when a campaign is busy; the other refusals are listed, not raised."""
    try:
        editadas, sin_cambio, rechazadas = _aplicar(db, campana_ids, cambios, usuario_id)
    finally:
        db.rollback()
    campanas = db.query(SellOutCampana).filter(SellOutCampana.id.in_(editadas)).order_by(SellOutCampana.id).all()
    salen = _salen(db, campanas, cambios)
    entran, items_entran = _entran(db, campanas, cambios)
    montos: dict[str, Decimal] = defaultdict(Decimal)
    cambian = []
    for c in campanas:  # read before the rollback below, which expires them (one SELECT each otherwise)
        sale = {"lineas": salen[c.id]["lineas"], "unidades": salen[c.id]["unidades"]}
        sale["monto"] = _monto_que_sale(c, salen[c.id], items_entran[c.id])
        if sale["lineas"]:
            montos[c.moneda] += sale["monto"]
        nuevos = {campo: cambios.get(campo, getattr(c, campo)) for campo in CAMPOS}
        cambian.append(
            {"id": c.id, "nombre": c.nombre, "moneda": c.moneda, **nuevos, "salen": sale, "entran": entran[c.id]}
        )
    db.rollback()  # nothing to keep: release the snapshot instead of holding it until the session closes
    totales = {
        "cambian": len(cambian),
        "sin_cambio": len(sin_cambio),
        "rechazadas": len(rechazadas),
        "salen": {
            "lineas": sum(c["salen"]["lineas"] for c in cambian),
            "unidades": sum(c["salen"]["unidades"] for c in cambian),
            "montos": [{"moneda": m, "monto": montos[m]} for m in sorted(montos)],
        },
        "entran": {
            "lineas": sum(e["lineas"] for e in entran.values()),
            "unidades": sum(e["unidades"] for e in entran.values()),
        },
    }
    return {
        "totales": totales,
        "cambian": cambian,
        "sin_cambio": sin_cambio,
        "rechazadas": [{"id": i, "nombre": n, "motivo": m} for i, n, m in sorted(rechazadas, key=lambda r: r[0])],
    }

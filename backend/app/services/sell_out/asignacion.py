"""Sell-out allocator (sell-in-sell-out T7 S2): rebuilds campaigns' `sell_out_consumos`.

`recalcular` rebuilds whole campaigns from scratch (design
`design/sell-out-allocator/t7`, owner 2026-10-20: a late sale dated earlier
displaces a later one, a cancellation frees its units): it loads the sales each
campaign reaches (`alcance`), gives them the credit with the pure
`tope.asignar` and writes only the difference against what is stored, so a
re-run writes nothing. A campaign that is not `activa` (or no longer exists)
keeps no rows.

Stacking: two campaigns sharing a product stack unless one of them is not
`acumulable`; then the one with the lower id takes precedence, and the other
only gets, per sale, the units the first did not take (`ocupadas`), or, per
return, the units it did not free. Campaigns sharing products are therefore
rebuilt together, in id order, whatever was asked: the call takes every active
campaign linked to the asked ones through shared products, transitively.

Rate: a USD row freezes `tc_venta`, the BNA rate (`tipo_cambio`, USD `venta`,
the latest on or before the sale day) when it is written; a row that does not
change keeps it. ARS amounts are computed on read (S5). A `dia_venta` campaign
with no rate for a sale day fails: never a guessed rate.

Not yet: a `porcentaje` campaign fails (`SellOutAsignacionError`) until its base
(which cost, which net price, converted how) is decided; so does a campaign
loaded with VAT reaching a product without `iva`.

Concurrency: `pg_advisory_xact_lock(LOCK_NAMESPACE, campana_id)` for every
campaign rebuilt, in id order, before reading what is stored. Does not commit;
any error propagates and the caller rolls back.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import delete, insert, or_, text
from sqlalchemy.orm import Session

from app.models.sell_out import SellOutCampana, SellOutConsumo
from app.services.sell_in.bonos import _tasas_bna
from app.services.sell_out import alcance, tope

# First key of the two-key advisory lock; the second is the campaign id. Sell-in costing uses 0x5E11 (item ids)
# and the brand bonus 0x5E12 (bonus ids).
LOCK_NAMESPACE = 0x5E13
_LOCK_SQL = text(
    "SELECT pg_advisory_xact_lock(:ns, i) FROM (SELECT DISTINCT i FROM unnest(CAST(:ids AS integer[])) AS t(i) "
    "ORDER BY i) AS ordered"
)

Clave = Tuple[str, int]  # (canal, venta_ref)
Productos = Dict[int, Dict[int, Optional[Decimal]]]


class SellOutAsignacionError(ValueError):
    """A campaign cannot be allocated as it stands; the message says why."""


@dataclass
class RecomputeResult:
    campanas: int = 0
    inserted: int = 0
    deleted: int = 0


def _vinculadas(db: Session, ids: List[int]) -> Tuple[Dict[int, SellOutCampana], Productos, List[int]]:
    """The asked campaigns plus every active one sharing a product with them, transitively, in id order."""
    campanas = {
        c.id: c
        for c in db.query(SellOutCampana)
        .filter(or_(SellOutCampana.id.in_(ids), SellOutCampana.estado == "activa"))
        .populate_existing()
    }
    productos = alcance.productos(db, campanas)
    activas = [c for c in campanas.values() if c.estado == "activa"]
    vistas = set(ids)
    pendientes = [i for i in ids if i in productos]
    while pendientes:
        mios = productos[pendientes.pop()].keys()
        for otra in activas:
            if otra.id not in vistas and mios & productos.get(otra.id, {}).keys():
                vistas.add(otra.id)
                pendientes.append(otra.id)
    return campanas, productos, sorted(vistas)


def _tope(c: SellOutCampana) -> tope.Campana:
    if c.tipo != "por_unidad":
        raise SellOutAsignacionError(f"campaign {c.id}: percentage campaigns are not allocated yet (base undecided)")
    return tope.Campana(
        tipo=c.tipo,
        moneda=c.moneda,
        monto_unit=c.monto_unit,
        monto_incluye_iva=c.monto_incluye_iva,
        tope_unidades=c.tope_unidades,
        tope_monto=c.tope_monto,
    )


def _asignar(activas: List[SellOutCampana], productos: Productos, ventas: List[alcance.Venta]):
    """`{campana_id: [Consumo]}`, campaigns in id order, each after those taking precedence over it."""
    tomadas: Dict[int, Dict[Clave, int]] = {}  # per campaign: units taken per sale on its turn, freed per return
    salida: Dict[int, List[tope.Consumo]] = {}
    for c in activas:
        alcance_c = productos.get(c.id, {})
        antes = [p.id for p in activas if p.id < c.id and not (p.acumulable and c.acumulable)]
        lineas = []
        for v in ventas:
            if v.item_id not in alcance_c or not alcance.en_campana(c, v):
                continue
            iva = alcance_c[v.item_id]
            if c.monto_incluye_iva and iva is None:
                raise SellOutAsignacionError(f"campaign {c.id}: product {v.item_id} has no VAT rate")
            clave = (v.canal, v.venta_ref)
            ocupadas = min(abs(v.unidades), sum(tomadas[p].get(clave, 0) for p in antes))
            lineas.append(
                tope.Linea(
                    canal=v.canal,
                    venta_ref=v.venta_ref,
                    item_id=v.item_id,
                    fecha=v.fecha,
                    unidades=v.unidades,
                    iva_pct=iva or Decimal(0),
                    ocupadas=ocupadas,
                    objetivo=v.objetivo,
                )
            )
        tomadas[c.id] = {}
        salida[c.id] = tope.asignar(_tope(c), lineas, por_linea=tomadas[c.id])
    return salida


def recalcular(db: Session, campana_ids: Iterable[int]) -> RecomputeResult:
    """Rebuilds the given campaigns and every active campaign sharing products with them (module docstring)."""
    ids = sorted({int(i) for i in campana_ids})
    if not ids:
        return RecomputeResult()
    _, _, bloqueadas = _vinculadas(db, ids)
    if db.get_bind().dialect.name == "postgresql":
        db.execute(_LOCK_SQL, {"ns": LOCK_NAMESPACE, "ids": bloqueadas})
    # Again under the lock, and ONLY for the locked ones: a campaign linked while this call waited is
    # rebuilt by the call its own change queues.
    campanas, productos, vinculadas = _vinculadas(db, ids)
    cierre = [i for i in vinculadas if i in set(bloqueadas)]
    activas = [campanas[i] for i in cierre if i in campanas and campanas[i].estado == "activa"]
    items = {item for c in activas for item in productos.get(c.id, {})}
    ventas = []
    if activas and items:
        desde = min(c.fecha_desde for c in activas)
        ventas = alcance.ventas(db, items, desde, max(c.fecha_hasta for c in activas))
    deseados = _asignar(activas, productos, ventas)

    guardados: Dict[Tuple[int, str, int], Tuple[int, tuple]] = {}
    t = SellOutConsumo
    for rid, cid, canal, ref, item_id, fecha, unidades, monto in db.query(
        t.id, t.campana_id, t.canal, t.venta_ref, t.item_id, t.fecha_venta, t.unidades, t.monto
    ).filter(t.campana_id.in_(cierre)):
        guardados[(cid, canal, ref)] = (rid, (item_id, fecha, unidades, Decimal(monto)))
    nuevos = {
        (cid, x.canal, x.venta_ref): (x.item_id, x.fecha_venta, x.unidades, x.monto)
        for cid, consumos in deseados.items()
        for x in consumos
    }
    borrar = [rid for clave, (rid, valores) in guardados.items() if nuevos.get(clave) != valores]
    insertar = [clave for clave, valores in nuevos.items() if guardados.get(clave, (None, None))[1] != valores]
    usd = {c.id: c for c in activas if c.moneda == "USD"}
    tasas = _tasas_bna(db, {nuevos[clave][1] for clave in insertar if clave[0] in usd})
    filas = []
    for clave in insertar:
        cid, canal, ref = clave
        item_id, fecha, unidades, monto = nuevos[clave]
        tasa = tasas.get(fecha) if cid in usd else None
        if tasa is None and cid in usd and usd[cid].tc_modo == "dia_venta":
            raise SellOutAsignacionError(f"campaign {cid}: no BNA rate on or before {fecha}")
        filas.append(
            {
                "campana_id": cid,
                "canal": canal,
                "venta_ref": ref,
                "item_id": item_id,
                "fecha_venta": fecha,
                "unidades": unidades,
                "monto": monto,
                "tc_venta": tasa,
            }
        )
    if borrar:
        db.execute(delete(SellOutConsumo).where(SellOutConsumo.id.in_(borrar)))
    if filas:
        db.execute(insert(SellOutConsumo), filas)
    return RecomputeResult(campanas=len(cierre), inserted=len(filas), deleted=len(borrar))

"""Sell-out allocator (sell-in-sell-out T7 S2): rebuilds campaigns' `sell_out_consumos`.

`recalcular` rebuilds whole campaigns from scratch (design
`design/sell-out-allocator/t7`, owner 2026-10-20: a late sale dated earlier
displaces a later one, a cancellation frees its units): it loads the sales each
campaign reaches (`alcance`), gives them the credit with the pure
`tope.asignar` and writes only the difference against what is stored, so a
re-run writes nothing. A campaign that is not `activa` (or no longer exists)
keeps no rows.

Stacking: two campaigns sharing a product stack unless one of them is not
`acumulable`; then the one with the lower id takes precedence. Units are
tracked per sale line: a campaign takes the lowest-numbered units not held by
the campaigns that take precedence over it (`ocupadas` = how many those hold
between them), so campaigns that stack share the SAME units and campaigns that
do not hold different ones. On a return the same goes for the units each frees.
Campaigns sharing products are therefore rebuilt together, in id order,
whatever was asked: the call takes every active campaign linked to the asked
ones through shared products, transitively. S3 must queue, on a group edit, the
campaigns that shared products BEFORE the edit too (afterwards they are no
longer linked, so this call would not find them).

Percentage (owner 2026-10-20): `porcentaje` of a base per unit without VAT,
as recorded on the sale (`alcance.Venta`): `costo`, or `precio_neto` (an ML
price is stripped of its product's VAT). A sale whose base is unknown (an ML
order not settled yet, a sale without its cost) is skipped: it holds no units,
so the cap goes on to the next sale, and it is counted in `pendientes_base`.
Once it settles, its campaign is rebuilt (S3) and it takes its place in sale
order. A missing rate or VAT rate is configuration, not transient data: it fails. A USD campaign converts the ARS base with its own `tc_modo`: `fijo`
at its `tipo_cambio`; `dia_venta` at the sale day's BNA; `al_cobro` at its
`tipo_cambio` once set, before that at the CURRENT BNA (the latest `tipo_cambio`
row), so its amounts move with BNA: S3 queues `al_cobro` campaigns when BNA
updates. The money cap applies to those amounts.

Rate: every USD row freezes `tc_venta`, the BNA rate (`tipo_cambio`, USD
`venta`, the latest on or before the sale day) when it is written; a row that
does not change keeps it. ARS amounts are computed on read (S5). A USD row or
conversion with no rate fails the campaign: never a guessed nor an empty rate.
A campaign loaded with VAT reaching a product without `iva` fails too.

Concurrency: `pg_advisory_xact_lock(LOCK_NAMESPACE, campana_id)` for every
campaign rebuilt, in id order, before reading what is stored. Does not commit;
any error propagates and the caller rolls back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import delete, insert, or_, text
from sqlalchemy.orm import Session

from app.models.sell_out import SellOutCampana, SellOutConsumo
from app.models.tipo_cambio import TipoCambio
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


class _BaseDesconocida(Exception):
    """A sale's percentage base is not known yet (module docstring)."""


@dataclass
class RecomputeResult:
    campanas: int = 0
    inserted: int = 0
    deleted: int = 0
    # campaign -> its percentage sales skipped because their base is unknown yet (only campaigns with some)
    pendientes_base: Dict[int, int] = field(default_factory=dict)


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
    return tope.Campana(
        tipo=c.tipo,
        moneda=c.moneda,
        monto_unit=c.monto_unit,
        porcentaje=c.porcentaje,
        monto_incluye_iva=c.monto_incluye_iva,
        tope_unidades=c.tope_unidades,
        tope_monto=c.tope_monto,
    )


@dataclass(frozen=True)
class _Tasas:
    por_dia: Dict[date, Optional[Decimal]]  # BNA of each sale day of a USD campaign
    actual: Optional[Decimal]  # the latest BNA, when an `al_cobro` campaign without its rate needs it


def _tasa(c: SellOutCampana, fecha: date, tasas: _Tasas) -> Decimal:
    if c.tc_modo == "fijo" or (c.tc_modo == "al_cobro" and c.tipo_cambio is not None):
        tasa = c.tipo_cambio
    elif c.tc_modo == "dia_venta":
        tasa = tasas.por_dia.get(fecha)
    else:
        tasa = tasas.actual
    if tasa is None:
        raise SellOutAsignacionError(f"campaign {c.id}: no BNA rate to convert the sale of {fecha}")
    return Decimal(tasa)


def _base(c: SellOutCampana, v: alcance.Venta, iva: Optional[Decimal], tasas: _Tasas) -> Optional[Decimal]:
    """A positive sale's percentage base per unit, without VAT, in the campaign currency."""
    if c.tipo != "porcentaje" or v.unidades < 0:
        return None
    base = v.costo_unit if c.base_porcentaje == "costo" else v.precio_unit
    if base is None:
        raise _BaseDesconocida
    if c.base_porcentaje == "precio_neto" and v.precio_con_iva:
        if iva is None:
            raise SellOutAsignacionError(f"campaign {c.id}: product {v.item_id} has no VAT rate")
        base = base / (1 + iva / 100)
    return base if c.moneda == "ARS" else base / _tasa(c, v.fecha, tasas)


def _asignar(activas: List[SellOutCampana], productos: Productos, ventas: List[alcance.Venta], tasas: _Tasas):
    """`{campana_id: [Consumo]}`, campaigns in id order, each after those taking precedence over it."""
    tenidas: Dict[int, Dict[Clave, List[int]]] = {}  # per campaign and line: the unit numbers it took or freed
    salida: Dict[int, List[tope.Consumo]] = {}
    pendientes: Dict[int, int] = {}
    for c in activas:
        alcance_c = productos.get(c.id, {})
        antes = [p.id for p in activas if p.id < c.id and not (p.acumulable and c.acumulable)]
        lineas, libres = [], {}
        for v in ventas:
            if v.item_id not in alcance_c or not alcance.en_campana(c, v):
                continue
            iva = alcance_c[v.item_id]
            if c.monto_incluye_iva and iva is None:
                raise SellOutAsignacionError(f"campaign {c.id}: product {v.item_id} has no VAT rate")
            try:
                base_unit = _base(c, v, iva, tasas)
            except _BaseDesconocida:
                pendientes[c.id] = pendientes.get(c.id, 0) + 1
                continue
            clave = (v.canal, v.venta_ref)
            ocupado = set().union(*(tenidas[p].get(clave, ()) for p in antes))
            libres[clave] = [u for u in range(abs(v.unidades)) if u not in ocupado]
            lineas.append(
                tope.Linea(
                    canal=v.canal,
                    venta_ref=v.venta_ref,
                    item_id=v.item_id,
                    fecha=v.fecha,
                    unidades=v.unidades,
                    iva_pct=iva or Decimal(0),
                    base_unit=base_unit,
                    ocupadas=len(ocupado),
                    objetivo=v.objetivo,
                )
            )
        por_linea: Dict[Clave, int] = {}
        salida[c.id] = tope.asignar(_tope(c), lineas, por_linea=por_linea)
        tenidas[c.id] = {clave: libres[clave][:n] for clave, n in por_linea.items()}
    return salida, pendientes


def _tasas(db: Session, activas: List[SellOutCampana], ventas: List[alcance.Venta]) -> _Tasas:
    usd = [c for c in activas if c.moneda == "USD"]
    por_dia = _tasas_bna(db, {v.fecha for v in ventas if v.unidades > 0} if usd else set())
    actual = None
    if any(c.tipo == "porcentaje" and c.tc_modo == "al_cobro" and c.tipo_cambio is None for c in usd):
        fila = (
            db.query(TipoCambio.venta)
            .filter(TipoCambio.moneda == "USD", TipoCambio.venta > 0)
            .order_by(TipoCambio.fecha.desc(), TipoCambio.id.desc())
            .first()
        )
        actual = Decimal(str(fila[0])) if fila else None
    return _Tasas(por_dia, actual)


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
    tasas = _tasas(db, activas, ventas)
    deseados, pendientes = _asignar(activas, productos, ventas, tasas)

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
    usd = {c.id for c in activas if c.moneda == "USD"}
    filas = []
    for clave in insertar:
        cid, canal, ref = clave
        item_id, fecha, unidades, monto = nuevos[clave]
        tasa = tasas.por_dia.get(fecha) if cid in usd else None
        if tasa is None and cid in usd:
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
    return RecomputeResult(len(cierre), len(filas), len(borrar), pendientes)

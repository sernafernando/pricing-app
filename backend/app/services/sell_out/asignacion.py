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
A return linked to its sale (`alcance.Venta.objetivo`) counts only when that
sale is one of the campaign's lines: one returning a sale from before the
campaign, or a sale skipped while its base is unknown, frees nothing here (when
that sale settles, the rebuild counts both). Only a return that could not be
linked falls back to the latest earlier sale of the product (`tope.asignar`).
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
order. A missing rate or VAT rate is configuration, not transient data: it fails.
A USD campaign converts the ARS base with its own `tc_modo`: `fijo`
at its `tipo_cambio`; `dia_venta` at the sale day's BNA; `al_cobro` at its
`tipo_cambio` once set, before that at the CURRENT BNA (the latest `tipo_cambio`
row), so its amounts move with BNA: S3 queues `al_cobro` campaigns when BNA
updates. The money cap applies to those amounts.

Rate: every USD row carries `tc_venta`, the rate it converts at NOW (S3, owner:
"cuando está en dinámico se calcula en cuanto se actualiza bna"): `al_cobro`
its `tipo_cambio` once set, before that the latest BNA; `fijo` its
`tipo_cambio` (no BNA needed); `dia_venta` the BNA of the sale day
(`tipo_cambio`, USD `venta`, the latest on or before it). A changed rate is a
change: the row is rewritten. The rate is rounded to the column's 6 decimals
half up, as Postgres rounds NUMERIC. ARS amounts are computed on read (S5). A
USD row or conversion with no rate fails the campaign: never a guessed nor an
empty rate.
A campaign loaded with VAT reaching a product without `iva` fails too.

Per-product amounts (T22b, legacy grouped offsets): a `por_unidad` campaign's
`sell_out_campana_items` give a product its own amount instead of
`monto_unit`, under the same one cap (`tope`); read in ONE query per call.

Fixed totals (T26b, S34/S35): a `monto_total` campaign's manual shares
(`sell_out_campana_items`, read in ONE query per call) spread over each
product's sales the campaign reaches in its dates, the same sale set and
returns as the other kinds (`tope.asignar` keeps the net units, with no money),
by units (`reparto.repartir`); the rows may be negative (a deduction). A share
whose product sold nothing there and the unassigned remainder write nothing
(`reparto.resumen_monto_total`). VAT and currency as for a per-unit amount: a
share loaded with VAT is divided by its own product's VAT; the share is in the
campaign currency and a USD row carries its `tc_venta` by `tc_modo` as above.
Stacking: a lump sum is not per unit, so it holds no units (another exclusive
campaign is not displaced by it, whatever its `acumulable`) and no campaign's
units limit it. Shares that cannot be split as they stand (`reparto.validar`:
a fixed share against the total's sign, shares exceeding the total) fail the
campaign like a missing VAT rate does, writing nothing. Only its rows may be negative: a negative row of a
`por_unidad` or `porcentaje` campaign fails the rebuild (the DB no longer
refuses it).

Concurrency: `pg_advisory_xact_lock(LOCK_NAMESPACE, campana_id)` for every
campaign rebuilt, in id order, before reading what is stored. Does not commit;
any error propagates and the caller rolls back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import delete, insert, or_, text
from sqlalchemy.orm import Session

from app.models.sell_out import SellOutCampana, SellOutCampanaItem, SellOutConsumo
from app.models.tipo_cambio import TipoCambio
from app.services.sell_in.bonos import tasas_bna_por_fecha
from app.services.sell_out import alcance, reparto, tope

# First key of the two-key advisory lock; the second is the campaign id. Sell-in costing uses 0x5E11 (item ids)
# and the brand bonus 0x5E12 (bonus ids).
LOCK_NAMESPACE = 0x5E13
LOCK_SQL = text(
    "SELECT pg_advisory_xact_lock(:ns, i) FROM (SELECT DISTINCT i FROM unnest(CAST(:ids AS integer[])) AS t(i) "
    "ORDER BY i) AS ordered"
)

_TC_ESCALA = Decimal("0.000001")  # `sell_out_consumos.tc_venta` is NUMERIC(18, 6)

Clave = Tuple[str, int]  # (canal, venta_ref)
Productos = Dict[int, Dict[int, Optional[Decimal]]]
Montos = Dict[int, Dict[int, Decimal]]  # campana_id -> item_id -> its own amount per unit
Repartos = Dict[int, Dict[int, reparto.Reparto]]  # campana_id -> item_id -> its share of the total


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


def vinculadas(db: Session, campana_ids: Iterable[int]) -> List[int]:
    """The given campaigns plus every active one sharing a product with them, transitively, in id order:
    what `recalcular` would rebuild right now. A group edit captures it BEFORE the edit (S3)."""
    ids = sorted({int(i) for i in campana_ids})
    return _vinculadas(db, ids)[2] if ids else []


def montos_item(db: Session, campanas: Iterable[SellOutCampana]) -> Montos:
    """`{campana_id: {item_id: amount}}` of the given `por_unidad` campaigns' own product amounts, in ONE query
    (none when no campaign is `por_unidad`); a campaign without any is absent."""
    ids = sorted({c.id for c in campanas if c.tipo == "por_unidad"})
    salida: Montos = {}
    if ids:
        t = SellOutCampanaItem
        for cid, item_id, monto in db.query(t.campana_id, t.item_id, t.monto_unit).filter(t.campana_id.in_(ids)):
            salida.setdefault(cid, {})[item_id] = Decimal(monto)
    return salida


def repartos_item(db: Session, campanas: Iterable[SellOutCampana]) -> Repartos:
    """`{campana_id: {item_id: (reparto_porcentaje, reparto_monto)}}` of the given `monto_total` campaigns'
    shares, in ONE query (none when no campaign is `monto_total`); a campaign without any is absent."""
    ids = sorted({c.id for c in campanas if c.tipo == "monto_total"})
    salida: Repartos = {}
    if ids:
        t = SellOutCampanaItem
        filas = db.query(t.campana_id, t.item_id, t.reparto_porcentaje, t.reparto_monto).filter(t.campana_id.in_(ids))
        for cid, item_id, porcentaje, monto in filas:
            salida.setdefault(cid, {})[item_id] = (porcentaje, monto)
    return salida


def _tope(c: SellOutCampana, montos: Optional[Dict[int, Decimal]] = None) -> tope.Campana:
    return tope.Campana(
        montos_item=dict(montos or {}) if c.tipo == "por_unidad" else {},
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


def credito_unitario(
    c: SellOutCampana,
    fecha: date,
    iva: Optional[Decimal],
    base_ars: Optional[Decimal],
    bna: Optional[Decimal],
    *,
    monto_item: Optional[Decimal] = None,
) -> Optional[Tuple[Decimal, Decimal]]:
    """A unit not sold yet, on `fecha`: `(its credit in the campaign currency, the rate to ARS)`, by
    this allocator's rules (`_tasa`, `tope.credito_unitario`); the rate is 1 for ARS. `base_ars` is
    the percentage base per unit, ARS, without VAT; `bna` the BNA of `fecha`, also taken as the
    current one; `monto_item` the product's own amount in the campaign (`montos_item`), if any.
    None when a percentage base is unknown; a missing rate or VAT rate raises."""
    tasa = Decimal(1) if c.moneda == "ARS" else _tasa(c, fecha, _Tasas({fecha: bna}, bna))
    if c.monto_incluye_iva and iva is None:
        raise SellOutAsignacionError(f"campaign {c.id}: a product it reaches has no VAT rate")
    base = None
    if c.tipo == "porcentaje":
        if base_ars is None:
            return None
        base = Decimal(base_ars) / tasa
    linea = tope.Linea("", 0, 0, fecha, 1, iva_pct=iva or Decimal(0), base_unit=base)
    montos = {} if monto_item is None else {0: Decimal(monto_item)}  # keyed by the preview line's item 0
    return tope.credito_unitario(_tope(c, montos), linea), tasa


def _base_registrada(c: SellOutCampana, v: alcance.Venta) -> Optional[Decimal]:
    return v.costo_unit if c.base_porcentaje == "costo" else v.precio_unit


def base_desconocida(c: SellOutCampana, v: alcance.Venta) -> bool:
    """A positive sale of a percentage campaign whose base is not recorded yet: the rebuild skips it and
    counts it in `pendientes_base` (module docstring). The summary read (`resumen`) counts with it too."""
    return c.tipo == "porcentaje" and v.unidades > 0 and _base_registrada(c, v) is None


def _base(c: SellOutCampana, v: alcance.Venta, iva: Optional[Decimal], tasas: _Tasas) -> Optional[Decimal]:
    """A positive sale's percentage base per unit, without VAT, in the campaign currency."""
    if c.tipo != "porcentaje" or v.unidades < 0:
        return None
    if base_desconocida(c, v):
        raise _BaseDesconocida
    base = _base_registrada(c, v)
    if c.base_porcentaje == "precio_neto" and v.precio_con_iva:
        if iva is None:
            raise SellOutAsignacionError(f"campaign {c.id}: product {v.item_id} has no VAT rate")
        base = base / (1 + iva / 100)
    return base if c.moneda == "ARS" else base / _tasa(c, v.fecha, tasas)


def _asignar(
    activas: List[SellOutCampana],
    productos: Productos,
    ventas: List[alcance.Venta],
    tasas: _Tasas,
    montos: Optional[Montos] = None,
    repartos: Optional[Repartos] = None,
):
    """`{campana_id: [Consumo]}`, campaigns in id order, each after those taking precedence over it.
    `montos`: the campaigns' per-product amounts (`montos_item`); `repartos`: their shares (`repartos_item`)."""
    montos = montos or {}
    repartos = repartos or {}
    tenidas: Dict[int, Dict[Clave, List[int]]] = {}  # per campaign and line: the unit numbers it took or freed
    salida: Dict[int, List[tope.Consumo]] = {}
    pendientes: Dict[int, int] = {}
    for c in activas:
        alcance_c = productos.get(c.id, {})
        total = c.tipo == "monto_total"
        if total:  # only its shared products; it is not limited by the units others hold (module docstring)
            alcance_c = {i: iva for i, iva in alcance_c.items() if i in repartos.get(c.id, {})}
        antes = [] if total else [p.id for p in activas if p.id < c.id and not (p.acumulable and c.acumulable)]
        lineas, libres, admitidas = [], {}, set()
        for v in sorted(ventas, key=lambda x: x.unidades < 0):  # sales first: a return checks its sale
            if v.item_id not in alcance_c or not alcance.en_campana(c, v):
                continue
            if v.objetivo is not None and v.objetivo not in admitidas:
                continue  # it returns a sale this campaign does not count (before it, or waiting for its base)
            iva = alcance_c[v.item_id]
            if c.monto_incluye_iva and iva is None:
                raise SellOutAsignacionError(f"campaign {c.id}: product {v.item_id} has no VAT rate")
            try:
                base_unit = _base(c, v, iva, tasas)
            except _BaseDesconocida:
                pendientes[c.id] = pendientes.get(c.id, 0) + 1
                continue
            clave = (v.canal, v.venta_ref)
            admitidas.add(clave)
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
        consumos = tope.asignar(_tope(c, montos.get(c.id)), lineas, por_linea=por_linea)
        if total:
            mt = reparto.MontoTotal(c.monto_total, repartos.get(c.id, {}), c.monto_incluye_iva, alcance_c)
            try:
                salida[c.id] = reparto.repartir(mt, consumos)
            except ValueError as exc:  # shares that cannot be split, a product without VAT: as the other kinds
                raise SellOutAsignacionError(f"campaign {c.id}: {exc}") from exc
            tenidas[c.id] = {}  # a lump sum holds no units
            continue
        if any(x.monto < 0 for x in consumos):
            raise SellOutAsignacionError(f"campaign {c.id}: a {c.tipo} campaign never gives a negative amount")
        salida[c.id] = consumos
        tenidas[c.id] = {clave: libres[clave][:n] for clave, n in por_linea.items()}
    return salida, pendientes


def _tasas(db: Session, activas: List[SellOutCampana], ventas: List[alcance.Venta]) -> _Tasas:
    usd = [c for c in activas if c.moneda == "USD"]
    por_dia = tasas_bna_por_fecha(db, {v.fecha for v in ventas if v.unidades > 0} if usd else set())
    actual = None
    if any(c.tc_modo == "al_cobro" and c.tipo_cambio is None for c in usd):  # every such row carries it
        fila = (
            db.query(TipoCambio.venta)
            .filter(TipoCambio.moneda == "USD", TipoCambio.venta > 0)
            .order_by(TipoCambio.fecha.desc(), TipoCambio.id.desc())
            .first()
        )
        actual = Decimal(str(fila[0])) if fila else None
    return _Tasas(por_dia, actual)


def _tc_fila(c: SellOutCampana, x: tope.Consumo, tasas: _Tasas) -> Optional[Decimal]:
    """The rate a USD row carries: the one it converts at (`_tasa`, module docstring); None for ARS."""
    if c.moneda != "USD":
        return None
    # Rounded as Postgres stores it (half away from zero), so an unchanged rate compares equal.
    return _tasa(c, x.fecha_venta, tasas).quantize(_TC_ESCALA, rounding=ROUND_HALF_UP)


def recalcular(db: Session, campana_ids: Iterable[int]) -> RecomputeResult:
    """Rebuilds the given campaigns and every active campaign sharing products with them (module docstring)."""
    ids = sorted({int(i) for i in campana_ids})
    if not ids:
        return RecomputeResult()
    _, _, bloqueadas = _vinculadas(db, ids)
    if db.get_bind().dialect.name == "postgresql":
        db.execute(LOCK_SQL, {"ns": LOCK_NAMESPACE, "ids": bloqueadas})
    # Again under the lock, and ONLY for the locked ones: a campaign linked while this call waited is
    # rebuilt by the call its own change queues.
    campanas, productos, vinculadas = _vinculadas(db, ids)
    con_lock = set(bloqueadas)
    cierre = [i for i in vinculadas if i in con_lock]
    activas = [campanas[i] for i in cierre if i in campanas and campanas[i].estado == "activa"]
    items = {item for c in activas for item in productos.get(c.id, {})}
    ventas = []
    if activas and items:
        desde = min(c.fecha_desde for c in activas)
        ventas = alcance.ventas(db, items, desde, max(c.fecha_hasta for c in activas))
    tasas = _tasas(db, activas, ventas)
    deseados, pendientes = _asignar(
        activas, productos, ventas, tasas, montos_item(db, activas), repartos_item(db, activas)
    )

    guardados: Dict[Tuple[int, str, int], Tuple[int, tuple]] = {}
    t = SellOutConsumo
    for rid, cid, canal, ref, item_id, fecha, unidades, monto, tc in db.query(
        t.id, t.campana_id, t.canal, t.venta_ref, t.item_id, t.fecha_venta, t.unidades, t.monto, t.tc_venta
    ).filter(t.campana_id.in_(cierre)):
        guardados[(cid, canal, ref)] = (rid, (item_id, fecha, unidades, Decimal(monto), tc))
    por_id = {c.id: c for c in activas}
    nuevos = {
        (cid, x.canal, x.venta_ref): (x.item_id, x.fecha_venta, x.unidades, x.monto, _tc_fila(por_id[cid], x, tasas))
        for cid, consumos in deseados.items()
        for x in consumos
    }
    borrar = [rid for clave, (rid, valores) in guardados.items() if nuevos.get(clave) != valores]
    insertar = [clave for clave, valores in nuevos.items() if guardados.get(clave, (None, None))[1] != valores]
    filas = []
    for clave in insertar:
        cid, canal, ref = clave
        item_id, fecha, unidades, monto, tasa = nuevos[clave]
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

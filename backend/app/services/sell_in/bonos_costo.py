"""A sell-in bonus on a % of the sale's cost, with no purchase or invoice (sell-in-sell-out T25b, S30, S33).

Owner: "agregá el de sell in, es para operaciones viejas que no tienen la factura cargada". A bonus with
`base = 'costo_venta'` (always a percentage, ARS, over a brand, a category or models: the
`ck_sell_in_bonos_marca_costo_venta` check) never generates a sell-in purchase (`bonos.reconciliar` skips it).
`recalcular` keeps its `sell_in_bono_consumos` rows, one per (bonus, channel, sale), in step with:

- Scope and date: the sales of the products its scope reaches (`bonos_alcance.del_alcance`, the panel's rule)
  whose SALE date is in its inclusive range, read the way sell out reads them (`sell_out.alcance.ventas`, every
  channel; fuera/TN returns resolved to their sale like the FIFO's `costing.resolver_objetivos`).
- Base: the cost recorded on the sale, ARS without VAT (ML `mcosto / qty`, fuera/TN `costo_total / units`,
  `alcance.Venta.costo_unit`). A sale whose cost is unknown is skipped, counted in `pendientes` per bonus.
- Amount per unit: the model's own % (`sell_in_bono_items.porcentaje`) or the bonus's, of that cost. With
  `incluye_iva` (S33: "el tilde tendría que restar el iva, a la cuenta siempre debería llegar 2,71") the % is first
  divided by (1 + that product's own VAT rate), by sell out's own per-product rule (`tope.credito_unitario` on a
  `monto_incluye_iva` campaign); a product reached with no VAT rate fails (configuration, never guessed).
- Exclusive per unit with invoice-based sell in (rule 5, owner "ok"): the units a sale already took from a
  purchase (`sell_in_consumos` of that (canal, venta_ref), as stored: FIFO's rows are already net of returns) are
  `ocupadas`; the bonus takes only the rest. A return frees its units here in full: the FIFO resolves it to the same
  sale (`resolver_objetivos`) and its stored rows are already net of it, so the FIFO's units plus the bonus's never
  exceed the sale's net units. A return whose sale the bonus does not count (outside its dates, unknown cost) frees
  nothing, like sell out.
- Several cost bonuses on one sale stack, in id order, each unit's total never above the unit cost: a later bonus's
  amount per unit is cut to the cost minus what the earlier ones give that sale per unit (conservative when an
  earlier capped bonus holds only part of the sale's units).
- Cap (T24 columns): `tope_unidades` units sold and/or `tope_monto` ARS, allocated in sale order (fecha_venta,
  canal, venta_ref) by sell out's `tope.asignar` with the per-unit amount as a 100 % base (like `bonos._topear`),
  recomputed from scratch for the whole bonus: a late sale dated earlier displaces a later one. Amounts are each
  row's units x the unrounded unit amount, rounded once to cents, half up.

What a call recomputes: the given products, the scope of the given bonuses and every product holding rows of them,
closed over the scope of every active CAPPED cost bonus reaching any of them (its cap couples its products). An
uncapped bonus is exact per product. The products fall into components linked by those capped bonuses; a
component whose amounts cannot be computed (a missing VAT rate) is reported in `failed` (per product) and
`bonos_fallidos` (per bonus reaching it) and keeps its rows as they were; the others are written.

Writes: only the difference against the stored rows of those products (a changed row is deleted and inserted,
like `costing`), so a re-run writes nothing. A bonus that is not active, no longer a cost bonus, or no longer
reaches a sale keeps no row for it.

Concurrency: under `costing`'s per-product advisory lock (`pg_advisory_xact_lock(costing.LOCK_NAMESPACE,
item_id)`), taken in item order for every product recomputed BEFORE reading the FIFO's rows, so the exclusivity
reads a settled FIFO. `sell.drain` already holds the lock on its products (the FIFO recompute just ran in the same
transaction); a capped bonus's other products are locked here, after, which can deadlock with another drain in a
rare case: Postgres aborts one (40P01, transient) and it is retried. Gated: with no active cost bonus and no bonus
given, ONE query. Does not commit.

ERP independence (owner, 2026-10-17): only app tables, never `tb_*`.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import delete, func, insert, text
from sqlalchemy.orm import Session

from app.models.producto import ProductoERP
from app.models.sell_in import SellInBonoConsumo, SellInBonoItem, SellInBonoMarca, SellInConsumo
from app.schemas.sell_in_bonos import BASE_COSTO_VENTA
from app.services.sell_in import bono_queue
from app.services.sell_in.costing import LOCK_SQL, LOCK_NAMESPACE
from app.services.sell_out import alcance, tope
from app.services.sell_out import queue as sell_out_queue

logger = logging.getLogger(__name__)

BASE = BASE_COSTO_VENTA
# How long `seguir_fifo` (an interactive purchase, the invoice reconcile) waits for a product lock.
LOCK_TIMEOUT = sell_out_queue.LOCK_TIMEOUT
CIEN = Decimal(100)

Clave = Tuple[str, int]  # (canal, venta_ref)
_Fila = Tuple[int, date, int, Decimal]  # (item_id, fecha_venta, unidades, descuento_ars)


@dataclass
class CostoResult:
    products: int = 0
    inserted: int = 0
    deleted: int = 0
    # item_id -> why its component could not be computed (its rows are left as they were)
    failed: Dict[int, str] = field(default_factory=dict)
    # bono_id -> its sales skipped because their cost is unknown (only bonuses with some)
    pendientes: Dict[int, int] = field(default_factory=dict)
    # bono_id -> the error of a component it reaches
    bonos_fallidos: Dict[int, str] = field(default_factory=dict)
    # bono_id -> the products of its failed component(s)
    productos_fallidos: Dict[int, Set[int]] = field(default_factory=dict)


def _activos(db: Session) -> Dict[int, SellInBonoMarca]:
    return {
        x.id: x
        for x in db.query(SellInBonoMarca)
        .filter(SellInBonoMarca.base == BASE, SellInBonoMarca.estado == "activa")
        .order_by(SellInBonoMarca.id)
        .populate_existing()
    }


def _alcances(db: Session, activos: Dict[int, SellInBonoMarca]) -> Dict[int, Set[int]]:
    """Each active cost bonus's products, by the panel's scope rule (one query per bonus: they are few)."""
    # Imported here: `bonos_alcance` imports `bonos`, which imports this module.
    from app.services.sell_in.bonos_alcance import del_alcance

    return {
        bid: {i for (i,) in db.query(ProductoERP.item_id).filter(del_alcance(db, bono, ProductoERP.item_id, None))}
        for bid, bono in activos.items()
    }


def _con_tope(bono: SellInBonoMarca) -> bool:
    return bono.tope_unidades is not None or bono.tope_monto is not None


def _cerrar(activos: Dict[int, SellInBonoMarca], alcances: Dict[int, Set[int]], productos: Set[int]) -> Set[int]:
    """`productos` plus the whole scope of every capped bonus reaching them, until nothing is added."""
    cerrado = set(productos)
    cambio = True
    while cambio:
        cambio = False
        for bid, bono in activos.items():
            if _con_tope(bono) and alcances[bid] & cerrado and not alcances[bid] <= cerrado:
                cerrado |= alcances[bid]
                cambio = True
    return cerrado


def _semilla(db: Session, item_ids: Set[int], bono_ids: Set[int], alcances: Dict[int, Set[int]]) -> Set[int]:
    productos = set(item_ids)
    for bid in bono_ids:
        productos |= alcances.get(bid, set())
    if bono_ids:
        productos |= {
            int(i)
            for (i,) in db.query(SellInBonoConsumo.item_id)
            .filter(SellInBonoConsumo.bono_id.in_(sorted(bono_ids)))
            .distinct()
        }
    return productos


def _bloquear(db: Session, ids: Set[int]) -> None:
    if ids and db.get_bind().dialect.name == "postgresql":
        db.execute(LOCK_SQL, {"ns": LOCK_NAMESPACE, "ids": sorted(ids)})


def _componentes(activos: Dict[int, SellInBonoMarca], alcances: Dict[int, Set[int]], productos: Set[int]):
    """The products grouped by the capped bonuses linking them (union-find); the others alone."""
    padre = {p: p for p in productos}

    def raiz(p: int) -> int:
        while padre[p] != p:
            padre[p] = padre[padre[p]]
            p = padre[p]
        return p

    for bid, bono in activos.items():
        if _con_tope(bono):
            mios = sorted(alcances[bid] & productos)
            for otro in mios[1:]:
                padre[raiz(otro)] = raiz(mios[0])
    grupos: Dict[int, Set[int]] = defaultdict(set)
    for p in productos:
        grupos[raiz(p)].add(p)
    return [grupos[k] for k in sorted(grupos)]


def _pct_neto(bono: SellInBonoMarca, pct: Decimal, item_id: int, iva: Optional[Decimal], fecha: date) -> Decimal:
    """The % that reaches the math: divided by (1 + the product's VAT rate) when loaded with VAT, by sell out's
    `monto_incluye_iva` rule (`tope.credito_unitario`)."""
    if bono.incluye_iva and iva is None:
        raise ValueError(f"bono {bono.id}: el producto {item_id} no tiene alícuota de IVA")
    campana = tope.Campana(tipo="por_unidad", moneda="ARS", monto_unit=pct, monto_incluye_iva=bono.incluye_iva)
    return tope.credito_unitario(campana, tope.Linea("", 0, item_id, fecha, 1, iva_pct=iva or Decimal(0)))


def _componente(
    bonos: List[SellInBonoMarca],
    alcances: Dict[int, Set[int]],
    modelos: Dict[int, Dict[int, Optional[Decimal]]],
    iva: Dict[int, Optional[Decimal]],
    ventas: List[alcance.Venta],
    fifo: Dict[Clave, int],
    pendientes: Dict[int, int],
) -> Dict[Tuple[int, str, int], _Fila]:
    """The desired rows of one component: its bonuses in id order over its sales (module docstring)."""
    deseadas: Dict[Tuple[int, str, int], _Fila] = {}
    usado: Dict[Clave, Decimal] = defaultdict(Decimal)  # per sale: what earlier bonuses give per unit
    for bono in bonos:
        lineas: List[tope.Linea] = []
        unitarios: Dict[Clave, Decimal] = {}
        for v in sorted(ventas, key=lambda x: x.unidades < 0):  # sales first: a return checks its sale
            if v.item_id not in alcances[bono.id] or not (bono.fecha_desde <= v.fecha <= bono.fecha_hasta):
                continue
            clave = (v.canal, v.venta_ref)
            if v.unidades > 0:
                if v.costo_unit is None:
                    pendientes[bono.id] = pendientes.get(bono.id, 0) + 1
                    continue
                propio = modelos.get(bono.id, {}).get(v.item_id)
                pct = Decimal(propio if propio is not None else bono.porcentaje)
                unitario = v.costo_unit * _pct_neto(bono, pct, v.item_id, iva.get(v.item_id), v.fecha) / CIEN
                unitario = min(unitario, v.costo_unit - usado[clave])
                if unitario <= 0:
                    continue
                unitarios[clave] = unitario
                ocupadas = min(fifo.get(clave, 0), v.unidades)
            else:
                if v.objetivo is not None and v.objetivo not in unitarios:
                    continue  # it returns a sale this bonus does not count
                ocupadas = 0  # the FIFO's rows are net of the return already: it frees its units here in full
            lineas.append(
                tope.Linea(
                    canal=v.canal,
                    venta_ref=v.venta_ref,
                    item_id=v.item_id,
                    fecha=v.fecha,
                    unidades=v.unidades,
                    base_unit=unitarios.get(clave),
                    ocupadas=ocupadas,
                    objetivo=v.objetivo,
                )
            )
        campana = tope.Campana(
            tipo="porcentaje",
            moneda="ARS",
            porcentaje=CIEN,
            tope_unidades=bono.tope_unidades,
            tope_monto=Decimal(bono.tope_monto) if bono.tope_monto is not None else None,
        )
        for x in tope.asignar(campana, lineas):
            clave = (x.canal, x.venta_ref)
            deseadas[(bono.id, x.canal, x.venta_ref)] = (x.item_id, x.fecha_venta, x.unidades, x.monto)
            usado[clave] += unitarios[clave]
    return deseadas


def recalcular(db: Session, item_ids: Iterable[int] = (), *, bono_ids: Iterable[int] = ()) -> CostoResult:
    """Brings the cost bonuses' rows of the given products, and of the given bonuses, in line (module docstring)."""
    items = {int(i) for i in item_ids if i is not None}
    dados = {int(i) for i in bono_ids}
    activos = _activos(db)
    if not activos and not dados:
        return CostoResult()
    alcances = _alcances(db, activos)
    productos = _cerrar(activos, alcances, _semilla(db, items, dados, alcances))
    bloqueados: Set[int] = set()
    while productos - bloqueados:
        _bloquear(db, productos - bloqueados)
        bloqueados |= productos
        # Again under the lock: a bonus changed meanwhile may reach (or cap) more products.
        activos = _activos(db)
        alcances = _alcances(db, activos)
        productos = _cerrar(activos, alcances, _semilla(db, items, dados, alcances))
    result = CostoResult(products=len(productos))
    if not productos:
        return result

    ids = sorted(productos)
    alcanzados = {p for bid in activos for p in alcances[bid] & productos}
    iva = {
        int(i): Decimal(str(v)) if v is not None else None
        for i, v in db.query(ProductoERP.item_id, ProductoERP.iva).filter(ProductoERP.item_id.in_(ids))
    }
    modelos: Dict[int, Dict[int, Optional[Decimal]]] = defaultdict(dict)
    if activos:
        for bid, item_id, pct in db.query(
            SellInBonoItem.bono_id, SellInBonoItem.item_id, SellInBonoItem.porcentaje
        ).filter(SellInBonoItem.bono_id.in_(sorted(activos))):
            modelos[bid][item_id] = pct
    ventas: List[alcance.Venta] = []
    if alcanzados:
        desde = min(b.fecha_desde for b in activos.values())
        hasta = max(b.fecha_hasta for b in activos.values())
        ventas = alcance.ventas(db, alcanzados, desde, hasta)
    fifo: Dict[Clave, int] = {
        (canal, int(ref)): int(unidades)
        for canal, ref, unidades in db.query(
            SellInConsumo.canal, SellInConsumo.venta_ref, func.sum(SellInConsumo.unidades)
        )
        .filter(SellInConsumo.item_id.in_(ids))
        .group_by(SellInConsumo.canal, SellInConsumo.venta_ref)
    }

    deseadas: Dict[Tuple[int, str, int], _Fila] = {}
    fallidos: Set[int] = set()
    for componente in _componentes(activos, alcances, productos):
        suyos = [b for b in activos.values() if alcances[b.id] & componente]
        try:
            deseadas.update(
                _componente(
                    suyos,
                    alcances,
                    modelos,
                    iva,
                    [v for v in ventas if v.item_id in componente],
                    fifo,
                    result.pendientes,
                )
            )
        except ValueError as exc:
            error = str(exc)[:500]
            fallidos |= componente
            result.failed.update({p: error for p in componente})
            result.bonos_fallidos.update({b.id: error for b in suyos})
            for b in suyos:
                result.productos_fallidos.setdefault(b.id, set()).update(componente)

    guardadas: Dict[Tuple[int, str, int], Tuple[int, _Fila]] = {}
    t = SellInBonoConsumo
    for rid, bid, canal, ref, item_id, fecha, unidades, monto in (
        db.query(t.id, t.bono_id, t.canal, t.venta_ref, t.item_id, t.fecha_venta, t.unidades, t.descuento_ars)
        .join(SellInBonoMarca, SellInBonoMarca.id == t.bono_id)
        .filter(t.item_id.in_(ids), SellInBonoMarca.base == BASE)
    ):
        # Only cost bonuses' rows: a row of any other kind is never this call's to delete.
        guardadas[(bid, canal, ref)] = (rid, (item_id, fecha, unidades, Decimal(monto)))
    # A failed component keeps its rows; a sale re-filed into another product keeps its key there too.
    retenidas = {clave for clave, (_, fila) in guardadas.items() if fila[0] in fallidos}
    borrar = [rid for clave, (rid, fila) in guardadas.items() if clave not in retenidas and deseadas.get(clave) != fila]
    filas = [
        {
            "bono_id": clave[0],
            "canal": clave[1],
            "venta_ref": clave[2],
            "item_id": fila[0],
            "fecha_venta": fila[1],
            "unidades": fila[2],
            "descuento_ars": fila[3],
        }
        for clave, fila in deseadas.items()
        if clave not in retenidas and guardadas.get(clave, (None, None))[1] != fila
    ]
    if borrar:
        db.execute(delete(SellInBonoConsumo).where(SellInBonoConsumo.id.in_(borrar)))
    if filas:
        db.execute(insert(SellInBonoConsumo), filas)
    result.inserted, result.deleted = len(filas), len(borrar)
    return result


def seguir_fifo(db: Session, item_ids: Iterable[int]) -> None:
    """Right after a write that moved the FIFO of `item_ids` outside `sell.drain` (the invoice reconcile, loading or
    voiding a manual purchase): their cost bonuses follow in the same transaction, so the exclusivity holds. It never
    blocks that write: it runs in a savepoint whose statements wait at most `LOCK_TIMEOUT` for a lock (a capped
    bonus's other products may be locked by a drain), and ANY error rolls back only that savepoint and is logged.
    The FIFO's new units then commit while the cost-bonus rows still hold the same units, so the active cost bonuses
    reaching the products are queued (`sell_in_bono_dirty`, `('bono', id)`) in the caller's transaction: they commit
    with the write and the `sell_in.bono` drain recomputes them (verifier B1). A product whose cost bonus cannot be
    computed (a missing VAT rate) keeps its rows, logged; queuing it would only fail again."""
    item_ids = set(item_ids)
    try:
        with sell_out_queue.lock_timeout(db, LOCK_TIMEOUT):
            fallidos = recalcular(db, item_ids).failed
    except Exception:  # noqa: BLE001 - the purchase or reconcile that called it must commit
        logger.exception("sell in: the %% of cost bonuses were not recomputed for products %s", sorted(item_ids))
        _encolar(db, item_ids)
        return
    if fallidos:
        logger.warning(
            "sell in: the %% of cost bonuses of %s product(s) were left as they were: %s", len(fallidos), fallidos
        )


# The bonus key the queue's triggers write (`bono_queue`), with the same refresh on conflict.
_ENCOLAR_BONO = text(
    "INSERT INTO sell_in_bono_dirty (tipo, ref) VALUES ('bono', :ref) "
    "ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL"
)


def _encolar(db: Session, item_ids: Set[int]) -> None:
    """Queues the active cost bonuses reaching `item_ids` for the `sell_in.bono` drain, in a savepoint of the caller's
    transaction. If even that fails, an ERROR says which products stay stale until their next drain."""
    try:
        with db.begin_nested():
            activos = _activos(db)
            bonos = sorted(bid for bid, productos in _alcances(db, activos).items() if productos & item_ids)
            for bid in bonos:
                db.execute(_ENCOLAR_BONO, {"ref": bid})
            if bonos:
                db.execute(text("SELECT pg_notify(:canal, '')"), {"canal": bono_queue.CHANNEL})
    except Exception:  # noqa: BLE001 - the purchase or reconcile that called it must commit
        logger.exception("sell in: the cost bonuses of products %s could not be queued; stale until a drain", item_ids)


def registrar_fallidos(result: CostoResult, origen: str) -> None:
    """One ERROR per failed cost bonus (its products and why), so it reaches alerting without charging anything."""
    for bono_id, error in sorted(result.bonos_fallidos.items()):
        productos = sorted(result.productos_fallidos.get(bono_id, ()))
        logger.error("%s: cost bonus (bono %s) not recomputed for products %s: %s", origen, bono_id, productos, error)

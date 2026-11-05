"""`SellInCosting`: how a sell in reaches the cost of the units sold
(sell-in-sell-out T5).

The strategy is the ONLY thing that turns sell-in purchases plus sales into
`sell_in_consumos`. Loading a purchase, the split selector and the screens never
depend on how.

`FifoPurchaseCosting` (option A, active): a sale's units come out of the
product's purchase lines in FIFO order (`fifo.asignar`); what they carry
follows the product's dated cost modes (`sell_in_modos_producto`: FIFO by
default, weighted or last price from a row's `desde` on, see `fifo`). Each
call recomputes whole PRODUCTS from scratch (their active purchase lines and
their sales since the oldest of those lines counts) and writes only the
difference against the stored consumptions, so:

- a re-run writes nothing (idempotent);
- a deleted sale, a quantity or date change, or a sale moved to another
  product frees its units and the next sales in line take them, as long as the
  caller recomputes every product the line touched (old and new);
- a voided purchase (`estado = 'anulada'`) is not a source any more, so its
  consumptions go away and later purchases take over;
- a line counting from the goods receipt (`cuenta_desde = 'ingreso'`) with no
  `fecha_ingreso` has not started: its units are not available yet (fail-safe;
  the table's check forbids such a row anyway).
- a manual mode row (D6) is a lot of its own (`fifo.lote_manual`): its
  consumptions are filed under the row (`modo_id`, no purchase line), and
  everywhere a line id keys a lot here, the block's is `-modo_id`.

Amounts are compared and written at `sell_in_consumos.descuento_ars`'s scale,
so a re-run never rewrites a row only because of precision the column drops.

Sources per channel (one `venta_ref` keyspace each, like `sell_dirty`):

- `ml`: `ml_sale_lines` (`item_row_id`, `product`, `day`, `qty`);
- `fuera` / `tn`: `ventas_fuera_ml_metricas` / `ventas_tienda_nube_metricas`
  (`it_transaction`, `item_id`, the UTC date of `fecha_venta` — stored at
  midnight UTC —, `signo * cantidad`).

Returns (owner's decision, 2026-10-17): every return (negative `signo *
cantidad`, e.g. a fuera credit note `signo = -1`) gives its units back
(`fifo.asignar`). The sale that loses them is the customer's ONLY earlier sale
of the product (same `cust_id` and `item_id`, earlier by `(fecha_venta,
it_transaction)`); with zero or several candidates, the most recent earlier
sale still holding units. A unique candidate dated before the purchase counts
held nothing (it is not among the sales passed to `fifo.asignar`), so that
return falls back to the most recent holder too: every return releases units.
Measured on prod: 283 of 409 fuera product returns
have exactly one candidate, 89 several, 37 none. Our sale tables carry no
reference to the original sale, so a recompute reads the CURRENT rows: a new,
deleted or changed return or sale re-queues its line through the fuera / TN
triggers and the drain recomputes the product. A `cust_id`-only change is not
in the triggers' `ALLOCATION_COLUMNS`: it takes effect on the product's next
recompute (any other change to it, or the backfill).

ERP independence (owner's rule, 2026-10-17): this process reads only the
app's own tables (`ml_sale_lines`, `ventas_fuera_ml_metricas`,
`ventas_tienda_nube_metricas`, `sell_in_*`), never an ERP mirror (`tb_*`), so
replacing the ERP does not change it.

Combos (owner, 2026-11-05: "El combo consume los lotes de sell in de cada
componente"): a combo line is, for each component, a sale of `qty x cantidad`
units under the component's `item_id` with the line's own `venta_ref`
(`app.services.combos.ventas`); the combo never consumes its own lots. Like ML
costing, the FIFO refuses while the bill of materials is unsynced
(`CombosNoSincronizados`) instead of counting a combo as a plain item.

A USD purchase is consumed in pesos at the purchase's own `tipo_cambio`, never at the
sale-date rate: the owner's decision (2026-10-17).

Concurrency: every recompute takes `pg_advisory_xact_lock(LOCK_NAMESPACE,
item_id)` for its products, in item order, BEFORE reading, so two drains (or a
drain and a purchase being loaded or voided) never interleave on one product
and never deadlock. Load is set-based: a handful of queries per call whatever
the number of products, then one DELETE and one INSERT per product that changed.
Measured on prod (2026-10-17): at most ~3.4k ML lines per product per year, so
recomputing a product from scratch needs no derived table.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Optional, Protocol, Tuple, runtime_checkable

from sqlalchemy import delete, func, insert, or_, text
from sqlalchemy.orm import Session

from app.models.ml_sale_line import MlSaleLine
from app.models.sell_in import SellInCompra, SellInCompraItem, SellInConsumo, SellInModoProducto
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
from app.services.combos.ventas import partes_de_combos, unidades_de
from app.services.sell_in.fifo import (
    Consumo,
    Dinero,
    Lote,
    Periodo,
    Venta,
    asignar,
    gobiernan,
    lote_manual,
    orden_fifo,
    periodo_en,
)
from app.services.sell_in.split import unit_discount

logger = logging.getLogger(__name__)

# First key of the two-key advisory lock; the second is the product's item_id.
LOCK_NAMESPACE = 0x5E11

LOCK_SQL = text(
    "SELECT pg_advisory_xact_lock(:ns, i) FROM (SELECT DISTINCT i FROM unnest(CAST(:ids AS integer[])) AS t(i) "
    "ORDER BY i) AS ordered"
)
VENTAS_FACTURADAS = (("fuera", VentaFueraMLMetrica), ("tn", VentaTiendaNubeMetrica))


@dataclass
class RecomputeResult:
    products: int = 0
    inserted: int = 0
    deleted: int = 0
    # item_id -> error, for the products whose recompute failed (rolled back alone).
    failed: Dict[int, str] = field(default_factory=dict)
    # Set by `sell.drain` (T25b): the % of cost bonuses that could not be recomputed after this FIFO run.
    bonos_costo_fallidos: int = 0


@runtime_checkable
class SellInCosting(Protocol):
    def recompute(self, db: Session, item_ids: Iterable[int], *, isolate_failures: bool = True) -> RecomputeResult:
        """Bring the stored consumptions of `item_ids` in line with the strategy.
        Does not commit. With `isolate_failures`, a product whose allocation or
        write fails is rolled back on its own (a savepoint) and reported in
        `failed` while the others are written; otherwise the error propagates and
        the caller rolls back. The batch reads shared by every product (purchase
        lines, sales, stored consumptions) run before that and always propagate."""
        ...

    def vigentes(self, db: Session, item_ids: Iterable[int], hoy: date) -> Dict[int, "LoteVigente"]:
        """`{item_id: what a sale on `hoy` would be discounted}` for the products that have it, from
        the stored consumptions (read only; a product with none is absent)."""
        ...

    def lotes(self, db: Session, item_ids: Iterable[int]) -> Dict[int, List[Lote]]:
        """Each product's lines of active purchases, in the order its sales consume them (read only)."""
        ...

    def unidades_usadas(self, db: Session, lineas: List[int]) -> Dict[int, int]:
        """`{compra_item_id: units the stored consumptions took}`, for the lines that have any (read only)."""
        ...

    def periodos(self, db: Session, ids: List[int]) -> Dict[int, List[Periodo]]:
        """`{item_id: its dated cost modes, oldest first}` for the products that have any; without, FIFO (read only)."""
        ...

    def sin_asignar(self, db: Session, item_id: int, hoy: date) -> Decimal:
        """ARS the product's lots hold that no unit hands out, sold or left (positive: never handed out)."""
        ...


@dataclass(frozen=True)
class LoteVigente:
    """The purchase line the next sale of a product takes its sell in from."""

    compra_item_id: int
    descuento_unit_ars: Decimal  # rounded like `split.unit_discount`
    unidades_restantes: int
    # True when a weighted or last-price mode governs and its replay gave the value: every unit of the lines that
    # count goes at it. False under FIFO, or when the replay could not run and the line's own value stands.
    en_pool: bool = False
    # Under a pool, what a sale on the next lot's start date gets once that lot joins it; None otherwise.
    siguiente_unit_ars: Optional[Decimal] = None
    # The day the next sale is valued on: `hoy`, or the latest stored sale when one is dated later. Lots counting by
    # then are already inside the pool.
    dia: Optional[date] = None


def utc_date(value) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.date()
    return value


def unidades_firmadas(signo, cantidad) -> int:
    return int(Decimal(cantidad) * (signo if signo is not None else 1))


def resolver_objetivos(db: Session, model, devoluciones: List[tuple]) -> Dict[int, int]:
    """`{return ref: the sale it reverses}` for the returns whose customer has EXACTLY ONE
    earlier sale of the product: same `cust_id` and `item_id`, earlier by
    `(fecha_venta, it_transaction)`, over the whole history (a sale before the
    purchase counts as a candidate too; it holds no units, so `fifo.asignar` then
    falls back to the most recent holder). One query for every return of the batch."""
    con_cliente = [d for d in devoluciones if d[4] is not None]
    if not con_cliente:
        return {}
    items = sorted({d[1] for d in con_cliente})
    clientes = sorted({d[4] for d in con_cliente})
    hasta = datetime.combine(max(d[2] for d in con_cliente), time.max, tzinfo=timezone.utc)
    candidatas: Dict[Tuple[int, int], List[Tuple[date, int]]] = defaultdict(list)
    rows = db.query(model.it_transaction, model.item_id, model.cust_id, model.fecha_venta, model.signo, model.cantidad)
    for ref, item_id, cust_id, fecha, signo, cantidad in rows.filter(
        model.item_id.in_(items), model.cust_id.in_(clientes), model.fecha_venta <= hasta
    ):
        if unidades_firmadas(signo, cantidad) > 0:
            candidatas[(item_id, cust_id)].append((utc_date(fecha), ref))
    objetivos: Dict[int, int] = {}
    for ref, item_id, fecha, _, cust_id in con_cliente:
        previas = [c for c in candidatas.get((item_id, cust_id), []) if c < (fecha, ref)]
        if len(previas) == 1:
            objetivos[ref] = previas[0][1]
    return objetivos


_DESCUENTO_SCALE = Decimal(1).scaleb(-SellInConsumo.__table__.c.descuento_ars.type.scale)


def fuente(t=SellInConsumo):
    """A consumption's lot as the allocation keys it: its purchase line, or `-modo_id` for a manual block's."""
    return func.coalesce(t.compra_item_id, -t.modo_id)


def de_lotes(lineas: List[int], t=SellInConsumo):
    """The filter for the consumptions of `lineas` (lot ids as `fuente` gives them)."""
    compras = [linea for linea in lineas if linea > 0]
    bloques = [-linea for linea in lineas if linea < 0]
    return or_(t.compra_item_id.in_(compras), t.modo_id.in_(bloques))


def _a_columna(monto: Decimal) -> Decimal:
    """`monto` at the scale `sell_in_consumos.descuento_ars` stores, rounded half up like Postgres."""
    return Decimal(monto).quantize(_DESCUENTO_SCALE, rounding=ROUND_HALF_UP)


_Key = Tuple[str, int, int]  # (canal, venta_ref, lot: compra_item_id, or -modo_id for a manual block)


class FifoPurchaseCosting:
    """Option A: FIFO over the units of each purchase."""

    def recompute(self, db: Session, item_ids: Iterable[int], *, isolate_failures: bool = True) -> RecomputeResult:
        ids = sorted({int(i) for i in item_ids if i is not None})
        result = RecomputeResult(products=len(ids))
        if not ids:
            return result
        if db.get_bind().dialect.name == "postgresql":
            db.execute(LOCK_SQL, {"ns": LOCK_NAMESPACE, "ids": ids})

        lotes, periodos = self._con_bloques(db, ids)
        ventas = self._ventas(db, lotes)
        guardados = self._guardados(db, ids)

        for item_id in ids:
            # The whole per-product work (allocation AND write) runs inside the
            # isolation, so one product's bad data never aborts the batch.
            args = (
                db,
                item_id,
                lotes.get(item_id, []),
                ventas.get(item_id, []),
                guardados.get(item_id, {}),
                periodos.get(item_id, []),
            )
            if isolate_failures:
                try:
                    with db.begin_nested():
                        borrados, insertados = self._producto(*args)
                except Exception as exc:  # noqa: BLE001 - one product must not block the rest
                    result.failed[item_id] = f"{type(exc).__name__}: {exc}"[:500]
                    continue
            else:
                borrados, insertados = self._producto(*args)
            result.deleted += borrados
            result.inserted += insertados
        return result

    def vigentes(self, db: Session, item_ids: Iterable[int], hoy: date) -> Dict[int, LoteVigente]:
        """The first line in FIFO order (`fifo`: `fecha`, `compra_id`, `compra_item_id`) counting on or
        before `hoy` with units the stored consumptions left; a product whose lines are used up is
        absent: its cost is back to normal. Three queries (lines, units used, cost modes), whatever the
        number of products.

        A product with cost modes replays its stored consumptions through `fifo.Dinero`, so the value is the one
        the mode governing `hoy` gives (the weighted pool, or the newest lot for every unit left); its line is still
        the FIFO one the units come from (under a manual block, the block: `-modo_id`). One more query, only when some
        product has modes. A product whose modes cannot be replayed here (rows read mid-change) keeps its FIFO line at the
        line's own value and is logged: it still has units, so it never reads as used up, and never the whole batch."""
        lotes, periodos = self._con_bloques(db, sorted({int(i) for i in item_ids if i is not None}))
        usadas = self.unidades_usadas(db, [lote.compra_item_id for item in lotes.values() for lote in item])
        salida: Dict[int, LoteVigente] = {}
        for item_id, item in lotes.items():
            for lote in item:
                restantes = lote.cantidad - usadas.get(lote.compra_item_id, 0)
                if lote.fecha <= hoy and restantes > 0:
                    descuento = unit_discount(lote.descuento_ars, lote.cantidad)
                    salida[item_id] = LoteVigente(lote.compra_item_id, descuento, restantes)
                    break
        con_modos = {item_id: item for item_id, item in lotes.items() if item_id in periodos}
        filas = self._filas_guardadas(db, [lote.compra_item_id for item in con_modos.values() for lote in item])
        for item_id, item in con_modos.items():
            try:
                dinero, dia = self._replay(item, periodos[item_id], filas.get(item_id, []), hoy)
                proximo = dinero.proximo(dia)
            except (ValueError, ArithmeticError, KeyError) as exc:
                # A mode the replay does not support yet, or rows read mid-change by another transaction.
                logger.warning("sell in: next sale of product %s not computed: %s", item_id, exc)
                continue
            if proximo is not None:
                i, monto, sobre, restantes = proximo
                en_pool = periodo_en(periodos[item_id], dia)[1] not in ("fifo", "manual")
                siguiente = self._siguiente(dinero, item, periodos[item_id], dia) if en_pool else None
                salida[item_id] = LoteVigente(
                    item[i].compra_item_id, unit_discount(monto, sobre), restantes, en_pool, siguiente, dia
                )
        return salida

    def sin_asignar(self, db: Session, item_id: int, hoy: date) -> Decimal:
        """ARS the product's lots hold that neither its stored consumptions nor its units left hand out, the units left
        valued as a sale on the replay day would get them (`_replay`): what the mode preview shows (D2, D5). Zero under
        FIFO and `ponderado` but for rounding; `ultimo` and a switch back to FIFO from a pool can leave money unhanded
        (positive) or hand out more than the lots hold (negative). Raises like the replay."""
        lotes, periodos = self._con_bloques(db, [item_id])
        item = lotes.get(item_id, [])
        if not item:
            return Decimal("0.00")
        lineas = [lote.compra_item_id for lote in item]
        filas = self._filas_guardadas(db, lineas).get(item_id, [])
        dinero, dia = self._replay(item, periodos.get(item_id, []), filas, hoy)
        dado = db.query(func.coalesce(func.sum(SellInConsumo.descuento_ars), 0)).filter(de_lotes(lineas))
        total = sum((lote.descuento_ars for lote in item), Decimal(0))
        resto = total - Decimal(dado.scalar()) - dinero.restante(dia)
        return resto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _replay(
        item: List[Lote], periodos: List[Periodo], filas: List[Tuple[int, date, int]], hoy: date
    ) -> Tuple[Dinero, date]:
        """The money pass fed with a product's stored consumptions, and the day the next sale is valued on: after
        every stored one, even one dated after `hoy` (a later UTC day)."""
        indice = {lote.compra_item_id: i for i, lote in enumerate(item)}
        dinero = Dinero(item, periodos)
        dia = hoy
        for linea, fecha, unidades in filas:
            dinero.fila(fecha, indice[linea], unidades)
            dia = max(dia, fecha)
        return dinero, dia

    @staticmethod
    def _siguiente(dinero: Dinero, item: List[Lote], periodos: List[Periodo], hoy: date) -> Optional[Decimal]:
        """What a sale on the next lot's start date gets once that lot joins the pool; None when no lot starts later,
        when FIFO or a manual block governs that date (the lot is then at its own value), or when that date cannot be
        replayed: today's value stands either way."""
        futuro = next((lote for lote in item if lote.fecha > hoy), None)
        if futuro is None or periodo_en(periodos, futuro.fecha)[1] in ("fifo", "manual"):
            return None
        try:
            despues = dinero.proximo(futuro.fecha)
        except (ValueError, ArithmeticError, KeyError):
            return None
        return unit_discount(despues[1], despues[2]) if despues is not None else None

    @staticmethod
    def _filas_guardadas(db: Session, lineas: List[int]) -> Dict[int, List[Tuple[int, date, int]]]:
        """`{item_id: [(line, sale date, units), ...]}` of the stored consumptions of `lineas`, in sale order (the
        order of one sale's lines does not change what the money pass is left with)."""
        if not lineas:
            return {}
        t = SellInConsumo
        filas = (
            db.query(t.item_id, fuente(), t.fecha_venta, t.unidades)
            .filter(de_lotes(lineas))
            .order_by(t.item_id, t.fecha_venta, t.canal, t.venta_ref, fuente())
        )
        salida: Dict[int, List[Tuple[int, date, int]]] = defaultdict(list)
        for item_id, linea, fecha, unidades in filas:
            salida[item_id].append((linea, fecha, unidades))
        return salida

    def lotes(self, db: Session, item_ids: Iterable[int]) -> Dict[int, List[Lote]]:
        """Each product's lines of active purchases, in the order its sales consume them (`fifo.orden_fifo`)."""
        return self._con_bloques(db, sorted({int(i) for i in item_ids if i is not None}))[0]

    @staticmethod
    def unidades_usadas(db: Session, lineas: List[int]) -> Dict[int, int]:
        """`{compra_item_id: units the stored consumptions took}`, for the lines that have any."""
        if not lineas:
            return {}
        t = SellInConsumo
        filas = db.query(fuente(), func.sum(t.unidades)).filter(de_lotes(lineas))
        return {linea: int(unidades) for linea, unidades in filas.group_by(fuente())}

    @classmethod
    def periodos(cls, db: Session, ids: List[int]) -> Dict[int, List[Periodo]]:
        """`{item_id: its cost modes, oldest first}` (`sell_in_modos_producto`; same `desde`: by id, the one saved
        last after), for the products that have any; a product without is FIFO."""
        return cls._modos(db, ids)[0]

    @staticmethod
    def _modos(db: Session, ids: List[int]) -> Tuple[Dict[int, List[Periodo]], Dict[int, List[Lote]]]:
        """One query: each product's periods (`periodos`), and the block of each manual row that governs some day
        (`fifo.lote_manual`): its typed units, each at the frozen cost minus the typed cost (signed, unrounded)."""
        if not ids:
            return {}, {}
        m = SellInModoProducto
        filas = (
            db.query(m.item_id, m.desde, m.modo, m.id, m.cantidad, m.costo_unit, m.costo_base_unit)
            .filter(m.item_id.in_(ids))
            .order_by(m.item_id, m.desde, m.id)
        )
        periodos: Dict[int, List[Periodo]] = defaultdict(list)
        manuales: Dict[int, tuple] = {}
        for item_id, desde, modo, modo_id, cantidad, costo, base in filas:
            periodos[item_id].append(Periodo(desde, modo, modo_id if modo == "manual" else None))
            if modo == "manual":
                manuales[modo_id] = (cantidad, Decimal(base) - Decimal(costo))
        bloques: Dict[int, List[Lote]] = defaultdict(list)
        for item_id, item in periodos.items():
            for k in gobiernan(item):
                if item[k].modo == "manual":
                    cantidad, valor = manuales[item[k].modo_id]
                    bloques[item_id].append(lote_manual(item[k].modo_id, item[k].desde, cantidad, valor * cantidad))
        return periodos, bloques

    @classmethod
    def _con_bloques(cls, db: Session, ids: List[int]) -> Tuple[Dict[int, List[Lote]], Dict[int, List[Periodo]]]:
        """Each product's lots (purchase lines and manual blocks, FIFO order) and periods: two queries."""
        lotes = cls._lotes(db, ids) if ids else {}
        periodos, bloques = cls._modos(db, ids)
        for item_id, item in bloques.items():
            lotes.setdefault(item_id, []).extend(item)
        return {item_id: sorted(item, key=orden_fifo) for item_id, item in lotes.items()}, periodos

    @classmethod
    def _producto(
        cls,
        db: Session,
        item_id: int,
        lotes: List[Lote],
        ventas: List[Venta],
        guardados: Dict[_Key, tuple],
        periodos: List[Periodo],
    ) -> Tuple[int, int]:
        return cls._escribir(db, item_id, asignar(lotes, ventas, periodos), guardados)

    @staticmethod
    def _lotes(db: Session, ids: List[int]) -> Dict[int, List[Lote]]:
        rows = (
            db.query(
                SellInCompraItem.id,
                SellInCompraItem.item_id,
                SellInCompraItem.cantidad,
                SellInCompraItem.monto_asignado,
                SellInCompra.id,
                SellInCompra.fecha_compra,
                SellInCompra.fecha_ingreso,
                SellInCompra.cuenta_desde,
                SellInCompra.moneda,
                SellInCompra.tipo_cambio,
            )
            .join(SellInCompra, SellInCompra.id == SellInCompraItem.compra_id)
            .filter(SellInCompraItem.item_id.in_(ids), SellInCompra.estado == "activa")
        )
        lotes: Dict[int, List[Lote]] = defaultdict(list)
        for linea_id, item_id, cantidad, monto, compra_id, f_compra, f_ingreso, desde, moneda, tc in rows:
            fecha = f_ingreso if desde == "ingreso" else f_compra
            if fecha is None:
                # Counting from a goods receipt that has not happened: the purchase
                # has not started, so its units are not available yet (fail-safe; the
                # `ck_sell_in_compras_ingreso_con_fecha` check forbids it anyway).
                continue
            factor = Decimal(tc) if moneda == "USD" else Decimal(1)
            lotes[item_id].append(
                Lote(
                    compra_item_id=linea_id,
                    compra_id=compra_id,
                    fecha=fecha,
                    cantidad=cantidad,
                    descuento_ars=Decimal(monto) * factor,
                )
            )
        return lotes

    @staticmethod
    def _ventas(db: Session, lotes: Dict[int, List[Lote]]) -> Dict[int, List[Venta]]:
        """The positive sales of the products that have purchase lines, from the oldest line's date; a combo's line
        counts for each component that has lines, never for the combo itself (module docstring)."""
        if not lotes:
            return {}
        combos = partes_de_combos(db, lotes)
        ids = sorted(set(lotes) | set(combos))

        def destinos(item_id: int, unidades: int) -> List[Tuple[int, int]]:
            if item_id in combos:
                return [(p.componente, unidades_de(unidades, p)) for p in combos[item_id] if p.componente in lotes]
            return [(item_id, unidades)] if item_id in lotes else []

        desde = min(lote.fecha for item in lotes.values() for lote in item)
        ventas: Dict[int, List[Venta]] = defaultdict(list)
        ml = db.query(MlSaleLine.item_row_id, MlSaleLine.product, MlSaleLine.day, MlSaleLine.qty).filter(
            MlSaleLine.product.in_(ids), MlSaleLine.day >= desde, MlSaleLine.qty > 0
        )
        for ref, item_id, dia, qty in ml:
            for destino, unidades in destinos(item_id, int(qty)):
                ventas[destino].append(Venta("ml", ref, dia, unidades))
        inicio = datetime.combine(desde, time(0), tzinfo=timezone.utc)
        for canal, model in VENTAS_FACTURADAS:
            rows = db.query(
                model.it_transaction, model.item_id, model.fecha_venta, model.signo, model.cantidad, model.cust_id
            ).filter(model.item_id.in_(ids), model.fecha_venta >= inicio)
            devoluciones = []
            for ref, item_id, fecha, signo, cantidad, cust_id in rows:
                unidades = unidades_firmadas(signo, cantidad)
                if unidades > 0:
                    for destino, suyas in destinos(item_id, unidades):
                        ventas[destino].append(Venta(canal, ref, utc_date(fecha), suyas))
                elif unidades < 0:
                    devoluciones.append((ref, item_id, utc_date(fecha), unidades, cust_id))
            # Resolved on the sold item (the combo's own earlier sale), then given back by each component.
            objetivos = resolver_objetivos(db, model, devoluciones)
            for ref, item_id, fecha, unidades, _ in devoluciones:
                objetivo = objetivos.get(ref)
                for destino, suyas in destinos(item_id, unidades):
                    ventas[destino].append(Venta(canal, ref, fecha, suyas, (canal, objetivo) if objetivo else None))
        return ventas

    @staticmethod
    def _guardados(db: Session, ids: List[int]) -> Dict[int, Dict[_Key, tuple]]:
        rows = db.query(
            SellInConsumo.id,
            SellInConsumo.item_id,
            SellInConsumo.canal,
            SellInConsumo.venta_ref,
            fuente(),
            SellInConsumo.fecha_venta,
            SellInConsumo.unidades,
            SellInConsumo.descuento_ars,
        ).filter(SellInConsumo.item_id.in_(ids))
        guardados: Dict[int, Dict[_Key, tuple]] = defaultdict(dict)
        for cid, item_id, canal, ref, linea, fecha, unidades, descuento in rows:
            guardados[item_id][(canal, ref, linea)] = (cid, (fecha, unidades, Decimal(descuento)))
        return guardados

    @staticmethod
    def _escribir(db: Session, item_id: int, deseados: List[Consumo], guardados: Dict[_Key, tuple]) -> Tuple[int, int]:
        # Compared and written at the column's scale: an amount finer than what the
        # column stores would otherwise differ from its stored self on every re-run.
        nuevos = {
            (c.canal, c.venta_ref, c.compra_item_id): (c.fecha_venta, c.unidades, _a_columna(c.descuento_ars))
            for c in deseados
        }
        borrar = [cid for key, (cid, valores) in guardados.items() if nuevos.get(key) != valores]
        insertar = [
            {
                "compra_item_id": key[2] if key[2] > 0 else None,
                "modo_id": -key[2] if key[2] < 0 else None,
                "canal": key[0],
                "venta_ref": key[1],
                "item_id": item_id,
                "fecha_venta": valores[0],
                "unidades": valores[1],
                "descuento_ars": valores[2],
            }
            for key, valores in nuevos.items()
            if key not in guardados or guardados[key][1] != valores
        ]
        if borrar:
            db.execute(delete(SellInConsumo).where(SellInConsumo.id.in_(borrar)))
        if insertar:
            db.execute(insert(SellInConsumo), insertar)
        return len(borrar), len(insertar)


_COSTING: SellInCosting = FifoPurchaseCosting()


def get_costing() -> SellInCosting:
    """The active sell-in costing strategy (option A: FIFO by purchase)."""
    return _COSTING

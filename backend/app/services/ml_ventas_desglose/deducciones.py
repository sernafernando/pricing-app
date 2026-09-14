"""The Total Gauss deduction chain (ml-ventas-modo-logistico, PR5, design D1/D7).

`total_gauss` is `neto_sin_iva` (from `iva.descomponer_neto`, design D8) with
an ORDERED, EXTENSIBLE chain of deductions subtracted, entirely WITHOUT IVA
(the user's own formula: "Neto - envío flex - % = total gauss", stripped of
IVA first).

The chain is a plain tuple, `DEDUCCIONES`, walked in order with no hardcoded
length -- adding a fourth deduction is adding one entry, never touching the
orchestrator (`calcular_total_gauss`).

## `None` propagates, NEVER a lying zero (design D1, D7)

Every `resolve_bulk` returns `Optional[Decimal]` per order: `None` means
UNKNOWN, and an unknown single deduction makes the WHOLE order's
`total_gauss` unknown too -- never a partial sum that silently drops the
piece it could not resolve. `etiquetas_stats.py:416`'s `coalesce(..., 0)` is
the right call for an aggregate; it would be a lying zero here, one sale at
a time.

A KEY ABSENT from a resolver's returned dict means something different: the
deduction does NOT APPLY to that order at all (e.g. `EnvioFlexDeduccion` on
a `retiro` order -- there is no Flex cost to deduct, not an unresolved one).
An absent key contributes nothing and does not block; a present key with
value `None` blocks the whole chain for that order.

## Per-item cost rolls up all-or-nothing (design D7)

`CostoMercaderiaDeduccion` sums `costo_unitario_ars * quantity` over every
live item of an order; if EVEN ONE item lacks a frozen snapshot (PR3), the
order's cost -- and therefore its `total_gauss` -- is UNKNOWN as a whole,
never a partial sum over just the items that happen to have one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.ml_venta_deduccion import MlVentaDeduccion
from app.models.varios_venta_pct import VariosVentaPct
from app.services.ml_ventas_desglose.breakdown_service import resolve_flex_cost_by_order_ids

_CENT = Decimal("0.01")


@runtime_checkable
class DeduccionResolver(Protocol):
    """One entry of the ordered chain (design D1). `base` tells the
    orchestrator what a PERCENTAGE resolver's returned value multiplies:
    `"neto"` is `neto_sin_iva` (the chain's starting point, never touched by
    earlier deductions), `"corriente"` is the running total AFTER every
    earlier deduction in `orden`. Non-percentage resolvers ignore `base`."""

    code: str
    concepto: str
    orden: int
    base: str  # "neto" | "corriente"
    es_porcentaje: bool

    def resolve_bulk(self, db: Session, order_ids: Sequence[int]) -> Dict[int, Optional[Decimal]]: ...


class CostoMercaderiaDeduccion:
    """The frozen cost of the goods sold (design D4/D7). Sums
    `costo_unitario_ars * quantity` over every live item of the order;
    `None` if any item lacks a frozen snapshot OR the order has no items at
    all -- never a partial sum."""

    code = "costo_mercaderia"
    concepto = "Costo de mercadería"
    orden = 1
    base = "neto"
    es_porcentaje = False

    def resolve_bulk(self, db: Session, order_ids: Sequence[int]) -> Dict[int, Optional[Decimal]]:
        order_ids = list(order_ids)
        result: Dict[int, Optional[Decimal]] = {}
        if not order_ids:
            return result

        items = db.query(MlOrderItemOps).filter(MlOrderItemOps.order_id.in_(order_ids)).all()
        items_by_order: Dict[int, List[MlOrderItemOps]] = {}
        for item in items:
            items_by_order.setdefault(item.order_id, []).append(item)

        costos = db.query(MlOrderItemCosto).filter(MlOrderItemCosto.order_id.in_(order_ids)).all()
        costo_by_key: Dict[Tuple[int, str, Optional[int]], MlOrderItemCosto] = {
            (c.order_id, c.item_id, c.variation_id): c for c in costos
        }

        for order_id in order_ids:
            order_items = items_by_order.get(order_id, [])
            if not order_items:
                # No items at all -- nothing to cost, and reporting a
                # known $0 here would be a lie: it reads as "this order
                # cost nothing", not "we don't know what it cost".
                result[order_id] = None
                continue

            total = Decimal("0")
            resolved_all = True
            for item in order_items:
                key = (item.order_id, item.item_id, item.variation_id)
                costo = costo_by_key.get(key)
                if costo is None or item.quantity is None:
                    resolved_all = False
                    break
                total += (costo.costo_unitario_ars * item.quantity).quantize(_CENT, rounding=ROUND_HALF_UP)
            result[order_id] = total if resolved_all else None

        return result


class EnvioFlexDeduccion:
    """The seller's OWN Flex shipping cost (design D1). Applies ONLY to
    `self_service` orders -- reuses `resolve_flex_cost_by_order_ids`
    (`breakdown_service.py`), never reimplements the resolution rule.
    A non-Flex order simply gets no key (not applicable); a Flex order
    whose cost cannot be resolved gets `None` (`flex_cost_unknown`,
    same discipline as `compute_breakdown`'s line)."""

    code = "envio_flex"
    concepto = "Envío Flex (costo propio)"
    orden = 2
    base = "neto"
    es_porcentaje = False

    def resolve_bulk(self, db: Session, order_ids: Sequence[int]) -> Dict[int, Optional[Decimal]]:
        resuelto = resolve_flex_cost_by_order_ids(db, order_ids)

        # SPLIT across every order that shares the shipment, because the
        # freight is ONE cost, not one per order.
        #
        # A pack can hold several orders under a single `shipping_id`, and
        # charging each of them the whole shipment made the group total --
        # which sums its members -- count the same freight twice. The
        # precedent is already in this module's sibling: `compute_breakdown`
        # DEDUPES a pack's billing shipping charge for exactly this reason.
        #
        # The divisor comes from the DATABASE, not from `order_ids`: taking
        # it from the batch would make one order's cost depend on who else
        # happened to be on the same page, which is the kind of number that
        # changes when you scroll.
        shipping_by_order = dict(
            db.query(MlOrdersOps.order_id, MlOrdersOps.shipping_id)
            .filter(MlOrdersOps.order_id.in_(list(resuelto.keys())))
            .all()
        )
        shipping_ids = {sid for sid in shipping_by_order.values() if sid is not None}
        if not shipping_ids:
            return resuelto

        compartidos: Dict[int, int] = {}
        for shipping_id, cuantas in (
            db.query(MlOrdersOps.shipping_id, func.count(MlOrdersOps.order_id))
            .filter(MlOrdersOps.shipping_id.in_(sorted(shipping_ids)))
            .group_by(MlOrdersOps.shipping_id)
            .all()
        ):
            compartidos[shipping_id] = cuantas

        repartido: Dict[int, Optional[Decimal]] = {}
        for order_id, monto in resuelto.items():
            shipping_id = shipping_by_order.get(order_id)
            cuantas = compartidos.get(shipping_id, 1) if shipping_id is not None else 1
            if monto is None or cuantas <= 1:
                repartido[order_id] = monto
            else:
                repartido[order_id] = (monto / Decimal(cuantas)).quantize(_CENT, rounding=ROUND_HALF_UP)
        return repartido


class VariosDeduccion:
    """The "% de varios" (obs #2064): a NEW table, versioned by date,
    reading the version VIGENTE at the SALE's own date -- never today's,
    same rule PR2 applies to the Flex tariff.

    Returns the RATE (e.g. `Decimal("2.50")` for 2,5%), not an amount --
    `es_porcentaje=True` tells the orchestrator to multiply it against
    `base`.

    `base = "neto"` means the percentage applies to `neto_sin_iva`, the
    STARTING value, NOT to what is left after the cost of goods and the
    Flex freight have been subtracted. The formula reads
    `Neto - envio flex - % = Total Gauss`, which admits both readings, and
    the maintainer chose this one explicitly when asked. It also matches
    `calcular_comision_ml_total`, which applies `varios_porcentaje` to the
    price without IVA (obs #2064).

    The difference is not academic: on a $100.000 sale with $60.000 of
    goods and $5.000 of freight, 5% is $5.000 here and would be $1.750 the
    other way. Do not "fix" this into the running total."""

    code = "varios"
    concepto = "Varios (ventas)"
    orden = 3
    base = "neto"
    es_porcentaje = True

    def resolve_bulk(self, db: Session, order_ids: Sequence[int]) -> Dict[int, Optional[Decimal]]:
        order_ids = list(order_ids)
        result: Dict[int, Optional[Decimal]] = {}
        if not order_ids:
            return result

        orders = (
            db.query(MlOrdersOps.order_id, MlOrdersOps.date_created).filter(MlOrdersOps.order_id.in_(order_ids)).all()
        )
        versiones = db.query(VariosVentaPct).order_by(VariosVentaPct.fecha_desde.asc()).all()

        for order_id, date_created in orders:
            if date_created is None:
                result[order_id] = None
                continue
            fecha_venta = date_created.date() if hasattr(date_created, "date") else date_created
            vigente: Optional[VariosVentaPct] = None
            for version in versiones:
                if version.fecha_desde <= fecha_venta and (
                    version.fecha_hasta is None or version.fecha_hasta >= fecha_venta
                ):
                    vigente = version
            result[order_id] = Decimal(str(vigente.porcentaje)) if vigente is not None else None

        return result


# The chain, in resolution order (design D1). Extensible: `orden`/`len()`
# are never hardcoded anywhere else in this module -- adding a fourth
# deduction here is the ONLY change needed to grow the chain.
DEDUCCIONES: Tuple[DeduccionResolver, ...] = (
    CostoMercaderiaDeduccion(),
    EnvioFlexDeduccion(),
    VariosDeduccion(),
)


@dataclass(frozen=True)
class TotalGaussResultado:
    """`total_gauss` is `None` whenever `neto_sin_iva` itself is `None`
    (design D12's reconciliation failure) OR any APPLICABLE deduction in
    the chain resolved unknown (design D7). `lineas` lists every deduction
    that DID apply, in chain order, `(code, monto)` -- `monto` is `None`
    for the one that blocked the chain, so the UI can point at it."""

    total_gauss: Optional[Decimal]
    lineas: List[Tuple[str, Optional[Decimal]]] = field(default_factory=list)


def calcular_total_gauss(
    db: Session,
    order_ids: Sequence[int],
    neto_sin_iva_by_order: Dict[int, Optional[Decimal]],
) -> Dict[int, TotalGaussResultado]:
    """Applies `DEDUCCIONES` in order, per order_id, over the bulk-resolved
    result of EVERY registered deduction -- one `resolve_bulk` call per
    deduction TOTAL, never one per order (mirrors `descomponer_neto`'s own
    bulk shape).

    `total_gauss` is a materialised SORT/FILTER key only (design D2): this
    function is the ONE producer of the number, called both for live
    display (never served from the stored column) and by whatever
    persists the stored column for sorting.
    """
    order_ids = list(order_ids)
    result: Dict[int, TotalGaussResultado] = {}
    if not order_ids:
        return result

    resolved_by_code: Dict[str, Dict[int, Optional[Decimal]]] = {
        deduccion.code: deduccion.resolve_bulk(db, order_ids) for deduccion in DEDUCCIONES
    }

    for order_id in order_ids:
        neto_sin_iva = neto_sin_iva_by_order.get(order_id)
        total: Optional[Decimal] = neto_sin_iva
        lineas: List[Tuple[str, Optional[Decimal]]] = []

        for deduccion in DEDUCCIONES:
            by_order = resolved_by_code[deduccion.code]
            if order_id not in by_order:
                # Not applicable to this order -- contributes nothing and
                # never blocks the chain (D1: absence != unknown).
                continue

            raw = by_order[order_id]
            if raw is None:
                monto: Optional[Decimal] = None
            elif deduccion.es_porcentaje:
                objetivo = neto_sin_iva if deduccion.base == "neto" else total
                monto = (
                    None
                    if objetivo is None
                    else (objetivo * raw / Decimal("100")).quantize(_CENT, rounding=ROUND_HALF_UP)
                )
            else:
                monto = raw

            lineas.append((deduccion.code, monto))

            if monto is None or total is None:
                total = None
            else:
                total = total - monto

        result[order_id] = TotalGaussResultado(total_gauss=total, lineas=lineas)

    return result


def marcar_stale(db: Session, shipping_ids: Sequence[str]) -> int:
    """Marks every order whose `shipping_id` is in `shipping_ids` as
    `total_gauss_stale=True` -- design D3, the write-side invalidation hook.

    Must be called in the SAME transaction as the mutation that could
    change the order's Total Gauss (the caller commits). Returns the
    number of orders touched -- 0 is a valid, silent result (e.g. a Flex
    label just created for a shipment whose order has not ingested yet).
    """
    ids = [int(s) for s in shipping_ids if s is not None and str(s).lstrip("-").isdigit()]
    if not ids:
        return 0
    return (
        db.query(MlOrdersOps)
        .filter(MlOrdersOps.shipping_id.in_(ids))
        .update({MlOrdersOps.total_gauss_stale: True}, synchronize_session=False)
    )


def persistir_total_gauss(db: Session, order_ids: Sequence[int]) -> Dict[int, TotalGaussResultado]:
    """Recomputes and stores `total_gauss`/`total_gauss_at`/`_stale` plus
    every `ml_venta_deducciones` row for `order_ids` -- best-effort
    re-materialisation of the SORT/FILTER key (design D2). Never the source
    of a displayed number; callers that need a value to SHOW must call
    `calcular_total_gauss` directly (or read this function's return),
    never the stored column.
    """
    from app.services.ml_ventas_desglose.iva import descomponer_neto  # local import: avoids a cycle with iva.py

    order_ids = list(order_ids)
    if not order_ids:
        return {}

    descomposiciones = descomponer_neto(db, order_ids)
    neto_sin_iva_by_order = {oid: desc.neto_sin_iva for oid, desc in descomposiciones.items()}
    resultados = calcular_total_gauss(db, order_ids, neto_sin_iva_by_order)

    orders = db.query(MlOrdersOps).filter(MlOrdersOps.order_id.in_(order_ids)).all()
    orders_by_id = {o.order_id: o for o in orders}

    existing = db.query(MlVentaDeduccion).filter(MlVentaDeduccion.order_id.in_(order_ids)).all()
    existing_by_key = {(row.order_id, row.code): row for row in existing}

    orden_by_code = {d.code: d.orden for d in DEDUCCIONES}

    for order_id, resultado in resultados.items():
        order = orders_by_id.get(order_id)
        if order is not None:
            order.total_gauss = resultado.total_gauss
            order.total_gauss_at = datetime.now(timezone.utc)
            order.total_gauss_stale = False
        for code, monto in resultado.lineas:
            key = (order_id, code)
            row = existing_by_key.get(key)
            if row is None:
                row = MlVentaDeduccion(order_id=order_id, code=code, orden=orden_by_code[code], monto=monto)
                db.add(row)
                existing_by_key[key] = row
            else:
                row.orden = orden_by_code[code]
                row.monto = monto

    return resultados

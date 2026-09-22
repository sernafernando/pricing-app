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
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.varios_venta_pct import VariosVentaPct
from app.services.ml_ventas_desglose.breakdown_service import resolve_flex_cost_by_order_ids

_CENT = Decimal("0.01")


@runtime_checkable
class DeduccionResolver(Protocol):
    """One entry of the ordered chain (design D1). `base` tells the
    orchestrator what a PERCENTAGE resolver's returned value multiplies:
    `"neto"` is `neto_sin_iva` (the chain's starting point, never touched by
    earlier deductions), `"corriente"` is the running total AFTER every
    earlier deduction in `orden`, `"venta_sin_iva"` (ml-ventas-neto-iibb-varios
    R3, design D4) is `venta_sin_iva_by_order` -- the goods without IVA,
    independent of both `neto_sin_iva` and the running total. Non-percentage
    resolvers ignore `base`."""

    code: str
    concepto: str
    orden: int
    base: str  # "neto" | "corriente" | "venta_sin_iva"
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


@dataclass(frozen=True)
class CostoItemDetalle:
    """Per-item arithmetic behind `CostoMercaderiaDeduccion`'s aggregate
    sum -- product-owner request: "el costo del producto debería decir
    después de costo (precio USD + TC) de cada operación para saber cómo
    replicar ese valor".

    `conocido=False` means this item has NO frozen `MlOrderItemCosto` row
    at all (see that model's own docstring on `PR3 is write-only... nothing
    reads it yet` becoming false as of this feature) -- every other field
    stays `None` in that case, and the renderer MUST read this as "unknown",
    never as a `$0` cost.

    `moneda == "USD"` is the only case with real conversion arithmetic to
    show (`costo_origen x tipo_cambio (tipo_cambio_fecha) = costo_unitario_ars`).
    An ARS-costed item never had a rate applied -- `tipo_cambio` and
    `tipo_cambio_fecha` are `None` for it, and the renderer must not
    fabricate an empty conversion row for a conversion that never
    happened.

    `fuente`/`costo_fecha` are passed through UNCHANGED from
    `MlOrderItemCosto` (see its module docstring for what each `fuente`
    value means and why `costo_fecha` is `None` for a live-frozen row) --
    this module does not reinterpret or flatten them."""

    item_id: str
    variation_id: Optional[int]
    title: Optional[str]
    quantity: Optional[int]
    conocido: bool
    moneda: Optional[str] = None
    costo_origen: Optional[Decimal] = None
    tipo_cambio: Optional[Decimal] = None
    tipo_cambio_fecha: Optional[date] = None
    costo_unitario_ars: Optional[Decimal] = None
    fuente: Optional[str] = None
    costo_fecha: Optional[date] = None


def resolve_costo_mercaderia_detalle(db: Session, order_ids: Sequence[int]) -> Dict[int, List[CostoItemDetalle]]:
    """Bulk, per-item breakdown of what `CostoMercaderiaDeduccion` sums --
    one query for every member order's items, one for every frozen cost
    row, TOTAL, never one query per item (same discipline as
    `CostoMercaderiaDeduccion.resolve_bulk` and `_productos_por_item`
    in `costeo_service.py`).

    Every requested `order_id` gets a key, even one with no items (`[]`,
    never a missing key the caller has to guard). Within an order, every
    item of that order gets exactly one `CostoItemDetalle`, `conocido=False`
    when it has no frozen row -- unlike the aggregate deduction, a single
    unresolved item does NOT hide the others: an operator trying to
    replicate the cost of the ITEMS THAT DO HAVE ONE should still see them.
    """
    order_ids = list(order_ids)
    result: Dict[int, List[CostoItemDetalle]] = {order_id: [] for order_id in order_ids}
    if not order_ids:
        return result

    # Same stable order as `breakdown_service`'s item lines, and for the
    # same reason: the two lists sit in the SAME panel, so an operator
    # checking the cost detail against the product detail has to find them
    # in the same sequence. Left to the database, both come back in
    # whatever order the plan produces and the pairing is coincidence.
    items = (
        db.query(MlOrderItemOps)
        .filter(MlOrderItemOps.order_id.in_(order_ids))
        .order_by(MlOrderItemOps.order_id, MlOrderItemOps.id)
        .all()
    )
    costos = db.query(MlOrderItemCosto).filter(MlOrderItemCosto.order_id.in_(order_ids)).all()
    costo_by_key: Dict[Tuple[int, str, Optional[int]], MlOrderItemCosto] = {
        (c.order_id, c.item_id, c.variation_id): c for c in costos
    }

    for item in items:
        costo = costo_by_key.get((item.order_id, item.item_id, item.variation_id))
        if costo is None:
            detalle = CostoItemDetalle(
                item_id=item.item_id,
                variation_id=item.variation_id,
                title=item.title,
                quantity=item.quantity,
                conocido=False,
            )
        else:
            detalle = CostoItemDetalle(
                item_id=item.item_id,
                variation_id=item.variation_id,
                title=item.title,
                quantity=item.quantity,
                conocido=True,
                moneda=costo.moneda,
                # `costo_origen` and `costo_unitario_ars` are `nullable=False`
                # on `MlOrderItemCosto` (checked in the model, not assumed),
                # so `Decimal(str(...))` cannot be handed a `None` here and
                # there is no guard to write. A row that could not resolve
                # completely is never INSERTED in the first place -- see
                # `costeo_service._ResolvedCost`: "there is no
                # partially-resolved variant on purpose".
                costo_origen=Decimal(str(costo.costo_origen)),
                tipo_cambio=(Decimal(str(costo.tipo_cambio)) if costo.tipo_cambio is not None else None),
                tipo_cambio_fecha=costo.tipo_cambio_fecha,
                costo_unitario_ars=Decimal(str(costo.costo_unitario_ars)),
                fuente=costo.fuente,
                costo_fecha=costo.costo_fecha,
            )
        result.setdefault(item.order_id, []).append(detalle)

    return result


class EnvioFlexDeduccion:
    """The seller's OWN Flex shipping cost (design D1). Applies ONLY to
    `self_service` orders -- reuses `resolve_flex_cost_by_order_ids`
    (`breakdown_service.py`), never reimplements the resolution rule.
    A non-Flex order simply gets no key (not applicable); a Flex order
    whose cost cannot be resolved gets `None` (`flex_cost_unknown`,
    same discipline as `compute_breakdown`'s line).

    `concepto` is a STATIC fallback label only, used when the per-order
    label (company name) cannot be resolved. `calcular_total_gauss` fetches
    the real per-order label straight from `resolve_flex_cost_by_order_ids`
    (NOT stored on this instance -- module-level `DEDUCCIONES` singletons
    must stay stateless, or concurrent requests would race on them)."""

    code = "envio_flex"
    concepto = "Envío Flex (costo propio)"
    orden = 2
    base = "neto"
    es_porcentaje = False

    def resolve_bulk(self, db: Session, order_ids: Sequence[int]) -> Dict[int, Optional[Decimal]]:
        resuelto_con_concepto = resolve_flex_cost_by_order_ids(db, order_ids)
        resuelto = {order_id: monto for order_id, (monto, _concepto) in resuelto_con_concepto.items()}

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

    `base = "venta_sin_iva"` (ml-ventas-neto-iibb-varios R3, design D4):
    the percentage applies to the GOODS WITHOUT IVA -- Σ, at each item's
    own frozen rate (mixed-rate packs never use one rate on the aggregate),
    of the same per-item bases `iva.descomponer_neto`'s `CONCEPTO_VENTA_ITEM`
    components already show on the drawer. NOT `neto_sin_iva` (which also
    carries ML's fees/freight/withholdings, net of IVA) and NOT the running
    total after earlier deductions in the chain -- subtracted at the END of
    the chain (`orden = 3`, last), against a base that earlier deductions
    never touch.

    `pricing_calculator.calcular_comision_ml_total`/`varios_porcentaje` is a
    SEPARATE, forward-pricing estimate (obs #2064) -- it projects a price
    BEFORE a sale exists; this deduction reads the FROZEN, POST-SALE goods
    base of a sale that already happened. The two apply the same rate to
    different, independently-computed bases and are NOT required to match;
    this module does not touch that other function."""

    code = "varios"
    concepto = "Varios (ventas)"
    orden = 3
    base = "venta_sin_iva"
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

        # NO VERSION CONFIGURED IS ZERO PER CENT, NOT UNKNOWN. This is the
        # one deduction in the chain where absence is a real answer: a
        # percentage nobody has loaded is a percentage that does not apply,
        # and `Neto - costo - flete - 0%` is a number, not a mystery.
        #
        # It used to return `None`, which propagated through the chain and
        # made `total_gauss` NULL for EVERY sale until somebody configured a
        # percentage -- a screen that showed nothing while waiting for a
        # setting that has no screen yet. Maintainer's call, verbatim: "si
        # no hay varios se entiende que es 0 (punto)".
        #
        # The same goes for an order this query did not return, or one with
        # no `date_created`: those are reasons we cannot pick a VERSION, and
        # no version means zero, same as above.
        for order_id in order_ids:
            result[order_id] = Decimal("0")

        for order_id, date_created in orders:
            if date_created is None:
                continue
            fecha_venta = date_created.date() if hasattr(date_created, "date") else date_created
            vigente: Optional[VariosVentaPct] = None
            for version in versiones:
                if version.fecha_desde <= fecha_venta and (
                    version.fecha_hasta is None or version.fecha_hasta >= fecha_venta
                ):
                    vigente = version
            if vigente is not None:
                result[order_id] = Decimal(str(vigente.porcentaje))

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
    for the one that blocked the chain, so the UI can point at it.

    `markup` is the SALE'S REAL markup, not the theoretical one:
    `total_gauss / costo_mercaderia`, expressed as a percentage. The
    product owner picked this over `pricing_calculator.calcular_markup`'s
    `(limpio_sin_iva - costo) / costo` on purpose -- `total_gauss` IS that
    same numerator but with the Flex freight and the "% de varios" ALSO
    subtracted, so dividing it by cost reports what the sale actually
    earned instead of what it earned before those extra costs. `None`
    (never `0`, never infinite) whenever `total_gauss` is `None`, the
    goods cost is `None` (missing from the chain, or `costo_mercaderia`
    did not apply to this order), or the cost is exactly zero -- a
    division by zero here would be worse than an unknown value, and this
    module treats a fabricated zero as a lie everywhere else, so it must
    here too."""

    total_gauss: Optional[Decimal]
    # `(code, monto, concepto)`: `concepto` is `None` unless the deduction
    # has a per-order label to offer (today, only `envio_flex`, carrying the
    # logistics company name -- `EnvioFlexDeduccion.concepto`'s docstring).
    # A `None` concepto means "use the resolver's static `concepto`", never
    # "no label at all".
    lineas: List[Tuple[str, Optional[Decimal], Optional[str]]] = field(default_factory=list)
    markup: Optional[Decimal] = None
    # total-gauss-provisorio: `True` exactly when `total_gauss` above was
    # computed WITHOUT the Flex freight cost because it is not resolvable
    # YET (the shipping label has not been loaded at the warehouse -- it is
    # ingested AFTER the sale). A REAL computed number, distinct from a
    # fabricated/zeroed one: every other deduction in the chain still
    # resolved. `provisional_falta` names the missing concept for the UI
    # (e.g. "Envío Flex"); both are `None`/`False` in every other case,
    # INCLUDING when `total_gauss` is `None` for any other reason (e.g. an
    # unresolved cost of goods -- see `calcular_total_gauss`'s docstring for
    # why that boundary does NOT get this treatment).
    provisional: bool = False
    provisional_falta: Optional[str] = None


def calcular_total_gauss(
    db: Session,
    order_ids: Sequence[int],
    neto_sin_iva_by_order: Dict[int, Optional[Decimal]],
    *,
    venta_sin_iva_by_order: Dict[int, Optional[Decimal]],
) -> Dict[int, TotalGaussResultado]:
    """Applies `DEDUCCIONES` in order, per order_id, over the bulk-resolved
    result of EVERY registered deduction -- one `resolve_bulk` call per
    deduction TOTAL, never one per order (mirrors `descomponer_neto`'s own
    bulk shape).

    `total_gauss` is a materialised SORT/FILTER key only (design D2): this
    function is the ONE producer of the number, called both for live
    display (never served from the stored column) and by whatever
    persists the stored column for sorting.

    `venta_sin_iva_by_order` (ml-ventas-neto-iibb-varios R3, design D4) is
    REQUIRED and keyword-only, EXPLICIT at every caller -- a caller that
    silently forgets it must fail loudly (`TypeError`), never fall back to
    an empty map that quietly blocks every "% de varios" line with base
    `"venta_sin_iva"`. It carries `iva.DescomposicionNeto.base_venta_sin_iva`
    per order, which every caller already has in hand from `descomponer_neto`
    -- zero new queries here.
    """
    order_ids = list(order_ids)
    result: Dict[int, TotalGaussResultado] = {}
    if not order_ids:
        return result

    resolved_by_code: Dict[str, Dict[int, Optional[Decimal]]] = {
        deduccion.code: deduccion.resolve_bulk(db, order_ids) for deduccion in DEDUCCIONES
    }

    # Per-order Flex label (carries the logistics company name), resolved
    # in bulk directly -- NOT read off `EnvioFlexDeduccion` (module-level
    # singletons in `DEDUCCIONES` stay stateless, see its docstring). One
    # extra bulk call, still O(1) queries for the whole page, never one per
    # order.
    flex_concepto_by_order: Dict[int, Optional[str]] = {
        order_id: concepto for order_id, (_monto, concepto) in resolve_flex_cost_by_order_ids(db, order_ids).items()
    }

    for order_id in order_ids:
        neto_sin_iva = neto_sin_iva_by_order.get(order_id)
        total: Optional[Decimal] = neto_sin_iva
        lineas: List[Tuple[str, Optional[Decimal]]] = []
        # Tracked separately from `lineas` (which the chain can grow without
        # touching this function -- module docstring) so the markup formula
        # below reads directly off the goods-cost deduction by its stable
        # `code`, never by position.
        costo_mercaderia: Optional[Decimal] = None
        blocking_codes: List[str] = []

        # `total_provisional` mirrors `total` exactly, EXCEPT it treats an
        # unresolved Flex freight cost as a $0 contribution instead of a
        # block -- see the DELIBERATE EXCEPTION note below. It is discarded
        # unless `envio_flex` turns out to be the ONLY blocking link.
        total_provisional: Optional[Decimal] = neto_sin_iva

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
                # D5: the RATE is checked FIRST. Zero percent of anything is
                # zero -- known without even looking at the base -- so an
                # unconfigured "% de varios" (raw == 0) never newly blocks
                # an order whose base happens to be unresolved too. Only
                # when the rate is non-zero does an unresolved base become
                # a real, named block (never a silent 0 base).
                if raw == 0:
                    monto = Decimal("0")
                else:
                    objetivo_by_base = {
                        "neto": neto_sin_iva,
                        "corriente": total,
                        "venta_sin_iva": venta_sin_iva_by_order.get(order_id),
                    }
                    objetivo = objetivo_by_base[deduccion.base]
                    monto = (
                        None
                        if objetivo is None
                        else (objetivo * raw / Decimal("100")).quantize(_CENT, rounding=ROUND_HALF_UP)
                    )
            else:
                monto = raw

            linea_concepto = flex_concepto_by_order.get(order_id) if deduccion.code == EnvioFlexDeduccion.code else None
            lineas.append((deduccion.code, monto, linea_concepto))
            if deduccion.code == CostoMercaderiaDeduccion.code:
                costo_mercaderia = monto

            if monto is None or total is None:
                total = None
                if monto is None:
                    blocking_codes.append(deduccion.code)
            else:
                total = total - monto

            # DELIBERATE EXCEPTION, Flex-only: total-gauss-provisorio. A
            # `self_service` sale has no freight cost until the shipping
            # label is loaded at the warehouse, which happens AFTER the
            # sale is ingested -- so `envio_flex` resolving `None` here is
            # routine, not a data gap. Every OTHER unresolved link (most of
            # all, `costo_mercaderia`: no margin without a cost) must still
            # block the whole chain -- this is NOT "skip any unknown link",
            # it is this one link, named, on purpose. See
            # `TotalGaussResultado.provisional`'s docstring.
            if deduccion.code == EnvioFlexDeduccion.code and monto is None:
                pass  # total_provisional does NOT subtract this line
            elif total_provisional is not None:
                total_provisional = total_provisional - monto if monto is not None else None

        provisional = False
        provisional_falta: Optional[str] = None
        if total is None and blocking_codes == [EnvioFlexDeduccion.code] and total_provisional is not None:
            total = total_provisional
            provisional = True
            # The GENERIC concept name, never the company name: the whole
            # point is that the company's cost (and therefore which company
            # actually carried it) has not resolved yet.
            provisional_falta = EnvioFlexDeduccion.concepto

        # markup = total_gauss / costo_mercaderia, as a percentage -- see
        # `TotalGaussResultado.markup`'s docstring for why THIS numerator.
        # `None` propagates the same way every other value in this module
        # does: an unresolved cost, an unresolved chain, or a zero cost
        # (division by zero) all report "we do not know", never a 0% or an
        # infinite markup. Computed off the PROVISIONAL total too -- it is a
        # real number, just flagged.
        markup: Optional[Decimal] = None
        if total is not None and costo_mercaderia is not None and costo_mercaderia != 0:
            markup = (total / costo_mercaderia * Decimal("100")).quantize(_CENT, rounding=ROUND_HALF_UP)

        result[order_id] = TotalGaussResultado(
            total_gauss=total,
            lineas=lineas,
            markup=markup,
            provisional=provisional,
            provisional_falta=provisional_falta,
        )

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


MAX_TOTAL_GAUSS_REFRESH_PER_PASS = 500


def refrescar_total_gauss_pendientes(db: Session, limit: int = MAX_TOTAL_GAUSS_REFRESH_PER_PASS) -> int:
    """Materialises `total_gauss` for the orders that need it, and returns
    how many were refreshed.

    THIS FUNCTION IS WHY THE COLUMN IS NOT A LIE. `total_gauss` exists only
    to be sorted and filtered on -- the paging `ORDER BY` runs before the
    net can be computed, so the value has to be on the row already. Without
    a producer, every row stays NULL, `nullslast()` puts them all on the
    same side, and "sort by Total Gauss" silently degrades into sort by id:
    the operator asks for an ordering and gets another one, with nothing
    saying so. The five `marcar_stale` hooks had the mirror problem --
    they invalidated towards a recomputation that did not exist.

    Picks stale rows FIRST (something changed under them) and then rows
    never materialised at all, bounded per pass so a large backlog cannot
    turn the sweep into this job. Displayed values are still ALWAYS
    recomputed (design D2); this only feeds sorting.
    """
    pendientes = (
        db.query(MlOrdersOps.order_id)
        .filter(or_(MlOrdersOps.total_gauss_stale.is_(True), MlOrdersOps.total_gauss_at.is_(None)))
        .order_by(MlOrdersOps.total_gauss_stale.desc().nullslast(), MlOrdersOps.order_id.desc())
        .limit(limit)
        .all()
    )
    order_ids = [row[0] for row in pendientes]
    if not order_ids:
        return 0
    persistir_total_gauss(db, order_ids)
    return len(order_ids)


def persistir_total_gauss(db: Session, order_ids: Sequence[int]) -> Dict[int, TotalGaussResultado]:
    """Recomputes and stores `total_gauss`/`total_gauss_at`/`_stale` plus
    every `ml_venta_deducciones` row for `order_ids` -- best-effort
    re-materialisation of the SORT/FILTER key (design D2). Never the source
    of a displayed number; callers that need a value to SHOW must call
    `calcular_total_gauss` directly (or read this function's return),
    never the stored column.

    THIN DELEGATING ALIAS (ventas-ml-rediseno PR1.T9, design D1/D7): the
    write side now lives in `order_metrics.store.recompute_order_metrics`,
    which ALSO upserts the new `ml_order_metrics` table -- one writer, no
    second formula, no duplicated upsert logic. This function only
    translates `OrderMetrics` back into the legacy `TotalGaussResultado`
    shape every existing caller (and its tests) already expects.

    NOT byte-identical to `calcular_total_gauss` anymore: `.markup` here is
    `order_metrics.compute.normalize_markup_pct`'s NORMALIZED value, not the
    chain's raw one -- an order whose real markup cannot fit
    `ml_order_metrics.markup_pct` (`NUMERIC(9, 2)`, e.g. a near-zero frozen
    unit cost on a normal-priced order) reports `markup=None` here even
    though `calcular_total_gauss`, called directly, still returns the real
    -- if absurd -- raw value. A caller that needs the number to SHOW must
    call `calcular_total_gauss` directly, per this function's own module
    docstring; this alias's `.markup` reflects what got STORED.
    """
    # Local import: avoids a cycle (order_metrics.compute imports THIS
    # module for `calcular_total_gauss`/`CostoMercaderiaDeduccion`).
    from app.services.order_metrics.store import recompute_order_metrics
    from app.services.order_metrics.types import GaussStatus

    order_ids = list(order_ids)
    if not order_ids:
        return {}

    metrics_by_order = recompute_order_metrics(db, order_ids)
    return {
        order_id: TotalGaussResultado(
            total_gauss=metrics.total_gauss,
            lineas=metrics.lineas,
            markup=metrics.markup_pct,
            provisional=metrics.gauss_status == GaussStatus.PROVISIONAL,
            provisional_falta=metrics.provisional_falta,
        )
        for order_id, metrics in metrics_by_order.items()
    }

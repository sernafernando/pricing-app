"""IVA decomposition of a sale's `neto` (ml-ventas-modo-logistico, PR4,
design D8-D12).

`neto` is NOT redefined here -- it stays exactly whatever
`compute_neto_by_order_ids` / `compute_breakdown` already compute
(design D9, pinned by `TestTheTwoPathsToTheNetAgree`). This module produces
a DECOMPOSITION: every component of that net enters at its own IVA-free
value, never a single division of the whole net by one rate.

## Why `neto / 1.21` is wrong

The net mixes items taxed at different rates (measured: 2.368 products at
10,5% vs 1.948 at 21%) with ML's own charges, always taxed at 21%. Per the
verified identity (#1952) `net_received_amount == paid_amount -
sum(seller charges)`, its parts are individually known:

    neto         = venta_bruta - comisiones_brutas - retenciones
    neto_sin_iva = venta_neta  - comisiones_netas  - retenciones

Each component contributes a SIGNED `bruto` to `neto`: positive for a sale
item (it adds to what the seller invoiced), negative for a fee/freight/
withholding (it was already subtracted by ML before handing over the net).
`base`/`iva` are the EXACT split of that same signed amount, so
`base + iva == bruto` always holds and nothing needs a second, independent
rounding.

## The fee enters the chain at its NET value (D10)

A $1.000 fee deducts $1.000 from `neto` and $826,45 from `neto_sin_iva` --
NOT $1.000. Because the deduction SHRINKS, `neto_sin_iva` sits HIGHER than
naively stripping the whole net at a uniform rate would put it. This is
counter-intuitive and is pinned by a test on purpose so nobody "fixes" it
back into the wrong shape.

## Withholdings and residual charges pass through unstripped (D8/D11)

A `type == 'tax'` charge (a withholding) carries no IVA to strip: it enters
BOTH nets identically. `is_seller_charge` and the `charge.type == 'tax'`
branch are REUSED from `breakdown_service` -- see that module's own
docstring: "the ONE place this exclusion is applied... must never be
duplicated". A seller charge that is neither a known fee/freight nor a
`type == 'tax'` withholding is NEVER silently dropped (task 4.12): it is
reported as `CONCEPTO_IVA_NO_DETERMINADO`, passed through exactly like a
withholding, because we do not know its rate and must not invent one.

## Reconciliation is EXACT (D12)

    sum(componente.bruto for componente in componentes) == neto

No tolerance is allowed: a tolerance would launder a real inconsistency
into rounding noise. When it fails, `reconcilia=False`, `diferencia` is
populated, and `neto_sin_iva` is `None` -- the same all-or-nothing
discipline an unknown cost gets (D7): if the net's composition cannot be
accounted for exactly, it cannot be honestly de-IVA'd either. This DOES
fire in production: order 2000018322969636 is the known 1-of-488 mismatch.

Nothing here performs fiscal crediting or builds a libro IVA (D13) -- the
per-component, per-rate figures are a free byproduct of the decomposition,
not a feature built for a consumer that does not exist yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps
from app.services.ml_ventas_desglose.breakdown_service import (
    CHARGE_LABELS,
    _RELEVANT_PAYMENT_STATUSES,
    is_seller_charge,
    net_amount,
    payment_effective_net,
    shipping_label,
)

# ML's own IVA rate on its fees and freight -- authoritative per the
# maintainer, not a measurement. One edit here if it ever moves.
IVA_ML_PCT = Decimal("21")
IVA_ML_DIVISOR = Decimal("1") + IVA_ML_PCT / Decimal("100")

CONCEPTO_VENTA_ITEM = "Venta"

# A seller charge that is neither a known fee/freight nor a `type='tax'`
# withholding. Reported, never dropped (task 4.12) -- mirrors `_tax_label`'s
# discipline of never discarding an unrecognised name.
CONCEPTO_IVA_NO_DETERMINADO = "IVA no determinado"

# Positive terms that are INSIDE `net_received_amount` but are not the
# goods. Leaving them out was not a missing feature, it was a broken
# premise: `neto` derives from what the buyer PAID, and the buyer pays the
# shipping the seller charges plus, on a coupon, only part of the price --
# ML funds the rest and settles it to us. Decomposing only the items made
# every such order fail to reconcile, and `neto_sin_iva` went silently
# None. Both carry ML's 21%, same as every other ML-side figure.
CONCEPTO_ENVIO_COMPRADOR = "Envío cobrado al comprador"
CONCEPTO_CUPON_ML = "Cupón financiado por ML"

# Facts that make a per-rate decomposition IMPOSSIBLE, as opposed to merely
# unbalanced. Reported by name for the same reason `breakdown_service` names
# its own incomplete reasons: "it does not reconcile" sends the reader
# hunting for an arithmetic bug that is not there.
RAZON_VENTA_CON_DEVOLUCION = "venta_con_devolucion"
RAZON_ITEM_SIN_CANTIDAD = "item_sin_cantidad"
RAZON_ITEM_SIN_COSTO_CONGELADO = "item_sin_costo_congelado"

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class ComponenteIVA:
    concepto: str
    alicuota: Optional[Decimal]  # None = carries no IVA (withholding / residual)
    bruto: Decimal
    base: Decimal
    iva: Decimal  # base + iva == bruto, EXACTLY


@dataclass(frozen=True)
class DescomposicionNeto:
    """The net, split per IVA rate.

    `neto_sin_iva` is `None` whenever the split cannot be trusted -- either
    the components do not add up to `neto` exactly, or `razones` names
    something that makes a per-rate split undeterminable from what we
    store. A number here is always one that reconciles to the cent.
    """

    componentes: List[ComponenteIVA]
    neto_sin_iva: Optional[Decimal]
    reconcilia: bool
    diferencia: Decimal
    razones: List[str] = field(default_factory=list)


def _split(bruto: Decimal, divisor: Decimal) -> Tuple[Decimal, Decimal]:
    """Splits a SIGNED gross amount into `(base, iva)` at `divisor`.

    `iva` is the exact remainder of `bruto - base`, never computed
    independently -- so `base + iva == bruto` holds by construction, with
    no orphan cent, regardless of `bruto`'s sign."""
    sign = Decimal("1") if bruto >= 0 else Decimal("-1")
    base_magnitude = (abs(bruto) / divisor).quantize(_CENT, rounding=ROUND_HALF_UP)
    base = sign * base_magnitude
    iva = bruto - base
    return base, iva


def _passthrough(bruto: Decimal) -> Tuple[Decimal, Decimal]:
    """A withholding or a residual, unrecognised seller charge: no rate is
    known (or none applies), so it enters both nets identically (D8/D11)."""
    return bruto, Decimal("0")


def descomponer_neto(db: Session, order_ids: Sequence[int]) -> Dict[int, DescomposicionNeto]:
    """One `DescomposicionNeto` per `order_id`, each resolved
    INDEPENDENTLY -- mirrors `compute_neto_by_order_ids`'s bulk-by-order_ids
    shape (D1), never one query per order regardless of how many are
    requested together."""
    order_ids = list(order_ids)
    result: Dict[int, DescomposicionNeto] = {}
    if not order_ids:
        return result

    payments = db.query(MlPaymentOps).filter(MlPaymentOps.order_id.in_(order_ids)).all()
    payments_by_order: Dict[int, List[MlPaymentOps]] = {}
    for payment in payments:
        payments_by_order.setdefault(payment.order_id, []).append(payment)

    relevant_payments = [p for p in payments if p.status in _RELEVANT_PAYMENT_STATUSES]
    payment_ids = [p.payment_id for p in relevant_payments]

    charges: List[MlPaymentCharge] = []
    if payment_ids:
        charges = db.query(MlPaymentCharge).filter(MlPaymentCharge.payment_id.in_(payment_ids)).all()
    charges_by_payment: Dict[int, List[MlPaymentCharge]] = {}
    for charge in charges:
        charges_by_payment.setdefault(charge.payment_id, []).append(charge)

    costos = db.query(MlOrderItemCosto).filter(MlOrderItemCosto.order_id.in_(order_ids)).all()
    costos_by_order: Dict[int, List[MlOrderItemCosto]] = {}
    for costo in costos:
        costos_by_order.setdefault(costo.order_id, []).append(costo)

    items = db.query(MlOrderItemOps).filter(MlOrderItemOps.order_id.in_(order_ids)).all()
    # Assigning, not summing: `uq_ml_order_item_ops_order_item_variation`
    # makes this triple unique (with `postgresql_nulls_not_distinct`), so a
    # later row cannot silently replace an earlier one. Summing would not be
    # the safer choice, it would be the wrong one -- it would double a
    # quantity the constraint forbids from existing twice.
    quantity_by_key: Dict[Tuple[int, str, Optional[int]], Optional[int]] = {
        (it.order_id, it.item_id, it.variation_id): it.quantity for it in items
    }
    items_by_order: Dict[int, int] = {}
    for it in items:
        items_by_order[it.order_id] = items_by_order.get(it.order_id, 0) + 1

    for order_id in order_ids:
        order_relevant = [p for p in payments_by_order.get(order_id, []) if p.status in _RELEVANT_PAYMENT_STATUSES]
        if not order_relevant:
            result[order_id] = DescomposicionNeto(
                componentes=[], neto_sin_iva=None, reconcilia=False, diferencia=Decimal("0")
            )
            continue

        neto = Decimal("0")
        seller_charges: List[MlPaymentCharge] = []
        for payment in order_relevant:
            payment_charges = charges_by_payment.get(payment.payment_id, [])
            order_seller_charges = [c for c in payment_charges if is_seller_charge(c.type, c.name)]
            neto += payment_effective_net(payment, order_seller_charges)
            seller_charges.extend(order_seller_charges)

        componentes: List[ComponenteIVA] = []
        razones: List[str] = []

        # Sale, PER ITEM -- its OWN frozen alicuota, never a single 21
        # applied to the whole order (D8, task 4.8). Uses the FROZEN
        # `precio_unitario`/`iva_pct` (design D4/D6); quantity is read live
        # from `MlOrderItemOps` -- it is not a fiscal fact that gets frozen.
        # An order whose items were never frozen (PR3 runs only on new
        # ingestions) contributes NOTHING on the goods side, and without a
        # name that reads as an arithmetic bug in this module rather than
        # as the absent snapshot it is.
        if items_by_order.get(order_id) and not costos_by_order.get(order_id):
            razones.append(RAZON_ITEM_SIN_COSTO_CONGELADO)

        for costo in costos_by_order.get(order_id, []):
            key = (costo.order_id, costo.item_id, costo.variation_id)
            quantity = quantity_by_key.get(key)
            if quantity is None:
                # NAMED, never a bare `continue`: without the quantity this
                # item contributes nothing and the order stops reconciling,
                # which reads exactly like an arithmetic bug elsewhere.
                if RAZON_ITEM_SIN_CANTIDAD not in razones:
                    razones.append(RAZON_ITEM_SIN_CANTIDAD)
                continue
            bruto = (costo.precio_unitario * quantity).quantize(_CENT, rounding=ROUND_HALF_UP)
            divisor = Decimal("1") + Decimal(costo.iva_pct) / Decimal("100")
            base, iva = _split(bruto, divisor)
            componentes.append(
                ComponenteIVA(
                    concepto=CONCEPTO_VENTA_ITEM,
                    alicuota=Decimal(costo.iva_pct),
                    bruto=bruto,
                    base=base,
                    iva=iva,
                )
            )

        # Shipping the BUYER paid and the coupon share ML funded are both
        # inside `net_received_amount`, so they have to appear on the
        # positive side too or the sum can never reach it.
        # `order_relevant`, NOT every payment: `neto` was built from the
        # relevant ones only, so adding a rejected payment's shipping here
        # would inflate the positive side against a net that never saw it.
        for payment in order_relevant:
            for valor, concepto in (
                (payment.shipping_amount, CONCEPTO_ENVIO_COMPRADOR),
                (payment.coupon_amount, CONCEPTO_CUPON_ML),
            ):
                if valor is None:
                    continue
                bruto = Decimal(str(valor))
                if bruto == 0:
                    continue
                base, iva = _split(bruto, IVA_ML_DIVISOR)
                componentes.append(
                    ComponenteIVA(concepto=concepto, alicuota=IVA_ML_PCT, bruto=bruto, base=base, iva=iva)
                )
            if payment.transaction_amount_refunded:
                # A refund scales `neto` down, but nothing tells us WHICH
                # items came back -- so the per-rate split of the goods is
                # not determinable from what we store. Saying so beats a
                # silent mismatch that looks like a bug in this module.
                if RAZON_VENTA_CON_DEVOLUCION not in razones:
                    razones.append(RAZON_VENTA_CON_DEVOLUCION)

        for charge in seller_charges:
            name = charge.name or ""
            if charge.type == "tax":
                # Withholding -- reused branch, see module docstring; never
                # a parallel name list (D11, task 4.7).
                bruto = -net_amount(charge)
                base, iva = _passthrough(bruto)
                componentes.append(
                    ComponenteIVA(
                        concepto=name or CONCEPTO_IVA_NO_DETERMINADO, alicuota=None, bruto=bruto, base=base, iva=iva
                    )
                )
            elif name in CHARGE_LABELS or name.startswith("shp_"):
                # ML fee or freight -- ALWAYS 21% (D8/D10), always at its
                # NET value: this IS the deduction, not a gross line
                # reported alongside one.
                bruto = -net_amount(charge)
                base, iva = _split(bruto, IVA_ML_DIVISOR)
                concepto = CHARGE_LABELS.get(name) or shipping_label(name)
                componentes.append(
                    ComponenteIVA(concepto=concepto, alicuota=IVA_ML_PCT, bruto=bruto, base=base, iva=iva)
                )
            else:
                # Residual seller charge: not a known fee/freight, not a
                # withholding. Reported, never dropped (task 4.12) -- we do
                # not know its rate, so it passes through like a
                # withholding rather than being guessed at 21%.
                bruto = -net_amount(charge)
                base, iva = _passthrough(bruto)
                componentes.append(
                    ComponenteIVA(concepto=CONCEPTO_IVA_NO_DETERMINADO, alicuota=None, bruto=bruto, base=base, iva=iva)
                )

        suma_bruto = sum((c.bruto for c in componentes), Decimal("0"))
        diferencia = neto - suma_bruto
        reconcilia = diferencia == Decimal("0")

        # Both gates, not just the arithmetic one: a decomposition can add
        # up and still be untrustworthy (a refund whose items we cannot
        # identify), and one that does not add up is never trustworthy.
        confiable = reconcilia and not razones
        neto_sin_iva = sum((c.base for c in componentes), Decimal("0")) if confiable else None

        result[order_id] = DescomposicionNeto(
            componentes=componentes,
            neto_sin_iva=neto_sin_iva,
            reconcilia=reconcilia,
            diferencia=diferencia,
            razones=razones,
        )

    return result

"""Cost breakdown for one sale (order or pack) -- corte 6 of
ml-ventas-desglose-costos.

Read-only. Sourced ENTIRELY from data already ingested by corte 5
(`ml_payments_ops` / `ml_payment_charges`) and corte 1-3
(`ml_billing_charges` / `ml_billing_charge_orders`) -- nothing here
computes a number ML did not itself report. Every rule below is measured
against 514 real payments (see obs #1960, #1965, #1966).

## The seller-vs-buyer/coupon predicate

`_is_seller_charge` is the ONE place this exclusion is applied. It must
never be duplicated: a charge is NOT the seller's when
    type == "coupon" | type == "bonus" | name == "financing_fee" | "payer" in name

`financing_fee` (buyer pays for installments) and `financing_add_on_fee`
(WE pay ML for offering installments) are opposite pockets despite the
similar name -- only the former is excluded.

## Net of a sale

A sale can have several `approved` payments splitting both the total and
the shipping amount between them (order 2000018322969636: two approved
payments, 7371.11 + 12528.89 = 19900, `shipping_amount` on only one of
the two) -- the net is the SUM over every relevant payment, never a single
row.

For a returned sale, the reported `net_received_amount` on the payment
stays POSITIVE even though the whole amount was refunded (order
2000018325540962: net 27614 with everything returned). The identity
verified 20/20 against real data:

    transaction_amount_refunded - sum(refunded of SELLER charges) == net_received_amount

means the effective, POST-RETURN net of a payment is:

    net_received_amount - transaction_amount_refunded + sum(refunded of seller charges)

which is `net_received_amount` unchanged when nothing was refunded, and
collapses to exactly ZERO for a payment refunded in full -- one formula,
no special-casing by status. `rejected`/`cancelled` payments are excluded
entirely: they carry `net_received_amount == 0` WITH charges loaded, and
folding those charges into a breakdown would report costs for a sale that
never completed.

## "Envios" -- the easiest line to get wrong

Sourced ONLY from what ML actually charges: `shp_*` payment charges, plus
billing-side shipping charges (`ml_billing_charges` with
`detail_sub_type` in CXD/CFF/CSSTEC, joined through the
`ml_billing_charge_orders` bridge). NEVER `MlShipmentOps.sender_cost`:
verified live, 121 of 125 orders where that field is > 0 are
`self_service` -- ML never charges anything for those, the seller pays
its own carrier directly, and `sender_cost` would inflate every one of
those sales with a cost ML never billed.

A pack's shipping charge is shared: `ml_billing_charge_orders` bridges one
`detail_id` to every order in the pack, so summing per order would count
it once per order instead of once per parcel. Dedupe by `detail_id`
before summing.

## "Zero shipping charge" is the NORMAL case, not a missing-data signal

There is deliberately NO incompleteness reason for a missing shipping
charge. A first version raised one whenever an order had a shipment, zero shipping
charges, AND at least one billing row already linked (reasoning: the sweep
ran, so a missing shipping charge must mean the shipping charge itself is
missing). That is wrong, and it was caught before shipping because it was
measured, not because it looked wrong: of the 125 orders with
`MlShipmentOps.sender_cost > 0` (obs #1965), **121 have NO shipping charge
in billing at all** -- they are `self_service`, the seller pays its own
carrier, and ML never bills anything for them. Every `self_service` order
also has ordinary billing rows (a CVFV "Cargo por vender" charge exists
for every sale), so that version's condition fired on the self_service
case, not the actually-missing one. Projected across the ~480-order
listing (the measured 246/480 contingency), **more than half the rows
would render "incompleto"** -- an alarm that always sounds means as
little as one that never does (the corte-3 completeness check's mirror
problem, in the opposite direction), and both leave the operator with no
usable signal.

There is no reliable way, from data alone, to tell "this shipment's charge
should exist and doesn't" apart from "this shipment is self_service /
free and correctly has no charge." Inventing one is worse than not having
one: an operator who trusts a badge that lies stops trusting the badge
that tells the truth. If a real signal for this ever surfaces (e.g. an ML
field that distinguishes free/self_service from a genuinely uncollected
charge), wire it here. Until then this module emits no reason at all for
it, and the constant that once held one is gone: a reason that can never
fire is a promise the code does not keep, and the next reader tries to
make it fire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.ml_billing import MlBillingCharge, MlBillingChargeOrder
from app.models.ml_orders_ops import MlOrdersOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps

# Payment statuses whose charges/net are meaningful for a breakdown.
#
# `in_mediation` is money COLLECTED and held while a claim is settled, not
# money that never arrived: it reports a real `net_received_amount` and no
# refund. Measured 2026-09-08 across the 117 payments behind our open and
# closed claims: 46 approved, 36 in_mediation, 31 refunded, 4 rejected.
# `in_mediation` is 31% of them -- and while it was missing here, every one
# of those sales showed a net of ZERO, which is what a fully refunded sale
# reports. Order 2000018092595428 collected 199.707,50 and read as nothing.
#
# `rejected`/`cancelled` stay out -- see module docstring.
_RELEVANT_PAYMENT_STATUSES = frozenset({"approved", "refunded", "in_mediation"})

# Charge classification -- see module docstring. The ONE predicate, never
# duplicated elsewhere.
_NON_SELLER_TYPES = frozenset({"coupon", "bonus"})
_NON_SELLER_NAMES = frozenset({"financing_fee"})

# Billing detail sub-types that represent a shipping charge collected
# through the billing sweep (as opposed to a payment's own `shp_*` charges).
_SHIPPING_BILLING_SUBTYPES = frozenset({"CXD", "CFF", "CSSTEC"})

_CHARGE_LABELS: Dict[str, str] = {
    "meli_percentage_fee": "Cargo por vender",
    "flat_fee": "Costo fijo",
    "financing_add_on_fee": "Costo por ofrecer cuotas",
}

CONCEPTO_IMPUESTOS = "Impuestos"
CONCEPTO_ENVIOS = "Envios"

# ML encodes WHICH tax and WHERE inside the charge name, so a single
# "Impuestos" line throws that away. Measured across production: 35
# distinct `type='tax'` names in four shapes.
#
#   tax_withholding_sirtac-<prov>            SIRTAC withholding
#   tax_withholding_sirtac_sobretasa-<prov>  its provincial surcharge
#   tax_withholding-<prov>                   a provincial withholding
#                                            charged outside SIRTAC
#   tax_withholding_<who>-debitos_creditos   the debit/credit tax, where
#                                            `collector` is US and
#                                            `payer` is the buyer (the
#                                            payer one never reaches here
#                                            -- `_is_seller_charge` drops
#                                            anything with "payer" in the
#                                            name)
#
# The bare `tax_withholding-<prov>` shape is deliberately labelled just
# "Retención": ML does not say which provincial tax it is, and naming it
# IIBB would be us guessing on a money line.
_TAX_PREFIX = "tax_withholding"

_TAX_KINDS: Dict[str, str] = {
    "": "Retención",
    "sirtac": "Retención SIRTAC",
    "sirtac_sobretasa": "Sobretasa SIRTAC",
    "collector": "Impuesto a los débitos y créditos",
}

# Spelled out rather than title-cased from the slug: `entre_rios` is
# "Entre Ríos", `caba` is not "Caba", and an operator reading a money
# breakdown should not be shown mangled province names.
_TAX_PLACES: Dict[str, str] = {
    "buenos_aires": "Buenos Aires",
    "caba": "CABA",
    "catamarca": "Catamarca",
    "chaco": "Chaco",
    "chubut": "Chubut",
    "cordoba": "Córdoba",
    "corrientes": "Corrientes",
    "entre_rios": "Entre Ríos",
    "formosa": "Formosa",
    "jujuy": "Jujuy",
    "la_pampa": "La Pampa",
    "la_rioja": "La Rioja",
    "mendoza": "Mendoza",
    "misiones": "Misiones",
    "neuquen": "Neuquén",
    "rio_negro": "Río Negro",
    "salta": "Salta",
    "san_juan": "San Juan",
    "san_luis": "San Luis",
    "santa_cruz": "Santa Cruz",
    "santa_fe": "Santa Fe",
    "santiago_del_estero": "Santiago del Estero",
    "tierra_del_fuego": "Tierra del Fuego",
    "tucuman": "Tucumán",
}


def _tax_label(charge_name: Optional[str]) -> str:
    """A readable line for one `type='tax'` charge.

    `charge_name` is Optional because `MlPaymentCharge.name` is nullable
    and a charge with `type` set and no name has been seen in production
    (it is what made an earlier version discard whole payments).

    Falls back to the plain `Impuestos` bucket for anything it does not
    recognise, ON PURPOSE: a name ML adds tomorrow must still show up as
    money the seller paid. Losing an amount because its label was
    unfamiliar would be a breakdown that quietly stops adding up.
    """
    name = charge_name or ""
    if not name.startswith(_TAX_PREFIX):
        return CONCEPTO_IMPUESTOS

    rest = name[len(_TAX_PREFIX) :]
    kind_slug, _, place_slug = rest.partition("-")
    kind_slug = kind_slug.lstrip("_")
    if not place_slug:
        return CONCEPTO_IMPUESTOS

    kind = _TAX_KINDS.get(kind_slug)
    if kind is None:
        return CONCEPTO_IMPUESTOS

    # The debit/credit tax is national -- its `place` is the tax itself,
    # not a province, so appending it would read "... (Debitos Creditos)".
    if place_slug == "debitos_creditos":
        return kind

    place = _TAX_PLACES.get(place_slug)
    if place is None:
        return CONCEPTO_IMPUESTOS
    return f"{kind} ({place})"


REASON_PAYMENTS_NOT_SYNCED = "payments_not_synced"
# Rows EXIST and are synced, but none of them counts: all rejected, or a
# status ML added that we do not model yet. Distinct from
# `payments_not_synced` on purpose -- telling the operator the sweep has
# not run yet, when it has, is the badge that lies about which the module
# docstring warns. One says "wait"; this one says "look at the payment".
REASON_PAYMENTS_NOT_COUNTABLE = "payments_not_countable"
REASON_BILLING_NOT_SWEPT = "billing_not_swept"


def _is_seller_charge(charge_type: Optional[str], charge_name: Optional[str]) -> bool:
    """The single reusable seller-vs-buyer/coupon predicate. See module
    docstring -- this must never be reimplemented anywhere else."""
    charge_type = charge_type or ""
    charge_name = charge_name or ""
    if charge_type in _NON_SELLER_TYPES:
        return False
    if charge_name in _NON_SELLER_NAMES:
        return False
    if "payer" in charge_name:
        return False
    return True


def _net_amount(charge: MlPaymentCharge) -> Decimal:
    """A charge's amount net of whatever ML already refunded on it."""
    amount = Decimal(str(charge.amount)) if charge.amount is not None else Decimal("0")
    refunded = Decimal(str(charge.refunded)) if charge.refunded is not None else Decimal("0")
    return amount - refunded


@dataclass(frozen=True)
class BreakdownLine:
    concepto: str
    monto: Decimal
    origen: str = "api"


@dataclass(frozen=True)
class OperationBreakdown:
    lines: List[BreakdownLine]
    neto: Optional[Decimal]
    incompleto: bool
    incomplete_reasons: List[str] = field(default_factory=list)


def _payment_effective_net(payment: MlPaymentOps, seller_charges: Sequence[MlPaymentCharge]) -> Decimal:
    """`net_received_amount`, corrected for whatever was refunded -- see
    module docstring. Zero for a payment refunded in full, unchanged for
    one never refunded."""
    net = Decimal(str(payment.net_received_amount)) if payment.net_received_amount is not None else Decimal("0")
    refunded_total = (
        Decimal(str(payment.transaction_amount_refunded))
        if payment.transaction_amount_refunded is not None
        else Decimal("0")
    )
    if refunded_total == 0:
        return net
    seller_refunded = sum(
        (Decimal(str(c.refunded)) if c.refunded is not None else Decimal("0")) for c in seller_charges
    )
    return net - refunded_total + seller_refunded


def compute_neto_by_order_ids(db: Session, order_ids: Sequence[int]) -> Dict[int, Optional[Decimal]]:
    """Bulk `neto` for every order in `order_ids`, in exactly two queries
    regardless of how many order_ids are passed in.

    This exists for the sales LISTING (`GET /ml-ventas-ops/sales`), which
    pages up to 200 rows: calling `compute_breakdown` once per row would be
    hundreds of queries per request. This function applies the exact same
    rule instead -- `_RELEVANT_PAYMENT_STATUSES`, `_is_seller_charge`,
    `_payment_effective_net` are the SAME predicates `compute_breakdown`
    uses, imported/reused here, never reimplemented -- but resolves it with
    two bulk queries scoped to every `order_id` on the page at once,
    mirroring `listar_ventas`'s own `members_base` pattern (page the keys,
    then fetch every member in bulk).

    `None` for an order_id with no payment row we can count -- either
    none synced yet, or none in a status we recognise. Never conflated
    with a returned sale's real, measured ZERO: zero is an answer, this is
    the absence of one. `compute_breakdown` applies the SAME rule, keyed
    off its own `relevant_payments`; the two must agree, and
    `TestTheTwoPathsToTheNetAgree` holds them to it.
    """
    order_ids = list(order_ids)
    result: Dict[int, Optional[Decimal]] = dict.fromkeys(order_ids)
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

    for order_id, order_payments in payments_by_order.items():
        order_relevant = [p for p in order_payments if p.status in _RELEVANT_PAYMENT_STATUSES]
        if not order_relevant:
            # Rows exist but none of them count. That is NOT zero: zero
            # means the sale left nothing, which is what a refunded sale
            # reports. Whatever status we do not recognise yet lands here,
            # and the honest answer is "we do not know" -- the same answer
            # an unsynced sale gets. This is the guard that would have
            # caught `in_mediation` before it read as a returned sale.
            result[order_id] = None
            continue
        neto = Decimal("0")
        for payment in order_relevant:
            payment_charges = charges_by_payment.get(payment.payment_id, [])
            seller_charges = [c for c in payment_charges if _is_seller_charge(c.type, c.name)]
            neto += _payment_effective_net(payment, seller_charges)
        result[order_id] = neto

    return result


def compute_breakdown(db: Session, order_ids: Sequence[int]) -> OperationBreakdown:
    """The cost breakdown for a sale -- one order, or every order sharing a
    pack (caller resolves which order_ids belong together, mirroring
    `listar_ventas`'s `_group_key_expr` grouping)."""
    order_ids = list(order_ids)
    if not order_ids:
        return OperationBreakdown(lines=[], neto=None, incompleto=True, incomplete_reasons=[REASON_PAYMENTS_NOT_SYNCED])

    incomplete_reasons: List[str] = []

    payments = db.query(MlPaymentOps).filter(MlPaymentOps.order_id.in_(order_ids)).all()
    relevant_payments = [p for p in payments if p.status in _RELEVANT_PAYMENT_STATUSES]
    if not relevant_payments:
        # Keyed off `relevant_payments`, not `payments`: rows can exist and
        # still leave us with no net. Off `payments` the panel returned a
        # null net with `incompleto=False` and no reason at all -- a silent
        # blank, in the one place that HAS a channel for saying "we do not
        # know". The listing can only stay quiet; this must not.
        #
        # WHICH reason matters: no rows means the sweep owes us data;
        # rows that do not count means the sweep did its job and the
        # payments themselves are the story. Saying "not synced yet" for
        # the second is the badge that lies.
        incomplete_reasons.append(REASON_PAYMENTS_NOT_SYNCED if not payments else REASON_PAYMENTS_NOT_COUNTABLE)
    payment_ids = [p.payment_id for p in relevant_payments]

    charges: List[MlPaymentCharge] = []
    if payment_ids:
        charges = db.query(MlPaymentCharge).filter(MlPaymentCharge.payment_id.in_(payment_ids)).all()

    charges_by_payment: Dict[int, List[MlPaymentCharge]] = {}
    for charge in charges:
        charges_by_payment.setdefault(charge.payment_id, []).append(charge)

    neto = Decimal("0")
    for payment in relevant_payments:
        payment_charges = charges_by_payment.get(payment.payment_id, [])
        seller_charges = [c for c in payment_charges if _is_seller_charge(c.type, c.name)]
        neto += _payment_effective_net(payment, seller_charges)

    seller_charges_all = [c for c in charges if _is_seller_charge(c.type, c.name)]

    line_amounts: Dict[str, Decimal] = {}

    # `flat_fee` is charged once PER ORDER in a pack (measured: pack
    # 2000014907031737, 1330 on each of its two payments) -- summing every
    # payment's flat_fee charge is correct, unlike shipping which is
    # shared once per pack.
    for charge in seller_charges_all:
        label = _CHARGE_LABELS.get(charge.name)
        if label is not None:
            line_amounts[label] = line_amounts.get(label, Decimal("0")) + _net_amount(charge)
        elif charge.type == "tax":
            tax_label = _tax_label(charge.name)
            line_amounts[tax_label] = line_amounts.get(tax_label, Decimal("0")) + _net_amount(charge)

    # Shipping: `shp_*` payment charges (never shared -- summed per order).
    shipping_total = Decimal("0")
    for charge in seller_charges_all:
        if charge.name.startswith("shp_"):
            shipping_total += _net_amount(charge)

    # Shipping: billing-side charges, joined through the bridge table and
    # DEDUPED by detail_id -- a pack's shipping charge is reported once by
    # ML but bridged to every order in the pack.
    billing_links = db.query(MlBillingChargeOrder).filter(MlBillingChargeOrder.order_id.in_(order_ids)).all()
    linked_detail_ids = {link.detail_id for link in billing_links}
    billing_charges: List[MlBillingCharge] = []
    if linked_detail_ids:
        billing_charges = db.query(MlBillingCharge).filter(MlBillingCharge.detail_id.in_(linked_detail_ids)).all()
    shipping_billing_charges = [c for c in billing_charges if c.detail_sub_type in _SHIPPING_BILLING_SUBTYPES]
    for charge in shipping_billing_charges:
        if charge.amount is not None:
            shipping_total += Decimal(str(charge.amount))

    if shipping_total != 0:
        line_amounts[CONCEPTO_ENVIOS] = line_amounts.get(CONCEPTO_ENVIOS, Decimal("0")) + shipping_total

    # `billing_not_swept` is a real, verifiable signal, but ONLY meaningful
    # for a sale that actually has a shipment: NO billing row at all is
    # linked to this order/pack, meaning the billing sweep never even
    # reached it. A zero shipping charge WITH billing rows present is the
    # ordinary self_service/free-shipping case -- see module docstring --
    # and is NEVER treated as incomplete.
    has_shipment_order = any(
        order.shipping_id is not None
        for order in db.query(MlOrdersOps).filter(MlOrdersOps.order_id.in_(order_ids)).all()
    )
    if has_shipment_order and shipping_total == 0 and not linked_detail_ids:
        incomplete_reasons.append(REASON_BILLING_NOT_SWEPT)

    lines = [BreakdownLine(concepto=concepto, monto=monto, origen="api") for concepto, monto in line_amounts.items()]

    return OperationBreakdown(
        lines=lines,
        # `relevant_payments`, NOT `payments`: an order whose payment rows
        # exist but none of them count has an UNKNOWN net, not a zero.
        # Keyed off `payments` this returned Decimal("0") while the listing
        # returned None for the same sale -- the two-numbers-for-one-sale
        # failure this module's own tests call the worst available here,
        # introduced by the guard that was meant to prevent it.
        neto=neto if relevant_payments else None,
        incompleto=bool(incomplete_reasons),
        incomplete_reasons=incomplete_reasons,
    )

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
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from sqlalchemy.orm import Session, joinedload

from app.models.codigo_postal_cordon import CodigoPostalCordon
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.logistica_costo_cordon import LogisticaCostoCordon
from app.models.ml_billing import MlBillingCharge, MlBillingChargeOrder
from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps
from app.services.logistica_costo_service import costo_efectivo, get_lluvia_config, normalizar_cordon
from app.services.ml_orders_ingestion.mode_resolution import (
    MODO_DESCONOCIDO,
    MODO_RETIRO,
    MODO_SELF_SERVICE,
    resolve_modo_logistico,
)

# `MODO_SELF_SERVICE` is IMPORTED, not redeclared: a second copy of the
# string here is precisely the drift this module argues against everywhere
# else. `MODO_MIXED` has no home in the cascade -- nothing resolves TO it,
# it only ever comes out of collapsing several orders -- so it lives here.
MODO_MIXED = "mixed"

# Modes for which a MISSING shipping charge is not a missing-data signal.
#
# `retiro` is the absolute case: no ML shipping is involved at all, so
# there is nothing that could ever be billed.
#
# `self_service` is the statistical one, and the difference matters enough
# to write down. ML DOES bill Flex sellers a technical charge sometimes --
# `shp_self_service_tech` appears on 553 payments in production, against
# 25.770 self_service shipments. So roughly 98% of Flex sales carry no ML
# shipping charge because the seller pays their own carrier directly, and
# the remaining 2% carry one legitimately.
#
# We cannot tell a genuinely missing `shp_self_service_tech` from the
# overwhelmingly normal absence of one, and warning on the 98% to catch the
# 2% is precisely the alarm-that-always-rings this module refuses to build.
# So Flex does not warn -- and that is a deliberate blind spot, not a claim
# that the charge never exists.
_MODES_NEVER_WARN_BILLING = frozenset({MODO_SELF_SERVICE, MODO_RETIRO})

_BILLING_AGE_THRESHOLD = timedelta(hours=48)

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
CONCEPTO_ENVIO_PROPIO = "Envío Flex (costo propio)"

# ml-ventas-modo-logistico PR2 -- per-mode split of the single "Envios"
# line. Mirrors `_tax_label`'s discipline exactly: a KNOWN `shp_*` type
# gets its own readable line; anything else falls back to the generic
# CONCEPTO_ENVIOS bucket instead of being dropped. Measured in production
# (obs #1965/#1966): only 5.075 of 12.528 payments carry any `shp_*`
# charge at all -- `shp_cross_docking` (3.818), `shp_fulfillment` (704),
# `shp_self_service_tech` (553).
_SHIPPING_CHARGE_LABELS: Dict[str, str] = {
    "shp_cross_docking": "Envíos (Colecta)",
    "shp_fulfillment": "Envíos (Full)",
    "shp_self_service_tech": "Envíos (Flex — cargo ML)",
}

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


def _shipping_label(charge_name: Optional[str]) -> str:
    """A readable per-mode line for one `shp_*` payment charge.

    Same discipline as `_tax_label`: falls back to the generic
    `CONCEPTO_ENVIOS` bucket for any `shp_*` type not in the known set, ON
    PURPOSE -- an unrecognised type must still show up as money the
    seller's shipping cost, never silently vanish from the sum."""
    return _SHIPPING_CHARGE_LABELS.get(charge_name or "", CONCEPTO_ENVIOS)


def _ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite drops tzinfo on reload of a `DateTime(timezone=True)` column
    -- the repo-wide pattern (see e.g. `pedidos_preparacion.py`,
    `sweep_service.py`) is to treat a naive reload as UTC rather than
    compare naive to aware and raise."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _resolve_modes(db: Session, orders: Sequence[MlOrdersOps]) -> tuple[str, Dict[int, str], Dict[int, MlShipmentOps]]:
    """Group-level logistic mode, PLUS the per-order modes it collapsed and
    the shipment rows it already loaded.

    All three come back together on purpose. The collapsed mode alone is
    lossy: a pack that resolves to `"mixed"` still has individual
    self_service orders whose freight WE pay, and a caller holding only
    `"mixed"` would drop that cost with no trace -- the silent hole this
    module's docstring exists to prevent. Returning the shipments map too
    keeps the Flex resolver from re-running the identical query.

    Always recomputed live from the shipment/tag join -- mirrors the D2
    pattern (`total_gauss`/`modo_logistico` snapshot columns are sort/filter
    keys only, never the displayed value) established in PR1. Mirrors the
    router's own `_collapse()`: every member order shares one mode -> that
    mode; disagreement -> `\"mixed\"`.
    """
    if not orders:
        return MODO_DESCONOCIDO, {}, {}

    shipping_ids = [o.shipping_id for o in orders if o.shipping_id is not None]
    shipments_by_id: Dict[int, MlShipmentOps] = {}
    if shipping_ids:
        shipments = db.query(MlShipmentOps).filter(MlShipmentOps.shipment_id.in_(shipping_ids)).all()
        shipments_by_id = {s.shipment_id: s for s in shipments}

    modes_by_order: Dict[int, str] = {}
    for order in orders:
        shipment = shipments_by_id.get(order.shipping_id) if order.shipping_id is not None else None
        modes_by_order[order.order_id] = resolve_modo_logistico(
            shipment_logistic_type=shipment.logistic_type if shipment else None,
            has_shipment=shipment is not None,
            tagged_no_shipping=bool(order.has_no_shipping_tag),
        )
    modes = set(modes_by_order.values())

    if len(modes) == 1:
        return next(iter(modes)), modes_by_order, shipments_by_id
    return MODO_MIXED, modes_by_order, shipments_by_id


def _postal_code_for_cordon(
    label: EtiquetaEnvio,
    shipments_by_id: Dict[int, MlShipmentOps],
) -> Optional[str]:
    """The postal code that decides the CORDON, which is not always the
    buyer's.

    When a `Transporte` is assigned, the parcel goes to the transport's
    depot and the carrier is paid for THAT trip, so the transport's CP
    decides the tariff. The Etiquetas screens already resolve it this way
    (`coalesce(Transporte.cp, eff_zip)`); reading the buyer's CP here would
    land on a different cordon, a different tariff and a different cost for
    the same `shipping_id`.

    Falls back to the label's manual override, then to the shipment's own
    receiver address.
    """
    transporte = label.transporte
    if transporte is not None and transporte.cp:
        return str(transporte.cp)
    if label.manual_zip_code:
        return str(label.manual_zip_code)
    shipment = shipments_by_id.get(int(label.shipping_id)) if label.shipping_id else None
    if shipment is not None and shipment.receiver_address:
        zip_code = shipment.receiver_address.get("zip_code")
        if zip_code:
            return str(zip_code)
    return None


def _resolve_flex_cost_line(
    db: Session,
    orders: Sequence[MlOrdersOps],
    modes_by_order: Dict[int, str],
    shipments_by_id: Dict[int, MlShipmentOps],
) -> tuple[Optional["BreakdownLine"], bool]:
    """The seller's OWN Flex shipping cost -- see spec "Flex Real Cost
    Line". Resolution is `costo_override` (wins when set) else
    `logistica_costo_cordon` by `(logistica_id, cordon, vigente_desde <=
    fecha_envio)` taking `MAX(id)`. All-or-nothing across every self_service
    shipment in the group: if ANY of them fails to resolve, NO line is
    emitted at all and the caller adds `REASON_FLEX_COST_UNKNOWN` -- never a
    `coalesce(..., 0)` that would render an unresolved cost as `$0`.

    Selection is PER ORDER, never off the group's collapsed mode. A pack
    that collapses to `"mixed"` can still hold a self_service order whose
    freight we pay, and keying off the collapsed value would drop that cost
    silently -- no line AND no `flex_cost_unknown`, which is worse than
    either alone.

    Returns `(None, False)` when no member order is self_service -- Flex
    cost simply does not apply.
    """
    flex_orders = [o for o in orders if modes_by_order.get(o.order_id) == MODO_SELF_SERVICE]
    if not flex_orders:
        return None, False

    shipping_ids = sorted({o.shipping_id for o in flex_orders if o.shipping_id is not None})
    if not shipping_ids:
        return None, True

    labels = (
        db.query(EtiquetaEnvio)
        .options(joinedload(EtiquetaEnvio.logistica), joinedload(EtiquetaEnvio.transporte))
        .filter(EtiquetaEnvio.shipping_id.in_([str(s) for s in shipping_ids]))
        .all()
    )
    labels_by_shipping_id = {label.shipping_id: label for label in labels}

    lluvia_tipo, lluvia_valor = get_lluvia_config(db)

    # Both lookups below are resolved in ONE query each, before the loop.
    # Querying inside it is the pattern AGENTS.md names outright, and a pack
    # is not a bound worth trusting.
    postal_code_by_shipping_id = {
        label.shipping_id: _postal_code_for_cordon(label, shipments_by_id) for label in labels
    }
    postal_codes = {pc for pc in postal_code_by_shipping_id.values() if pc}
    cordones_by_cp = {}
    if postal_codes:
        cordones_by_cp = {
            row.codigo_postal: row
            for row in db.query(CodigoPostalCordon)
            .filter(CodigoPostalCordon.codigo_postal.in_(sorted(postal_codes)))
            .all()
        }

    logistica_ids = {label.logistica_id for label in labels if label.logistica_id is not None}
    tarifas: List[LogisticaCostoCordon] = []
    if logistica_ids:
        tarifas = (
            db.query(LogisticaCostoCordon)
            .filter(LogisticaCostoCordon.logistica_id.in_(sorted(logistica_ids)))
            .order_by(LogisticaCostoCordon.id.asc())
            .all()
        )

    total = Decimal("0")
    logistica_names: List[str] = []

    for shipping_id in shipping_ids:
        label = labels_by_shipping_id.get(str(shipping_id))
        if label is None:
            return None, True

        if label.costo_override is not None:
            total += costo_efectivo(costo_override=label.costo_override)
            if label.logistica is not None and label.logistica.nombre not in logistica_names:
                logistica_names.append(label.logistica.nombre)
            continue

        if label.logistica_id is None:
            return None, True

        postal_code = postal_code_by_shipping_id.get(str(shipping_id))
        if not postal_code:
            return None, True

        cordon_row = cordones_by_cp.get(str(postal_code))
        if cordon_row is None or not cordon_row.cordon:
            return None, True

        if label.fecha_envio is None:
            return None, True

        cordon_buscado = normalizar_cordon(cordon_row.cordon)
        # KNOWN, DELIBERATE DIVERGENCE from the Etiquetas screens, written
        # down rather than left to be discovered: they select the tariff in
        # force TODAY (`vigente_desde <= hoy`), because they answer "what
        # would this cost now". This is a historical breakdown of a sale
        # that already shipped, so it selects the tariff in force ON THE
        # SHIPPING DATE. For an old label whose tariff was raised since,
        # the two screens will legitimately show different numbers, and the
        # one here is the one that was actually paid. If Etiquetas is ever
        # aligned to this rule, delete this note along with the difference.
        # MAX(id) among the rows in force on the shipping date -- `tarifas`
        # is ordered ascending, so the last match is that row.
        tarifa = None
        for row in tarifas:
            if (
                row.logistica_id == label.logistica_id
                and row.cordon == cordon_buscado
                and row.vigente_desde <= label.fecha_envio
            ):
                tarifa = row
        # NORMALISED, never raw: `cp_cordones` spells it "Cordón 1" and
        # `logistica_costo_cordon` spells it "Cordon 1". Comparing them raw
        # matches nothing, so every Flex sale without an override would
        # resolve to "cost unknown" wearing the face of honest missing data.
        if tarifa is None:
            return None, True

        # The tariff's plain `costo` is NOT the cost -- turbo and the rain
        # surcharge move it, and the Etiquetas screens already apply both.
        # Same function on both sides, so the two surfaces cannot disagree
        # about the same shipment.
        costo = costo_efectivo(
            es_turbo=bool(label.es_turbo),
            es_lluvia=bool(label.es_lluvia),
            costo=tarifa.costo,
            costo_turbo=tarifa.costo_turbo,
            lluvia_tipo=lluvia_tipo,
            lluvia_valor=lluvia_valor,
        )
        if costo is None:
            return None, True
        total += costo
        if label.logistica is not None and label.logistica.nombre not in logistica_names:
            logistica_names.append(label.logistica.nombre)

    concepto = CONCEPTO_ENVIO_PROPIO
    if logistica_names:
        concepto = f"{CONCEPTO_ENVIO_PROPIO} ({', '.join(sorted(logistica_names))})"

    return BreakdownLine(concepto=concepto, monto=total, origen="propio"), False


REASON_PAYMENTS_NOT_SYNCED = "payments_not_synced"
# Rows EXIST and are synced, but none of them counts: all rejected, or a
# status ML added that we do not model yet. Distinct from
# `payments_not_synced` on purpose -- telling the operator the sweep has
# not run yet, when it has, is the badge that lies about which the module
# docstring warns. One says "wait"; this one says "look at the payment".
REASON_PAYMENTS_NOT_COUNTABLE = "payments_not_countable"
REASON_BILLING_NOT_SWEPT = "billing_not_swept"
# The seller's own Flex cost could not be resolved -- see
# `_resolve_flex_cost_line`. Never paired with a `$0` line.
REASON_FLEX_COST_UNKNOWN = "flex_cost_unknown"
# Genuinely informational: the order is too young to expect a billing
# charge yet. Distinct from `REASON_BILLING_NOT_SWEPT` on purpose -- it
# must NOT flip `incompleto` to True (see `_INFORMATIONAL_REASONS` below).
REASON_BILLING_TOO_RECENT = "billing_too_recent"

# Reasons that describe a real gap in the data (payments/billing genuinely
# missing) flip `incompleto`. `REASON_BILLING_TOO_RECENT` reports a fact
# about elapsed time, not a gap -- the operator did not lose data, the
# sweep just has not had time to run yet. `REASON_FLEX_COST_UNKNOWN` is the
# same kind of fact, not a data-integrity alarm about the SALE itself: the
# pinned self_service regression (`test_self_service_shipment_with_no_...
# _but_ordinary_billing_is_complete`, obs #1965) already established that a
# self_service order with no shipping charge and ordinary billing is a
# COMPLETE sale -- an unresolved Flex freight cost is a separate, additive
# signal about that ONE line, not a reason to re-flag the whole sale as
# incomplete.
_INFORMATIONAL_REASONS = frozenset({REASON_BILLING_TOO_RECENT, REASON_FLEX_COST_UNKNOWN})


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
    """The sale's cost breakdown.

    `neto` DOES NOT include the `origen="propio"` lines, and that is by
    design, not an oversight. `neto` is ML's own `net_received_amount`:
    every `origen="api"` line is a charge ML already subtracted before
    handing us the money, so those lines EXPLAIN the net rather than move
    it. A `propio` line -- today the real Flex freight -- is a cost WE pay
    to a carrier ML never sees, so it cannot be inside a number ML
    computed.

    The consequence is deliberate and has to be carried honestly by
    whoever renders this: summing every line does NOT reproduce `neto`.
    The `propio` lines are what the upcoming Total Gauss subtracts FROM
    `neto` (spec: `Neto - envio flex - % = Total Gauss`), which is exactly
    why they are reported separately instead of being folded in here.
    """

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

    # Shipping: `shp_*` payment charges (never shared -- summed per order),
    # split by KNOWN mode into its own line (ml-ventas-modo-logistico PR2)
    # with an unrecognised type bucketed under CONCEPTO_ENVIOS, never
    # dropped. `shipping_total` still tracks the FULL sum for the billing
    # warning below -- summing every line it feeds is exactly the amount
    # the single legacy line would have reported.
    shipping_total = Decimal("0")
    for charge in seller_charges_all:
        if charge.name.startswith("shp_"):
            amount = _net_amount(charge)
            shipping_total += amount
            label = _shipping_label(charge.name)
            line_amounts[label] = line_amounts.get(label, Decimal("0")) + amount

    # Shipping: billing-side charges, joined through the bridge table and
    # DEDUPED by detail_id -- a pack's shipping charge is reported once by
    # ML but bridged to every order in the pack. These carry no `shp_*`
    # name to split by mode, so they stay in the generic bucket.
    billing_links = db.query(MlBillingChargeOrder).filter(MlBillingChargeOrder.order_id.in_(order_ids)).all()
    linked_detail_ids = {link.detail_id for link in billing_links}
    billing_charges: List[MlBillingCharge] = []
    if linked_detail_ids:
        billing_charges = db.query(MlBillingCharge).filter(MlBillingCharge.detail_id.in_(linked_detail_ids)).all()
    shipping_billing_charges = [c for c in billing_charges if c.detail_sub_type in _SHIPPING_BILLING_SUBTYPES]
    for charge in shipping_billing_charges:
        if charge.amount is not None:
            amount = Decimal(str(charge.amount))
            shipping_total += amount
            line_amounts[CONCEPTO_ENVIOS] = line_amounts.get(CONCEPTO_ENVIOS, Decimal("0")) + amount

    orders = db.query(MlOrdersOps).filter(MlOrdersOps.order_id.in_(order_ids)).all()
    has_shipment_order = any(order.shipping_id is not None for order in orders)
    _, modes_by_order, shipments_by_id = _resolve_modes(db, orders)

    # The seller's OWN Flex freight cost -- see spec "Flex Real Cost Line".
    # Applies to whichever member orders are self_service, chosen from the
    # PER-ORDER modes and never from the collapsed one; all-or-nothing per
    # `_resolve_flex_cost_line`, never a `$0` line for an unresolved input.
    flex_line, flex_unknown = _resolve_flex_cost_line(db, orders, modes_by_order, shipments_by_id)
    lines_extra: List[BreakdownLine] = []
    if flex_line is not None:
        lines_extra.append(flex_line)
    if flex_unknown:
        incomplete_reasons.append(REASON_FLEX_COST_UNKNOWN)

    # Three-case billing incompleteness (ml-ventas-modo-logistico PR2,
    # replacing the single condition below the module docstring's own
    # warning): (a) a mode that structurally never bills a shipping charge
    # (`self_service`, `retiro`) never warns; (b) an order under 48h old
    # gets the INFORMATIONAL `billing_too_recent` reason, which does not
    # flip `incompleto`; (c) 48h or older with no charge and no billing
    # link is a genuine `billing_not_swept`.
    # Decided off the PER-ORDER modes for the same reason the Flex line is:
    # a pack collapsing to `"mixed"` is not in `_MODES_NEVER_WARN_BILLING`,
    # so an all-Flex pack with one order whose shipment has not landed yet
    # would start warning about billing that structurally never arrives.
    # A sale warns only if some member order is in a mode that really can
    # be billed for shipping.
    billable_modes = {m for m in modes_by_order.values() if m not in _MODES_NEVER_WARN_BILLING}
    if has_shipment_order and billable_modes and shipping_total == 0 and not linked_detail_ids:
        created_dates = [_ensure_utc(order.date_created) for order in orders if order.date_created is not None]
        oldest_created = min(created_dates) if created_dates else None
        if oldest_created is not None and (datetime.now(timezone.utc) - oldest_created) < _BILLING_AGE_THRESHOLD:
            incomplete_reasons.append(REASON_BILLING_TOO_RECENT)
        else:
            incomplete_reasons.append(REASON_BILLING_NOT_SWEPT)

    # A charge fully refunded nets to zero. Splitting `Envios` per mode made
    # those surface as their own `Envios (Colecta): 0,00` row, which the
    # single legacy line never showed. A zero row states nothing and costs
    # the reader a second look, so it is dropped -- the sum is unchanged
    # either way, which is why this is safe to do here and nowhere near the
    # arithmetic.
    lines = [
        BreakdownLine(concepto=concepto, monto=monto, origen="api")
        for concepto, monto in line_amounts.items()
        if monto != 0
    ] + lines_extra

    return OperationBreakdown(
        lines=lines,
        # `relevant_payments`, NOT `payments`: an order whose payment rows
        # exist but none of them count has an UNKNOWN net, not a zero.
        # Keyed off `payments` this returned Decimal("0") while the listing
        # returned None for the same sale -- the two-numbers-for-one-sale
        # failure this module's own tests call the worst available here,
        # introduced by the guard that was meant to prevent it.
        neto=neto if relevant_payments else None,
        incompleto=any(reason not in _INFORMATIONAL_REASONS for reason in incomplete_reasons),
        incomplete_reasons=incomplete_reasons,
    )

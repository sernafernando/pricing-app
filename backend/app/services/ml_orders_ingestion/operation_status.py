"""Derivation of `operation_status` and `goods_status` for the ML sales
list (`GET /api/ml-ventas-ops/sales`).

There is no single ML field for "paid / cancelled / in dispute /
delivered": this module makes that derivation explicit, in exactly one
place, ported from `gbs-pricing`'s `app/application/operation_status.py`
(same precedence table, same production incidents behind it), amended per
this repo's own instructions (2026-09-01): an open claim of ANY stage now
counts as `in_dispute`, not only `payment_status == "in_mediation"`.

Precedence, most authoritative first (a later row never overrides an
earlier one):

| order_status  | payment_status | claim_status  | covered_by_marketplace | -> operation_status  |
|---------------|----------------|---------------|-------------------------|-----------------------|
| "cancelled"   | (any)          | (any)         | True                    | cancelled_ml_covered |
| "cancelled"   | (any)          | (any)         | False/None              | cancelled            |
| (not cancel)  | "in_mediation" | (any)         | (any)                   | in_dispute           |
| (not cancel)  | (any)          | open (*)      | (any)                   | in_dispute           |
| (not cancel)  | (any)          | no open claim | (any), shipping=delivered | delivered          |
| "paid"/"confirmed" | (other)   | no open claim | (any)                   | paid                 |
| anything else not covered above                                        | unknown              |

(*) "open" means present and not in `SETTLED_CLAIM_STATUSES` — a claim
whose status this system has never seen counts as open, which fails safe
towards showing the operator a claim rather than hiding one.

`covered_by_marketplace` is checked first, ahead of the plain `cancelled`
row, but only ever fires alongside it -- see this repo's
`app/models/ml_orders_ops.py::MlOrdersOps.covered_by_marketplace` for why
this column is currently written as `NULL` on every row (undetermined,
not guessed) and therefore never actually reaches `cancelled_ml_covered`
today. The precedence row is kept so a future slice that fills in the
column needs no change here.

`unknown` is a deliberate value: unrecognised/absent input fails safe
rather than being guessed into one of the other five (a row nobody has
classified stays visibly `unknown` instead of silently mislabeled).

---

`goods_status` is a SEPARATE axis from `operation_status` (deliberately,
per this slice's instructions): money and goods are independent facts
about the same sale. A cancellation with the goods still in the warehouse,
one where they went out and came back, and one where the buyer has them
are three different operational situations behind the identical
`operation_status == "cancelled"`. Vocabulary matches this repo's existing
Flex vocabulary (`app/api/endpoints/etiquetas_*.py`). The line the axis
draws is whether the parcel is still ours: `GOODS_STATUS_BY_SHIPPING_STATUS`
below is the one place that says which side each shipping status falls on,
and this docstring deliberately does not repeat it. Anything else
(including no shipment at all) is `unknown` -- distinct from "never
shipped", which this system cannot assert either.
"""

from __future__ import annotations

from typing import Optional

# Exported (not underscore-prefixed): the list endpoint's SQL query
# builder (`routers/ml_ventas_ops.py`) reuses these EXACT sets to build an
# equivalent `CASE` expression for query-time filtering/pagination, so the
# classification stays keyed off one shared source of truth instead of two
# copies that could drift.
PAID_ORDER_STATUSES = {"paid", "confirmed"}

# A claim in any of these is over: it changes nothing about the sale.
# Anything else -- including a status this system has never seen -- counts
# as live/open, which fails safe towards showing the operator a claim
# rather than hiding one. `rma_claims_ml.status` only ever takes "opened"
# or "closed" today (see that model's own column comment).
SETTLED_CLAIM_STATUSES = {"closed"}

OPERATION_STATUSES = (
    "cancelled_ml_covered",
    "cancelled",
    "in_dispute",
    "delivered",
    "paid",
    "unknown",
)

GOODS_STATUSES = (
    "unknown",
    "in_warehouse",
    "in_transit",
    "delivered",
    "returned_undelivered",
)

# The line this axis draws is the one the business acts on: is the parcel
# still OURS, or has it left? `ready_to_ship` is ours -- its substatuses
# (`ready_to_print`, `ready_to_pack`, `packed`, `in_warehouse`) are our own
# internal pipeline, all of them inside the warehouse.
#
# `handling` is NOT ours: the first carrier has already collected it
# (operator, 2026-09-03). It was mapped to `in_warehouse` here, which said
# the parcel was still on our floor after it had left. It does not appear
# in this account's traffic today -- a 20-shipment sample of live orders
# returned only `ready_to_ship`, `shipped` and `cancelled` -- so this was a
# latent defect rather than an active one, and it is corrected before it
# can surface.
GOODS_STATUS_BY_SHIPPING_STATUS = {
    "ready_to_ship": "in_warehouse",
    "handling": "in_transit",
    "shipped": "in_transit",
    "delivered": "delivered",
    "not_delivered": "returned_undelivered",
}


def operation_status_of(
    *,
    order_status: Optional[str],
    payment_status: Optional[str],
    claim_status: Optional[str] = None,
    covered_by_marketplace: Optional[bool] = None,
    shipping_status: Optional[str] = None,
) -> str:
    """Six values, five inputs. See module docstring for the precedence
    table. Never raises; unrecognised/absent input falls through to
    `"unknown"`."""
    if order_status == "cancelled":
        return "cancelled_ml_covered" if covered_by_marketplace else "cancelled"
    if payment_status == "in_mediation":
        return "in_dispute"
    if claim_status is not None and claim_status not in SETTLED_CLAIM_STATUSES:
        return "in_dispute"
    if shipping_status == "delivered":
        return "delivered"
    if order_status in PAID_ORDER_STATUSES:
        return "paid"
    return "unknown"


def goods_status_of(shipping_status: Optional[str]) -> str:
    """The goods axis, independent of `operation_status_of` above. `None`/
    unrecognised input is `"unknown"` -- ML did not say, which is a
    different fact from "never shipped"."""
    if shipping_status is None:
        return "unknown"
    return GOODS_STATUS_BY_SHIPPING_STATUS.get(shipping_status, "unknown")

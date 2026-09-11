"""Logistic mode resolution for ML sales (design D1 of
ml-ventas-modo-logistico).

The resolved mode answers "how does this parcel actually move", and the
real SHIPMENT always outranks the `no_shipping` TAG. ML tags an order
`no_shipping` whenever the seller registers an out-of-band delivery at
order time, but the order can still end up with a real shipment later
(store pickup rerouted to a carrier, cross-docking after all). Order
`2000016977234624` is the verified case: it carries BOTH the `no_shipping`
tag AND a `delivered` `cross_docking` shipment. A tag-only badge would
label that delivered sale "Retiro".

Cascade, in this exact order:
    1. `MlShipmentOps.logistic_type`, when a shipment exists and carries one
    2. `"retiro"`, when there is no shipment but the order carries the
       `no_shipping` tag
    3. `"desconocido"`, otherwise

Observed `logistic_type` values (from `ml_shipments_ops`, verified in
production): `self_service` (Flex), `cross_docking` (Colecta),
`fulfillment` (Full), `default`. An unobserved value is NEVER coerced or
dropped -- it passes through verbatim, because a future ML logistic type
must not silently vanish into "desconocido" the day it starts appearing.
"""

from __future__ import annotations

from typing import Any, List, Optional

MODO_SELF_SERVICE = "self_service"
MODO_RETIRO = "retiro"
MODO_DESCONOCIDO = "desconocido"

NO_SHIPPING_TAG = "no_shipping"


def has_no_shipping_tag(tags: Optional[List[Any]]) -> bool:
    """Whether an order payload's `tags` list carries `no_shipping`.

    Pure list membership -- no JSONB containment query, so the same
    function backs both the ingestion-time derived column (Postgres) and
    any in-Python check (SQLite tests), with nothing that diverges between
    the two engines.
    """
    if not tags:
        return False
    return NO_SHIPPING_TAG in tags


def resolve_modo_logistico(
    *,
    shipment_logistic_type: Optional[str],
    has_shipment: bool,
    tagged_no_shipping: bool,
) -> str:
    """Resolves one order's logistic mode per the cascade above.

    `has_shipment` is a separate flag from `shipment_logistic_type` being
    non-None: a shipment row can exist with a NULL `logistic_type` (ML
    hasn't populated it yet), and that still outranks the tag -- there IS a
    real shipment, we just don't know its type yet, so it resolves to
    `desconocido` rather than falling through to `retiro`.
    """
    if has_shipment:
        return shipment_logistic_type if shipment_logistic_type else MODO_DESCONOCIDO
    if tagged_no_shipping:
        return MODO_RETIRO
    return MODO_DESCONOCIDO

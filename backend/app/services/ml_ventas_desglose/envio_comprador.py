"""The shipping the BUYER pays (ventas-ml-varios-base-envio).

It is invoiced to the buyer, so it enters the "% de varios" base ("lo que
facturamos, después pagamos IIBB"): GROSS, even when ML later charges it back
(`shp_*`: +990 / -990). The charge keeps being subtracted where it is today;
this module only reads the money that came in, so the visible IVA line and the
varios base are built from the SAME amounts.

## ONE source: `payment.shipping_amount`

The explicit field ML labels as shipping, one value per payment. It is what
the visible line "Envío cobrado al comprador" (`iva.py`) has always read, and
the base now reads it through the same helper (`envio_comprador_de_pago`) and
the same aggregation: every RELEVANT payment of the order with a shipping
amount contributes once (a rejected payment never does), so an order with
three payments counts its shipping once, not three times.

Deliberately NOT used:

- `order.paid_amount - order.total_amount`: an inference that also catches
  anything else the buyer paid on top of the goods, such as a financing
  surcharge. It matches `shipping_amount` on every captured case, but the
  field is the one ML names.
- `raw_costs.receiver.cost`: ML annulled the 2216.30 of Flex pack
  2000015400388457 and `receiver.cost` still says 2216.30 (its
  `shipping_amount` is 0).
- the payment's `total_paid_amount - transaction_amount`: it also carries the
  payer's `tax_withholding_payer` (5107.54 instead of 4990 on order
  2000018846969514).

## Fail-closed

A non-numeric (a string, a bool, NaN/inf) or NEGATIVE amount adds nothing and
logs a warning with the `payment_id`. A null amount adds nothing and is
logged at debug (it is the normal state of a payment without shipping). Never
an exception: this runs inside the metrics recompute.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnvioCompradorOrden:
    """What the buyer paid for shipping on ONE order, gross and without IVA,
    both POSITIVE (the sign belongs to whoever puts it in a base)."""

    bruto: Decimal
    neto: Decimal


def envio_comprador_de_pago(shipping_amount: Any, payment_id: Optional[int] = None) -> Optional[Decimal]:
    """The shipping one payment carried, with IVA, or `None` for "nothing to
    add" (zero, null, or unreadable -- the unreadable ones are logged).
    Never raises."""
    if shipping_amount is None:
        logger.debug("envio_comprador: payment_id=%s has no shipping_amount", payment_id)
        return None
    # `bool` is an `int` in Python: `True` would be one peso.
    if isinstance(shipping_amount, bool) or not isinstance(shipping_amount, (int, float, Decimal)):
        logger.warning(
            "envio_comprador: payment_id=%s shipping_amount is not a number; contributing nothing", payment_id
        )
        return None
    if isinstance(shipping_amount, float) and not math.isfinite(shipping_amount):
        logger.warning("envio_comprador: payment_id=%s shipping_amount is not finite; contributing nothing", payment_id)
        return None
    value = Decimal(str(shipping_amount))
    if not value.is_finite():
        logger.warning("envio_comprador: payment_id=%s shipping_amount is not finite; contributing nothing", payment_id)
        return None
    if value < 0:
        logger.warning("envio_comprador: payment_id=%s shipping_amount is negative; contributing nothing", payment_id)
        return None
    return value if value > 0 else None

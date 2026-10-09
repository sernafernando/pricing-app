"""The basis of ads money, decided in ONE place (ml-billing-balance, design D6).

The tables store what the Ads API returned, untouched. Anything that subtracts ads from Total Gauss goes
through `ads_cost_net_of_iva`; no other module under `services/ml_ads/` or `services/ml_daily_metrics/` may
carry an IVA rate (a guard test enforces it). Ratios (ACOS, ROAS, CPC) stay on the API basis.

`brand_ads` is absent on purpose: it is informational and never subtracted, so asking for its basis raises.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, TypeVar, Union

from sqlalchemy.sql.elements import ColumnElement

from app.services.ml_ventas_desglose.iva import IVA_ML_DIVISOR  # import only; that package is not modified

Money = TypeVar("Money", bound=Union[Decimal, ColumnElement])  # a Decimal, or a SQL expression

# Billing is IVA-inclusive, so billing / API tells which basis the API uses.
ADS_IVA_MEASUREMENT: Dict[str, Dict[str, Any]] = {
    "product_ads": {
        "capture": "ads_iva_capture_20261008_111323.json.gz",
        "billing_period": "2026-09-01",
        "matched_lines": 195,  # PADS lines equal to round(API campaign-day cost * 1.21, 2) to the cent
        "median_ratio_billing_over_api": Decimal("1.21"),
    },
    "display": {
        "capture": "ads_capture_20261007_214456.json (consumed_budget) vs CDADSP billing lines",
        "billing_period": "2026-09-07..2026-09-16",
        "aggregate_ratio_billing_over_api": Decimal("1.1936"),  # day ratios 1.18-1.23; no per-line match
        "accepted_by": "owner (answer Q10, 2026-10-08)",
    },
}

API_COST_INCLUDES_IVA: Dict[str, bool] = {"product_ads": False, "display": False}


def includes_iva_for_ratio(ratio: Decimal) -> bool:
    """The design D6 decision rule: median(billing / API) near 1.21 means the API is net, near 1.00 gross."""
    if Decimal("1.205") <= ratio <= Decimal("1.215"):
        return False
    if Decimal("0.995") <= ratio <= Decimal("1.005"):
        return True
    raise ValueError(f"unexplained billing/API ratio {ratio}: an owner decision is needed")


def ads_cost_net_of_iva(value: Money, source: str = "product_ads") -> Money:
    """Decimal or SQLAlchemy expression -> the same type. The ONLY place ads money changes basis.

    Never rounds: `cents()` is applied once, at presentation."""
    if source not in API_COST_INCLUDES_IVA:
        raise ValueError(f"ads cost basis of {source!r} was never measured")
    return value / IVA_ML_DIVISOR if API_COST_INCLUDES_IVA[source] else value

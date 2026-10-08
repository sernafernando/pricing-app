"""`GET /marketplace/fbm/user-products/{MLAU}/replenishment?country=AR` (captured 2026-10-08).

Body: `{identifiers, product, stock, sales, recommendation, eligibility_benefits}`. `sales` is
`{sales_totals: {period, gmv: [{full}], currency, units_sold: [{full}]}, sales_history: [{start_date,
end_date, units_sold, days_out_of_stock, campaigns}]}` (newest week first as received, but the mapper sorts).

What the capture showed, and the rules that follow from it:
- The caller headers (`x-caller-id` / `x-caller-siteId`) the reference app gets from ml-webhook are NOT required
  on a direct call: the store sends only `Authorization`.
- A user product outside Full answers 200 with `inventory_id`, `stock`, `sales`, `recommendation` and
  `eligibility_benefits` null (the 404 the design expected never showed up), so `sales` may be null.
- A 206 is a partial answer (`x-content-missing` header); no 206 showed up in the capture. It is a 2xx, hence `ok`.

The mapper is a port of `parseReplenishment` (meli-full-report `src/meli/mlau.ts`), tests included. The key
(`user_product_id`) comes from the request, never from the body.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Optional

from app.services.ml_publications.mappers import to_decimal
from app.services.ml_publications.parsers.subresource import (
    MalformedSubResource,
    ParsedSubResource,
    parse_subresource,
    require_object,
)

PARTIAL_STATUS = 206
CONTENT_MISSING_HEADER = "x-content-missing"


def _validate(body: Any) -> None:
    obj = require_object(body, "replenishment")
    if "sales" not in obj or not (obj["sales"] is None or isinstance(obj["sales"], dict)):
        raise MalformedSubResource("replenishment: `sales` (object or null) is required")


def parse_replenishment(status: int, body: Any) -> ParsedSubResource:
    return parse_subresource(status, body, _validate)


def _int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _count(value: Any) -> int:
    """Weekly figure: a missing or malformed value counts 0, like `?? 0` in the reference app."""
    return _int(value) or 0


def _first_full(entries: Any) -> Any:
    """`units_sold` / `gmv` are lists with the Full figure in the first entry: `[0].full`."""
    if isinstance(entries, list) and entries and isinstance(entries[0], Mapping):
        return entries[0].get("full")
    return None


def _day(value: Any) -> Optional[date]:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _weeks(sales: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Weekly history, newest first (by `start_date`, as the reference app sorts it)."""
    history = sales.get("sales_history")
    weeks = [w for w in history if isinstance(w, Mapping)] if isinstance(history, list) else []
    return sorted(weeks, key=lambda w: str(w.get("start_date") or ""), reverse=True)


def map_replenishment(
    raw: Mapping[str, Any],
    _headers: Optional[Mapping[str, str]] = None,
    status: Optional[int] = None,
) -> dict[str, Any]:
    """Typed columns of `ml_user_product_replenishment`.

    Windows: 7/14/21 days are the sums of the newest 1/2/3 weeks, NULL while the history is shorter; days out of
    stock is the sum of the newest three. `partial` is true for a 206 or when `x-content-missing` is present.
    """
    headers = {str(k).lower(): v for k, v in (_headers or {}).items()}
    content_missing = _text(headers.get(CONTENT_MISSING_HEADER))

    sales = raw.get("sales") if isinstance(raw.get("sales"), Mapping) else {}
    totals = sales.get("sales_totals") if isinstance(sales.get("sales_totals"), Mapping) else {}
    stock = raw.get("stock") if isinstance(raw.get("stock"), Mapping) else {}

    weeks = _weeks(sales)
    units = [_count(w.get("units_sold")) for w in weeks]
    out_of_stock = [_count(w.get("days_out_of_stock")) for w in weeks]

    gmv: Optional[Decimal] = to_decimal(_first_full(totals.get("gmv")))
    return {
        "partial": status == PARTIAL_STATUS or content_missing is not None,
        "content_missing": content_missing,
        "period": _text(totals.get("period")),
        "units_30d": _int(_first_full(totals.get("units_sold"))),
        "gmv_30d": gmv,
        "currency_id": _text(totals.get("currency")),
        "units_7d": sum(units[:1]) if len(units) >= 1 else None,
        "units_14d": sum(units[:2]) if len(units) >= 2 else None,
        "units_21d": sum(units[:3]) if len(units) >= 3 else None,
        "days_out_of_stock_21d": sum(out_of_stock[:3]) if len(out_of_stock) >= 3 else None,
        "history_through": _day(weeks[0].get("end_date")) if weeks else None,
        "total_stock": _int(stock.get("total_stock")),
        "shipping_urgency": _text(stock.get("shipping_urgency")),
        "minimum_distributable_stock": _int(stock.get("minimum_distributable_stock")),
    }

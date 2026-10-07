"""`GET /items/{id}/visits/time_window?last=30&unit=day` (captured 2026-10-06).

Body: `{item_id, date_from, date_to, total_visits, last: 30, unit: "day", results: [{date, total,
visits_detail: [{company, quantity}]}]}`. `results` holds one entry per day WITH visits (an item with
none returns `[]`), in no particular order, so the diff engine keys it by `date`
(`diff.ARRAY_KEYS_BY_RESOURCE["visits"]`): a daily refetch reports the day that was added or dropped, never
the whole window. Typed columns describe the window; the daily series stays in raw.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ml_publications.mappers import to_timestamp
from app.services.ml_publications.parsers.subresource import (
    MalformedSubResource,
    ParsedSubResource,
    parse_subresource,
    require_object,
)


def _validate(body: Any) -> None:
    obj = require_object(body, "visits")
    results = obj.get("results", [])
    if not isinstance(results, list):
        raise MalformedSubResource("visits: `results` must be a list")
    for entry in results:
        if not isinstance(entry, dict) or not isinstance(entry.get("date"), str):
            raise MalformedSubResource("visits: every `results` entry must be an object with a `date`")


def parse_visits(status: int, body: Any) -> ParsedSubResource:
    return parse_subresource(status, body, _validate)


def _int(value: Any) -> Any:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def map_visits(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "window_days": _int(raw.get("last")),
        "total_visits": _int(raw.get("total_visits")),
        "date_from": to_timestamp(raw.get("date_from")),
        "date_to": to_timestamp(raw.get("date_to")),
    }

"""`GET /moderations/last_moderation/{id}-ITM` (captured 2026-10-06).

An item with no moderation answers `404 {"Status": 404}` (capital S, unlike every other 404 of the
store): that is the state "no moderation" (`has_moderation = false`), not a missing item and not an
error. Only that captured body is the state, so another 404 (a gateway, a different error shape) is
`not_found` and visible as such instead of being read as "no moderation".

An item with moderation records answers `200` with a JSON LIST of records `{id, name, evidence[], wordings[],
date_created}` (prod, 2026-10-14: `EXACT_DUPLICATE_CATALOG` on items under review); an item with none may
also answer `204` with no body. Both are states: the list is stored unchanged (`has_moderation = true` when
it holds a record) and the 204 is stored as the empty record list (`has_moderation = false`), so "no
moderation" reads the same whether it came as the 404 or the 204. What a record says (its `name`, its
wordings) is kept in raw and not interpreted: only presence is typed and raises events.

A 200 object (the shape assumed before a record was captured) is still accepted as one record.
"""

from __future__ import annotations

from typing import Any

from app.services.ml_publications.parsers.subresource import (
    MalformedSubResource,
    ParsedSubResource,
    parse_subresource,
    require_object,
)

NO_MODERATION_STATUS = 404
NO_MODERATION_BODY = {"Status": 404}
# HTTP status -> state name, as registered in `ResourceSpec.negative_states`.
NEGATIVE_STATES = {NO_MODERATION_STATUS: "no_moderation"}
NO_CONTENT_STATUS = 204
NO_RECORDS: list = []  # how a 204 (no body) is stored


def _validate(body: Any) -> None:
    if isinstance(body, list):
        if not all(isinstance(record, dict) for record in body):
            raise MalformedSubResource("moderation: every record of the list must be a JSON object")
        return
    require_object(body, "moderation")


def parse_moderation(status: int, body: Any) -> ParsedSubResource:
    if status == NO_MODERATION_STATUS and body == NO_MODERATION_BODY:
        return ParsedSubResource(status=status, state="ok", body=body)
    if status == NO_CONTENT_STATUS:
        if body is not None:
            raise MalformedSubResource("moderation: a 204 must have no body")
        return ParsedSubResource(status=status, state="ok", body=list(NO_RECORDS))
    return parse_subresource(status, body, _validate)


def map_moderation(raw: Any) -> dict[str, Any]:
    if isinstance(raw, list):
        return {"has_moderation": bool(raw)}
    return {"has_moderation": raw != NO_MODERATION_BODY}

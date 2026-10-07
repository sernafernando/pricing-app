"""`GET /moderations/last_moderation/{id}-ITM` (captured 2026-10-06).

An item with no moderation answers `404 {"Status": 404}` (capital S, unlike every other 404 of the
store): that is the state "no moderation" (`has_moderation = false`), not a missing item and not an
error. Only that captured body is the state, so another 404 (a gateway, a different error shape) is
`not_found` and visible as such instead of being read as "no moderation".

No item under review existed on 2026-10-06, so no moderation record was captured: a 200 object is
stored unchanged and typed only as `has_moderation = true`. The restrictive and resolved values inside
a record are NOT interpreted until a real record is captured. The fixture test
`test_moderation_captures_are_only_the_no_moderation_404_body` fails the day a record is added to the
fixture, which is the cue to revisit `map_moderation`, the events and `bundle.MODERATION_*`.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ml_publications.parsers.subresource import (
    ParsedSubResource,
    parse_subresource,
    require_object,
)

NO_MODERATION_STATUS = 404
NO_MODERATION_BODY = {"Status": 404}
# HTTP status -> state name, as registered in `ResourceSpec.negative_states`.
NEGATIVE_STATES = {NO_MODERATION_STATUS: "no_moderation"}


def _validate(body: Any) -> None:
    require_object(body, "moderation")


def parse_moderation(status: int, body: Any) -> ParsedSubResource:
    if status == NO_MODERATION_STATUS and body == NO_MODERATION_BODY:
        return ParsedSubResource(status=status, state="ok", body=body)
    return parse_subresource(status, body, _validate)


def map_moderation(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {"has_moderation": raw != NO_MODERATION_BODY}

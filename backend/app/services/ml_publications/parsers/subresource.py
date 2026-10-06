"""Shared envelope of the sub-resource parsers (pure, no I/O).

A fetch of one sub-resource ends in an HTTP status and a body. Classification is by
HTTP status, never by body shape (the 404 bodies differ per endpoint):

- 2xx  -> `ok`: the body is validated against the captured shape and kept unchanged as raw;
- 404  -> `not_found`: the item/user product is gone (or never existed);
- other non-2xx -> `error`: recorded with the status and the error body, never "gone".

Negative answers that are states rather than errors (moderation 404, performance 400) are
declared per resource by `ResourceSpec.negative_states`; none of the resources parsed here has one.

Each resource module pairs `parse_<resource>(status, body)` with `map_<resource>(raw)`. Mappers return
the typed non-key columns only: the entity key (item id, user product id, family id) always comes from
the request that was made, never from the body.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

NOT_FOUND_STATUS = 404


class MalformedSubResource(Exception):
    """A 2xx body does not have the shape captured for its endpoint."""


@dataclass(frozen=True)
class ParsedSubResource:
    status: int
    state: Literal["ok", "not_found", "error"]
    body: Any = None  # the 2xx body, unchanged (stored as raw)
    error_body: Optional[Any] = None  # non-2xx body, or None when the response had none


def parse_subresource(status: int, body: Any, validate: Callable[[Any], None]) -> ParsedSubResource:
    """Classify one response; `validate` raises `MalformedSubResource` for a bad 2xx body."""
    if 200 <= status < 300:
        validate(body)
        return ParsedSubResource(status=status, state="ok", body=body)
    state: Literal["not_found", "error"] = "not_found" if status == NOT_FOUND_STATUS else "error"
    return ParsedSubResource(status=status, state=state, error_body=body if body else None)


def require_object(body: Any, what: str) -> dict:
    if not isinstance(body, dict):
        raise MalformedSubResource(f"{what}: expected a JSON object, got {type(body).__name__}")
    return body

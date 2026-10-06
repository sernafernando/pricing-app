"""Parser for `GET /items/bulk` responses (pure, no I/O).

Shape normalization reuses `app.services.ml_multiget.parse_multiget` (shipped with
the bulk endpoint migration), which already understands every captured shape:

- full:     `{id, status_code, body}`; not found is `{id, status_code: 404, error}` with no body;
- filtered: `{body: {...selected fields}}` with no root id; not found is `{}`;
- legacy:   `{code, body}`, in a different order than the request.

On top of that this module adds what the store needs: matching every element to a
requested id (by id when present, by position for `{}`), strict validation (a
response that does not line up with the request is `MalformedBulkResponse` and
nothing from it may be applied) and the `partial` marker for attribute-filtered
bodies, which must never be persisted as an item's raw state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from app.services.ml_multiget import parse_multiget


class MalformedBulkResponse(Exception):
    """The response does not line up with the request; apply nothing, retry the batch."""


@dataclass(frozen=True)
class BulkElement:
    requested_id: str
    status: int  # 200 | 404 | any other element status (a failure, not "gone")
    body: Optional[dict]  # the item body for status 200; None otherwise
    partial: bool  # True for the attributes-filtered shape (never persisted as raw)


def parse_items_bulk(requested_ids: Sequence[str], payload: Any, *, filtered: bool) -> list[BulkElement]:
    """Match each response element to its requested id, in request order."""
    requested = list(requested_ids)
    if len(set(requested)) != len(requested):
        raise ValueError("requested_ids must be unique")
    if not isinstance(payload, list):
        raise MalformedBulkResponse(f"expected a JSON array, got {type(payload).__name__}")
    if len(payload) != len(requested):
        raise MalformedBulkResponse(f"requested {len(requested)} ids, response has {len(payload)} elements")

    elements = parse_multiget(payload)
    if len(elements) != len(payload):  # parse_multiget drops non-object elements
        raise MalformedBulkResponse("response contains elements that are not JSON objects")

    by_id: dict[str, BulkElement] = {}
    positional: list[int] = []
    for index, (raw, element) in enumerate(zip(payload, elements)):
        if element.id is None:
            if raw == {} and filtered:
                positional.append(index)  # `{}` means "that requested id was not found"
                continue
            raise MalformedBulkResponse(f"element {index} carries no id")
        if element.id not in requested:
            raise MalformedBulkResponse(f"response contains unrequested id {element.id!r}")
        if element.id in by_id:
            raise MalformedBulkResponse(f"response repeats id {element.id!r}")
        if element.status_code is None:
            raise MalformedBulkResponse(f"element {element.id!r} has no status")
        if element.status_code == 200 and element.body is None:
            raise MalformedBulkResponse(f"element {element.id!r} is 200 without a body")
        by_id[element.id] = BulkElement(element.id, element.status_code, element.body, partial=filtered)

    for index in positional:
        requested_id = requested[index]
        if requested_id in by_id:
            raise MalformedBulkResponse(f"empty element at position {index} collides with {requested_id!r}")
        by_id[requested_id] = BulkElement(requested_id, 404, None, partial=filtered)

    return [by_id[requested_id] for requested_id in requested]

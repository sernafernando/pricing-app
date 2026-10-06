"""`GET /items/{id}/description` (captured 2026-10-06): `{text, plain_text, last_updated, date_created, snapshot}`.

`text` was empty in every capture and `plain_text` carries the description. The item id is not
in the body: the key comes from the request.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.services.ml_publications.mappers import to_timestamp
from app.services.ml_publications.parsers.subresource import (
    MalformedSubResource,
    ParsedSubResource,
    parse_subresource,
    require_object,
)


def _validate(body: Any) -> None:
    obj = require_object(body, "description")
    if "text" not in obj and "plain_text" not in obj:
        raise MalformedSubResource("description: neither `text` nor `plain_text` present")


def parse_description(status: int, body: Any) -> ParsedSubResource:
    return parse_subresource(status, body, _validate)


def map_description(raw: Mapping[str, Any]) -> dict[str, Any]:
    plain_text = raw.get("plain_text")
    length: Optional[int] = len(plain_text) if isinstance(plain_text, str) else None
    return {"plain_text_length": length, "ml_last_updated": to_timestamp(raw.get("last_updated"))}

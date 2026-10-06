"""MercadoLibre multiget helpers (`/items/bulk`, replacing the deprecated `/items?ids=`).

ML deprecates `GET /items?ids=` (and `/users?ids=`) on 2026-10-25; the
replacement is `GET /items/bulk?ids=` (source:
https://developers.mercadolibre.com.ar/es_ar/items-y-busquedas).

The parser accepts every shape observed in production (captured 2026-10-06,
`tests/fixtures/ml/items_bulk_capture_20261006.json`) so a mixed rollout
(pricing app vs. ml-webhook bridge) can never break:

- bulk:        `{"id", "status_code": 200, "body": {...}}`; not found has `status_code` 404 and NO `body`.
- bulk + `attributes=body.*`: `{"body": {"id", ...}}` with no root `id`/`status_code`;
  an unknown id comes back as `{}`.
- legacy:      `{"code": 200|404, "body": {...}}`; the 404 body is an error payload (it carries an `id`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

# Deprecated multiget allowed 20 ids per call; the bulk limit is undocumented.
MAX_IDS_PER_CALL = 20
BULK_ITEMS_PATH = "/items/bulk"


@dataclass(frozen=True)
class MultigetElement:
    id: Optional[str]
    status_code: Optional[int]
    body: Optional[Dict[str, Any]]  # only set when the element is a found item

    @property
    def ok(self) -> bool:
        return self.body is not None


def parse_multiget(payload: Any) -> List[MultigetElement]:
    """Normalize a multiget response (any observed shape) into `MultigetElement`s."""
    if not isinstance(payload, list):
        return []

    parsed: List[MultigetElement] = []
    for element in payload:
        if not isinstance(element, dict):
            continue

        raw_body = element.get("body")
        body = raw_body if isinstance(raw_body, dict) and raw_body else None

        status = element.get("status_code", element.get("code"))
        if status is None and body is not None and body.get("id") is not None:
            # `attributes=body.*` shape: no status field, a populated body means found.
            status = 200

        item_id = element.get("id")
        if item_id is None and body is not None:
            item_id = body.get("id")

        found = status == 200 and body is not None
        parsed.append(MultigetElement(id=item_id, status_code=status, body=body if found else None))
    return parsed


def chunked(ids: List[str], size: int = MAX_IDS_PER_CALL) -> Iterable[List[str]]:
    for start in range(0, len(ids), size):
        yield ids[start : start + size]

"""Parser for ML multiget responses (`/items/bulk` + legacy `/items?ids=`).

Fixtures are the REAL production capture
`tests/fixtures/ml/items_bulk_capture_20261006.json` (2026-10-06). The ML docs
(https://developers.mercadolibre.com.ar/es_ar/items-y-busquedas) document the
`code` -> `status_code` rename and root `id` but give no bulk response example.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.ml_multiget import MAX_IDS_PER_CALL, parse_multiget

CAPTURE = Path(__file__).resolve().parent.parent / "fixtures" / "ml" / "items_bulk_capture_20261006.json"
FOUND = ("MLA935110613", "MLA934406852")


def _call(name: str) -> list:
    data = json.loads(CAPTURE.read_text(encoding="utf-8"))
    return next(c["body"] for c in data["calls"] if c["name"] == name)


def test_max_ids_is_twenty() -> None:
    assert MAX_IDS_PER_CALL == 20


def test_bulk_full_shape() -> None:
    parsed = parse_multiget(_call("bulk_full"))
    assert [e.id for e in parsed] == [*FOUND, "MLA1"]
    assert [e.status_code for e in parsed] == [200, 200, 404]
    assert parsed[0].body["id"] == FOUND[0]
    assert parsed[2].body is None
    assert [e.ok for e in parsed] == [True, True, False]


def test_bulk_attributes_shape_takes_id_from_body_and_empty_is_not_found() -> None:
    parsed = parse_multiget(_call("bulk_attributes"))
    assert [e.id for e in parsed[:2]] == list(FOUND)
    assert all(e.ok for e in parsed[:2])
    assert set(parsed[0].body) == {"id", "status", "available_quantity"}
    assert parsed[2].ok is False
    assert parsed[2].body is None
    assert parsed[2].id is None


def test_bulk_single_shape() -> None:
    parsed = parse_multiget(_call("bulk_single"))
    assert [(e.id, e.ok) for e in parsed] == [(FOUND[0], True)]


def test_legacy_shape_404_body_is_not_an_item() -> None:
    parsed = parse_multiget(_call("legacy_multiget"))
    assert [e.status_code for e in parsed] == [200, 200, 404]
    assert [e.ok for e in parsed] == [True, True, False]
    # the legacy 404 body carries error fields (and an id): it must not be exposed as an item
    assert parsed[2].body is None
    assert {e.id for e in parsed[:2]} == set(FOUND)


@pytest.mark.parametrize("junk", [None, {}, "x", 3])
def test_non_list_payload_yields_nothing(junk) -> None:
    assert parse_multiget(junk) == []


def test_junk_elements_are_skipped() -> None:
    assert [e.ok for e in parse_multiget([None, "x", {}, {"status_code": 200, "body": {"id": "MLA9"}}])] == [
        False,
        True,
    ]

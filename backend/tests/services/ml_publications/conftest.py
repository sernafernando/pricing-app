"""Loader helpers for the real ML captures under tests/fixtures/ml_publications/.

Every payload used by the ml_publications tests comes from these files (real
production captures, 2026-10-06). Tests that need a transition mutate a deep
copy of a real payload by exactly one field and say so in their docstring.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "ml_publications"

BULK_CAPTURE = "items_bulk_capture_20261006_015628.json"
ITEM_SAMPLES = "items_bulk_samples_20261006.json"
ITEM_WITH_VARIATIONS = "item_with_variations_MLA1207279308.json"


def load_fixture(name: str) -> Any:
    with (FIXTURES_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def bulk_call(name: str) -> Any:
    """Body of one named call of the `/items/bulk` capture (deep copy)."""
    for call in load_fixture(BULK_CAPTURE)["calls"]:
        if call["name"] == name:
            return copy.deepcopy(call["body"])
    raise KeyError(name)


def sample_item(item_id: str) -> dict:
    """Full item body (the `body` of a 200 `/items/bulk` element) captured for `item_id`."""
    for element in load_fixture(ITEM_SAMPLES)["elements"]:
        if element["id"] == item_id:
            return copy.deepcopy(element["body"])
    raise KeyError(item_id)


def bulk_item(item_id: str) -> dict:
    """Full item body from the first `/items/bulk` capture (MLA935110613, MLA934406852)."""
    for element in bulk_call("bulk_full"):
        if element.get("id") == item_id:
            return copy.deepcopy(element["body"])
    raise KeyError(item_id)


@pytest.fixture
def fixture_loader():
    return load_fixture

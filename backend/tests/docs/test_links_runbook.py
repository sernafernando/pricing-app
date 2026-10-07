"""The product-links runbook names only routes, permissions and settings that exist."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.routers import ml_publications_links as router_module
from app.services.ml_publications import settings_store

DOC = Path(__file__).resolve().parents[3] / "docs" / "ml-publications-links-runbook.md"


@pytest.fixture(scope="module")
def doc() -> str:
    assert DOC.exists(), f"missing {DOC}"
    return DOC.read_text(encoding="utf-8")


def test_every_route_of_the_router_is_documented_with_its_verb(doc) -> None:
    for route in router_module.router.routes:
        for method in route.methods:
            path = "/api" + route.path
            assert f"{method} {path}" in doc, f"{method} {path}"


def test_the_documented_routes_are_only_real_ones(doc) -> None:
    real = {f"{m} /api{r.path}" for r in router_module.router.routes for m in r.methods}
    documented = set(re.findall(r"^\s*(?:GET|PUT|POST|DELETE) /api/\S+", doc, flags=re.MULTILINE))
    assert {d.strip() for d in documented} <= real


def test_both_permissions_and_the_flags_are_named(doc) -> None:
    assert router_module.PERMISO_VER in doc and router_module.PERMISO_VINCULAR in doc
    for key in ("links.enabled", "events.enabled"):
        assert key in doc and key in settings_store.SETTING_DEFS


def test_the_runbook_says_a_no_change_write_may_still_refresh_the_suggestion(doc) -> None:
    assert "the unit's SKU suggestion may still be refreshed" in doc

"""The admin endpoints section of the topics checklist names only routes, jobs and permissions that exist."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.routers import ml_publications_admin
from app.services.ml_publications import admin

DOC = Path(__file__).resolve().parents[3] / "docs" / "ml-publications-topics-checklist.md"
PREFIX = "/api/ml-publications"


@pytest.fixture(scope="module")
def section() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index("## Admin endpoints")
    nxt = text.find("\n## ", start + 1)
    return " ".join(text[start : nxt if nxt != -1 else len(text)].split())  # one line: wrapping is not content


def test_every_route_in_the_table_exists_with_the_documented_verb_and_permission(section) -> None:
    routes = {
        (method, route.path): route
        for route in ml_publications_admin.router.routes
        for method in getattr(route, "methods", set())
    }
    documented = re.findall(r"\| `(GET|PUT|POST) (/[\w/{}.-]+)` \| `(ml_ops\.\w+)`", section)
    assert len(documented) == 5
    for verb, path, permission in documented:
        route = routes[(verb, f"/ml-publications{path}")]
        assert permission in (ml_publications_admin.PERMISO_VER, ml_publications_admin.PERMISO_GESTIONAR)
        assert route.path == f"/ml-publications{path}"


def test_every_curl_example_targets_a_documented_path(section) -> None:
    paths = re.findall(r'"\$API(/api/ml-publications/[\w/{}.-]+)"', section)
    assert len(paths) == 5
    for path in paths:
        assert path.startswith(PREFIX)


def test_the_jobs_named_are_exactly_the_requestable_ones(section) -> None:
    named = re.search(r"`job` is (.+?)\. `scan`", section).group(1)
    assert set(re.findall(r"`(\w+)`", named)) == set(admin.JOBS)


def test_the_documented_intake_threshold_is_the_configured_default(section) -> None:
    from app.core.config import settings

    assert f"(default {settings.ML_PUB_INTAKE_STALL_SECONDS})" in section

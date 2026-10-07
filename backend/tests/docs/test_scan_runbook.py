"""The scan runbook (first backfill) names only commands, settings and handlers that exist."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.ml_publications import scans, settings_store

DOC = Path(__file__).resolve().parents[3] / "docs" / "ml-publications-scan-runbook.md"


@pytest.fixture(scope="module")
def doc() -> str:
    assert DOC.exists(), f"missing {DOC}"
    return DOC.read_text(encoding="utf-8")


def test_every_setting_the_runbook_sets_is_allow_listed(doc) -> None:
    keys = set(re.findall(r"ml_publications_settings set ([\w.]+)", doc))
    assert {"scan.enabled", "scan.statuses"} <= keys
    assert keys <= set(settings_store.SETTING_DEFS)


def test_the_runbook_uses_the_request_cli_with_the_scan_handler_and_both_modes(doc) -> None:
    assert "ml_publications_request ml_publications.scan --mode full" in doc
    assert "--mode rescan" in doc


def test_the_runbook_names_the_default_status_order_with_closed_first(doc) -> None:
    default = settings.ML_PUB_SCAN_STATUSES
    assert default[0] == "closed"
    assert ",".join(default) in doc


def test_the_runbook_states_every_scan_status_it_can_ask_for(doc) -> None:
    for status in scans.ALL_SCAN_STATUSES:
        assert f"`{status}`" in doc


def test_the_runbook_covers_pause_rollback_and_the_core_only_bundle(doc) -> None:
    assert "scan.enabled false" in doc
    assert '["core"]' in doc
    assert "ml_pub_scan_state" in doc


def test_the_runbook_says_a_full_request_during_a_full_lap_is_satisfied_by_that_lap(doc) -> None:
    assert "already full" in doc and "satisfied by that lap" in doc

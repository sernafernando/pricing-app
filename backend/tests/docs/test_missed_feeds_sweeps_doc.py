"""The missed feeds and sweeps section of the topics checklist names only settings, handlers and numbers that exist."""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.ml_publications import missed_feeds, settings_store, sweeps
from app.workers import registry

DOC = Path(__file__).resolve().parents[3] / "docs" / "ml-publications-topics-checklist.md"


@pytest.fixture(scope="module")
def section() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index("## Missed feeds and sweeps")
    nxt = text.find("\n## ", start + 1)
    return " ".join(text[start : nxt if nxt != -1 else len(text)].split())  # one line: wrapping is not content


def test_every_setting_the_section_sets_is_allow_listed_and_its_value_is_valid(section) -> None:
    commands = re.findall(r"ml_publications_settings set ([\w.]+) (\S+)", section)
    assert {key for key, _ in commands} >= {
        "missed_feeds.enabled",
        "sweep.enabled",
        "sweep.statuses",
        "bundle_resources",
    }
    for key, raw in commands:
        value = json.loads(raw.strip().strip("'`"))
        assert key in settings_store.SETTING_DEFS, key
        assert settings_store.SETTING_DEFS[key].valid(value), (key, value)


def test_both_handlers_exist_with_the_documented_schedule(section) -> None:
    by_name = {h.name: h for h in registry.ML_PUBLICATIONS_REGISTRY}
    assert by_name["ml_publications.missed_feeds"].interval == timedelta(hours=2)
    assert by_name["ml_publications.sweep"].interval == timedelta(minutes=10)
    for needle in ("`ml_publications.missed_feeds`", "`ml_publications.sweep`", "every 2 hours", "every 10 minutes"):
        assert needle in section, needle


def test_the_sizing_is_the_one_the_design_states(section) -> None:
    for needle in (
        "24.6k",
        "about 49k calls a day",
        "0.57 req/s",
        "about 15.6k calls a day",
        "0.18 req/s",
        '["active"]',
    ):
        assert needle in section, needle
    assert round(sweeps.requests_per_second(sweeps.daily_calls(24_600, 24_600)), 2) == 0.57


def test_the_default_statuses_are_every_non_closed_status_and_closed_is_never_swept(section) -> None:
    assert set(settings.ML_PUB_SWEEP_STATUSES) == {"active", "paused", "under_review", "inactive", "pending"}
    assert "`closed`" in section and "never" in section
    assert str(settings.ML_PUB_NOT_APPLICABLE_RECHECK_DAYS) in section and "not_applicable" in section


def test_the_gap_rule_and_the_retention_are_stated_with_the_real_constant(section) -> None:
    assert f"{missed_feeds.GAP_HOURS} h" in section and "2 days" in section
    assert "coverage gap" in section and "rescan" in section


def test_the_checks_use_the_run_records_and_the_rollback_is_the_flags(section) -> None:
    assert "ml_pub_job_runs" in section and "job = 'missed_feeds'" in section and "job = 'sweep'" in section
    assert "missed_feeds.enabled false" in section and "sweep.enabled false" in section
    assert "Rollback" in section


def test_the_resume_age_limit_is_the_real_constant(section) -> None:
    from app.workers.handlers import ml_publications as handlers

    hours = int(handlers.MISSED_FEEDS_RESUME_MAX_AGE.total_seconds() // 3600)
    assert f"older than {hours} hours is dropped" in section


def test_the_yielded_outcome_is_explained(section) -> None:
    assert "`yielded`" in section and "expected, not a fault" in section


def test_the_health_signals_and_the_unconfirmed_ordering_are_stated(section) -> None:
    assert "`last_success_at` is not a health signal" in section
    assert "does not say in which order" in section


def test_the_parked_items_note_is_present(section) -> None:
    assert "parked" in section and "enqueued by hand" in section


def test_the_flags_are_independent_and_the_sweep_needs_its_resources_listed(section) -> None:
    assert "independent" in section.lower()
    assert "performance" in section and "visits" in section and "bundle_resources" in section


def test_the_capture_limitations_are_stated(section) -> None:
    assert "`stock-location`" in section and "`user_products`" in section and "wrong topic names" in section
    assert str(missed_feeds.PAGE_LIMIT) in section


def test_the_stale_sweeps_will_come_later_notes_are_gone() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "arrive in a later PR" not in text and "only once their sweeps ship" not in text
    assert "the sweeps of a later PR do" not in text

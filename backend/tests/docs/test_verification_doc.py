"""The verification jobs section of the topics checklist names only settings, handlers and numbers that exist."""

from __future__ import annotations

import json
import re
from datetime import time, timedelta
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.ml_publications import admin, queue, settings_store, verification
from app.workers import registry

DOC = Path(__file__).resolve().parents[3] / "docs" / "ml-publications-topics-checklist.md"


@pytest.fixture(scope="module")
def section() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index("## Verification jobs")
    nxt = text.find("\n## ", start + 1)
    return " ".join(text[start : nxt if nxt != -1 else len(text)].split())  # one line: wrapping is not content


def test_every_setting_the_section_sets_is_allow_listed_and_its_value_is_valid(section) -> None:
    commands = re.findall(r"ml_publications_settings set ([\w.]+) (\S+?)[`\s)]", section + " ")
    assert {key for key, _ in commands} == {"divergence.enabled", "verify.enabled"}
    for key, raw in commands:
        value = json.loads(raw)
        assert key in settings_store.SETTING_DEFS, key
        assert settings_store.SETTING_DEFS[key].valid(value), (key, value)


def test_the_handler_exists_with_the_documented_schedule_and_the_flags_default_off(section) -> None:
    handler = next(h for h in registry.ML_PUBLICATIONS_REGISTRY if h.name == "ml_publications.verify")
    assert handler.run_at_local == time(5, 0) and handler.catch_up_interval == timedelta(minutes=2)
    for needle in ("`ml_publications.verify`", "daily at 05:00", "2 minutes later"):
        assert needle in section, needle
    assert settings.ML_PUB_VERIFY_ENABLED is False and settings.ML_PUB_DIVERGENCE_ENABLED is False


def test_the_documented_numbers_are_the_configured_ones(section) -> None:
    assert f"default {settings.ML_PUB_DIVERGENCE_SAMPLE_SIZE}" in section
    assert f"The target is {verification.TARGET_RATE:.0f}%" in section
    assert f"sweep lane ({queue.LANE_SWEEP})" in section and verification.LANE == queue.LANE_SWEEP
    assert "20 per call" in section and settings.ML_PUB_BULK_MAX_IDS == 20


def test_the_run_record_names_and_job_names_are_the_ones_the_code_writes(section) -> None:
    assert f"`job = '{verification.JOB_DIVERGENCE}'`" in section
    assert f"`job = '{verification.JOB_SNAPSHOT}'`" in section
    assert f"`outcome = '{verification.OUTCOME_BELOW_TARGET}'`" in section


def test_the_jobs_the_request_endpoint_documents_run_the_verify_handler() -> None:
    assert admin.JOBS["verify"][0] == admin.JOBS["divergence"][0] == "ml_publications.verify"

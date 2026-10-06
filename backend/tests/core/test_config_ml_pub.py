"""Defaults of the ML publications store settings (design D19).

Every flag defaults to off and every tunable to its documented value, so a
fresh deploy with no env overrides is inert.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings

ENABLED_FLAGS = (
    "ML_PUB_REFRESH_ENABLED",
    "ML_PUB_INTAKE_ENABLED",
    "ML_PUB_SCAN_ENABLED",
    "ML_PUB_MISSED_FEEDS_ENABLED",
    "ML_PUB_SWEEP_ENABLED",
    "ML_PUB_EVENTS_ENABLED",
    "ML_PUB_PROMOTIONS_ENABLED",
    "ML_PUB_LINKS_ENABLED",
    "ML_PUB_VERIFY_ENABLED",
    "ML_PUB_DIVERGENCE_ENABLED",
)


@pytest.fixture()
def clean_settings(monkeypatch):
    for name in (*ENABLED_FLAGS, "ML_PUB_KILL_SWITCH", "ML_PUB_RATE_PER_SEC", "ML_PUB_BULK_MAX_IDS"):
        monkeypatch.delenv(name, raising=False)

    def build() -> Settings:
        return Settings(_env_file=None)

    return build


@pytest.mark.parametrize("flag", ENABLED_FLAGS)
def test_every_enabled_flag_defaults_to_false(clean_settings, flag) -> None:
    assert getattr(clean_settings(), flag) is False


def test_kill_switch_defaults_to_false(clean_settings) -> None:
    assert clean_settings().ML_PUB_KILL_SWITCH is False


def test_numeric_tunables_have_documented_defaults(clean_settings) -> None:
    s = clean_settings()
    assert s.ML_PUB_RATE_PER_SEC == 2.0
    assert s.ML_PUB_STOCK_RATE_PER_MIN == 60
    assert s.ML_PUB_BULK_MAX_IDS == 20
    assert s.ML_PUB_LEASE_SECONDS == 300
    assert s.ML_PUB_MAX_ATTEMPTS == 8
    assert s.ML_PUB_LOW_LANE_MIN_SHARE == 0.1


def test_bundle_resources_default_is_core_only(clean_settings) -> None:
    assert clean_settings().ML_PUB_BUNDLE_RESOURCES == ["core"]


def test_intake_topics_default_is_items_only(clean_settings) -> None:
    topics = clean_settings().ML_PUB_INTAKE_TOPICS
    assert topics == {"items": {"kind": "item", "resources": ["bundle"]}}


def test_env_overrides_a_default(monkeypatch, clean_settings) -> None:
    monkeypatch.setenv("ML_PUB_RATE_PER_SEC", "5")
    monkeypatch.setenv("ML_PUB_REFRESH_ENABLED", "true")
    s = clean_settings()
    assert s.ML_PUB_RATE_PER_SEC == 5.0
    assert s.ML_PUB_REFRESH_ENABLED is True


def test_bulk_max_ids_is_capped_at_the_ml_hard_limit(monkeypatch, clean_settings) -> None:
    monkeypatch.setenv("ML_PUB_BULK_MAX_IDS", "21")
    with pytest.raises(ValueError):
        clean_settings()

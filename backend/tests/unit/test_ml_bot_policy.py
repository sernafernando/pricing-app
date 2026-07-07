"""
T-B1/T-B3: Unit tests — services/ml_questions/policy.py

Covers (Slice B, spec R-201/R-202/R-203, design §5/§11, ADR-4):
- get_config(): live DB read + type casting, treats "" as unset (gotcha from Judgment Day).
- is_within_business_hours(): [start, end) half-open boundary, business_days, timezone.
- get_operating_mode() gate: off_hours_only vs always_on eligibility.
- resolve_wait_minutes(): always_on business-hours override vs default wait_minutes.

Pure logic — no DB session held during evaluation; config values are passed in
via a `ml_bot_config` SQLite-backed `db` fixture, read live (no indefinite cache).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.models.ml_bot_config import MlBotConfig
from app.services.ml_questions import policy


def _seed_config(db, **overrides: str) -> None:
    """Seed ml_bot_config rows matching the Slice A migration defaults, with overrides."""
    defaults = {
        "bot_enabled": ("false", "bool"),
        "operating_mode": ("off_hours_only", "string"),
        "business_hours_start": ("09:00", "time"),
        "business_hours_end": ("18:00", "time"),
        "business_days": ("[1,2,3,4,5]", "json"),
        "timezone": ("America/Argentina/Buenos_Aires", "string"),
        "wait_minutes": ("5", "int"),
        "wait_minutes_business_hours": ("", "int"),
        "min_confidence": ("0.6", "string"),
        "ingest_cursor_ts": ("", "string"),
    }
    for clave, (valor, tipo) in defaults.items():
        actual_valor = overrides.get(clave, valor)
        db.add(MlBotConfig(clave=clave, valor=str(actual_valor), tipo=tipo))
    db.flush()


class TestGetConfig:
    """T-B1 (RED first): config accessor casting + empty-string gotcha."""

    def test_get_config_casts_int(self, db) -> None:
        _seed_config(db, wait_minutes="7")
        assert policy.get_config(db, "wait_minutes", cast=int) == 7

    def test_get_config_casts_bool_true(self, db) -> None:
        _seed_config(db, bot_enabled="true")
        assert policy.get_config(db, "bot_enabled", cast=bool) is True

    def test_get_config_casts_bool_false(self, db) -> None:
        _seed_config(db, bot_enabled="false")
        assert policy.get_config(db, "bot_enabled", cast=bool) is False

    def test_get_config_missing_key_returns_default(self, db) -> None:
        _seed_config(db)
        assert policy.get_config(db, "does_not_exist", cast=str, default="fallback") == "fallback"

    def test_get_config_empty_string_int_returns_none_not_valueerror(self, db) -> None:
        """Judgment Day gotcha: wait_minutes_business_hours seeded as "" must not raise
        ValueError on int() cast — must be treated as unset (None)."""
        _seed_config(db, wait_minutes_business_hours="")
        assert policy.get_config(db, "wait_minutes_business_hours", cast=int) is None

    def test_get_config_empty_string_str_returns_none(self, db) -> None:
        """ingest_cursor_ts seeded as "" must also be treated as unset for str cast."""
        _seed_config(db, ingest_cursor_ts="")
        assert policy.get_config(db, "ingest_cursor_ts", cast=str) is None

    def test_get_config_empty_string_with_explicit_default(self, db) -> None:
        _seed_config(db, wait_minutes_business_hours="")
        assert policy.get_config(db, "wait_minutes_business_hours", cast=int, default=99) == 99


class TestIsWithinBusinessHours:
    """T-B1: [start, end) half-open boundary — R-202."""

    tz = ZoneInfo("America/Argentina/Buenos_Aires")

    def test_start_boundary_is_in_hours(self, db) -> None:
        _seed_config(db)
        # Tuesday 09:00:00 exactly -> in-hours (inclusive start)
        now = datetime(2026, 7, 7, 9, 0, 0, tzinfo=self.tz)
        assert policy.is_within_business_hours(db, now) is True

    def test_end_boundary_is_out_of_hours(self, db) -> None:
        _seed_config(db)
        # Tuesday 18:00:00 exactly -> off-hours (exclusive end)
        now = datetime(2026, 7, 7, 18, 0, 0, tzinfo=self.tz)
        assert policy.is_within_business_hours(db, now) is False

    def test_mid_business_hours(self, db) -> None:
        _seed_config(db)
        now = datetime(2026, 7, 7, 14, 0, 0, tzinfo=self.tz)
        assert policy.is_within_business_hours(db, now) is True

    def test_after_hours_at_night(self, db) -> None:
        _seed_config(db)
        now = datetime(2026, 7, 7, 22, 0, 0, tzinfo=self.tz)
        assert policy.is_within_business_hours(db, now) is False

    def test_weekend_is_out_of_hours(self, db) -> None:
        _seed_config(db)
        # Saturday 2026-07-11, 14:00 -> not in business_days [1..5]
        now = datetime(2026, 7, 11, 14, 0, 0, tzinfo=self.tz)
        assert policy.is_within_business_hours(db, now) is False

    def test_naive_datetime_is_localized_to_configured_timezone(self, db) -> None:
        _seed_config(db)
        now = datetime(2026, 7, 7, 14, 0, 0)  # naive
        assert policy.is_within_business_hours(db, now) is True


class TestOperatingModeGate:
    """T-B3: operating-mode gate — R-201."""

    tz = ZoneInfo("America/Argentina/Buenos_Aires")

    def test_off_hours_only_blocks_bot_during_business_hours(self, db) -> None:
        _seed_config(db, operating_mode="off_hours_only")
        now = datetime(2026, 7, 7, 14, 0, 0, tzinfo=self.tz)  # Tuesday in-hours
        assert policy.is_eligible_for_bot(db, now) is False

    def test_off_hours_only_allows_bot_off_hours(self, db) -> None:
        _seed_config(db, operating_mode="off_hours_only")
        now = datetime(2026, 7, 7, 22, 0, 0, tzinfo=self.tz)  # off-hours
        assert policy.is_eligible_for_bot(db, now) is True

    def test_always_on_allows_bot_during_business_hours(self, db) -> None:
        _seed_config(db, operating_mode="always_on")
        now = datetime(2026, 7, 7, 14, 0, 0, tzinfo=self.tz)  # in-hours
        assert policy.is_eligible_for_bot(db, now) is True

    def test_always_on_allows_bot_off_hours_too(self, db) -> None:
        _seed_config(db, operating_mode="always_on")
        now = datetime(2026, 7, 7, 22, 0, 0, tzinfo=self.tz)
        assert policy.is_eligible_for_bot(db, now) is True

    def test_unknown_operating_mode_defaults_to_off_hours_only_behavior(self, db) -> None:
        _seed_config(db, operating_mode="bogus_mode")
        now = datetime(2026, 7, 7, 14, 0, 0, tzinfo=self.tz)  # in-hours
        assert policy.is_eligible_for_bot(db, now) is False


class TestResolveWaitMinutes:
    """T-B3: wait-window selection — R-203."""

    tz = ZoneInfo("America/Argentina/Buenos_Aires")

    def test_off_hours_uses_standard_wait(self, db) -> None:
        _seed_config(db, operating_mode="off_hours_only", wait_minutes="5", wait_minutes_business_hours="15")
        now = datetime(2026, 7, 7, 22, 0, 0, tzinfo=self.tz)
        assert policy.resolve_wait_minutes(db, now) == 5

    def test_always_on_in_hours_uses_business_hours_override_when_set(self, db) -> None:
        _seed_config(db, operating_mode="always_on", wait_minutes="5", wait_minutes_business_hours="15")
        now = datetime(2026, 7, 7, 11, 0, 0, tzinfo=self.tz)
        assert policy.resolve_wait_minutes(db, now) == 15

    def test_always_on_in_hours_falls_back_to_standard_wait_when_override_unset(self, db) -> None:
        _seed_config(db, operating_mode="always_on", wait_minutes="5", wait_minutes_business_hours="")
        now = datetime(2026, 7, 7, 11, 0, 0, tzinfo=self.tz)
        assert policy.resolve_wait_minutes(db, now) == 5

    def test_always_on_off_hours_uses_standard_wait(self, db) -> None:
        _seed_config(db, operating_mode="always_on", wait_minutes="5", wait_minutes_business_hours="15")
        now = datetime(2026, 7, 7, 22, 0, 0, tzinfo=self.tz)
        assert policy.resolve_wait_minutes(db, now) == 5

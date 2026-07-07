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

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

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
        _seed_config(db, bot_enabled="true", operating_mode="off_hours_only")
        now = datetime(2026, 7, 7, 14, 0, 0, tzinfo=self.tz)  # Tuesday in-hours
        assert policy.is_eligible_for_bot(db, now) is False

    def test_off_hours_only_allows_bot_off_hours(self, db) -> None:
        _seed_config(db, bot_enabled="true", operating_mode="off_hours_only")
        now = datetime(2026, 7, 7, 22, 0, 0, tzinfo=self.tz)  # off-hours
        assert policy.is_eligible_for_bot(db, now) is True

    def test_always_on_allows_bot_during_business_hours(self, db) -> None:
        _seed_config(db, bot_enabled="true", operating_mode="always_on")
        now = datetime(2026, 7, 7, 14, 0, 0, tzinfo=self.tz)  # in-hours
        assert policy.is_eligible_for_bot(db, now) is True

    def test_always_on_allows_bot_off_hours_too(self, db) -> None:
        _seed_config(db, bot_enabled="true", operating_mode="always_on")
        now = datetime(2026, 7, 7, 22, 0, 0, tzinfo=self.tz)
        assert policy.is_eligible_for_bot(db, now) is True

    def test_unknown_operating_mode_defaults_to_off_hours_only_behavior(self, db) -> None:
        _seed_config(db, bot_enabled="true", operating_mode="bogus_mode")
        now = datetime(2026, 7, 7, 14, 0, 0, tzinfo=self.tz)  # in-hours
        assert policy.is_eligible_for_bot(db, now) is False


class TestBotEnabledKillSwitch:
    """Fix 5: `is_eligible_for_bot` must itself check `bot_enabled` (single
    source of truth for the kill switch), regardless of mode/time."""

    tz = ZoneInfo("America/Argentina/Buenos_Aires")

    def test_bot_enabled_false_blocks_regardless_of_mode_and_time(self, db) -> None:
        _seed_config(db, bot_enabled="false", operating_mode="always_on")
        now = datetime(2026, 7, 7, 22, 0, 0, tzinfo=self.tz)  # off-hours, always_on -> would be True
        assert policy.is_eligible_for_bot(db, now) is False

    def test_bot_enabled_missing_defaults_to_disabled(self, db) -> None:
        _seed_config(db, bot_enabled="", operating_mode="always_on")
        now = datetime(2026, 7, 7, 22, 0, 0, tzinfo=self.tz)
        assert policy.is_eligible_for_bot(db, now) is False

    def test_bot_enabled_true_preserves_existing_truth_table(self, db) -> None:
        _seed_config(db, bot_enabled="true", operating_mode="off_hours_only")
        now = datetime(2026, 7, 7, 22, 0, 0, tzinfo=self.tz)  # off-hours -> eligible
        assert policy.is_eligible_for_bot(db, now) is True


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

    def test_wait_minutes_business_hours_zero_returns_zero(self, db) -> None:
        """Fix 8/INFO: explicit "0" override means instant publish, not unset."""
        _seed_config(db, operating_mode="always_on", wait_minutes="5", wait_minutes_business_hours="0")
        now = datetime(2026, 7, 7, 11, 0, 0, tzinfo=self.tz)
        assert policy.resolve_wait_minutes(db, now) == 0


class TestResolvePollIntervalSeconds:
    """Judgment Day fix: `poll_interval_seconds` is seeded/documented as a
    panel-editable interval for the ingest/draft background loops, but was
    never read — both loops hardcoded `asyncio.sleep(30)`. Fail-safe like
    every other config read: missing/empty/malformed -> default; a typo like
    "0" must not hot-loop, so results are clamped to a sane floor."""

    def test_missing_config_returns_default(self, db) -> None:
        assert policy.resolve_poll_interval_seconds(db) == 30

    def test_valid_config_is_used(self, db) -> None:
        db.add(MlBotConfig(clave="poll_interval_seconds", valor="45", tipo="int"))
        db.flush()
        assert policy.resolve_poll_interval_seconds(db) == 45

    def test_malformed_config_falls_back_to_default_without_crashing(self, db) -> None:
        db.add(MlBotConfig(clave="poll_interval_seconds", valor="not-a-number", tipo="int"))
        db.flush()
        assert policy.resolve_poll_interval_seconds(db) == 30

    def test_empty_config_falls_back_to_default(self, db) -> None:
        db.add(MlBotConfig(clave="poll_interval_seconds", valor="", tipo="int"))
        db.flush()
        assert policy.resolve_poll_interval_seconds(db) == 30

    def test_below_floor_is_clamped_to_floor(self, db) -> None:
        db.add(MlBotConfig(clave="poll_interval_seconds", valor="0", tipo="int"))
        db.flush()
        assert policy.resolve_poll_interval_seconds(db) == 5

    def test_negative_value_is_clamped_to_floor(self, db) -> None:
        db.add(MlBotConfig(clave="poll_interval_seconds", valor="-10", tipo="int"))
        db.flush()
        assert policy.resolve_poll_interval_seconds(db) == 5


class TestMalformedConfigFailsSafe:
    """Fix 4: malformed config values must not crash the gate; they must fail
    SAFE (treated as within business hours -> bot NOT eligible in
    off_hours_only mode) and log a warning."""

    tz = ZoneInfo("America/Argentina/Buenos_Aires")

    _LOGGER_NAME = "app.services.ml_questions.policy"

    @pytest.fixture(autouse=True)
    def _allow_log_propagation(self):
        """The `app` root logger sets propagate=False (app/core/logging.py) to
        avoid duplicate logs under uvicorn; re-enable propagation for the
        duration of these tests so caplog (which attaches to the root logger)
        can observe the warning emitted by `policy.logger`."""
        app_logger = logging.getLogger("app")
        original = app_logger.propagate
        app_logger.propagate = True
        try:
            yield
        finally:
            app_logger.propagate = original

    def test_malformed_business_hours_start_fails_safe(self, db, caplog) -> None:
        _seed_config(db, business_hours_start="930")  # missing colon
        now = datetime(2026, 7, 7, 11, 0, 0, tzinfo=self.tz)
        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            result = policy.is_within_business_hours(db, now)
        assert result is True  # fail-safe: treated as in-hours
        assert any("business_hours_start" in record.getMessage() for record in caplog.records)

    def test_malformed_business_hours_end_fails_safe(self, db, caplog) -> None:
        _seed_config(db, business_hours_end="not-a-time")
        now = datetime(2026, 7, 7, 11, 0, 0, tzinfo=self.tz)
        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            result = policy.is_within_business_hours(db, now)
        assert result is True
        assert any("business_hours_end" in record.getMessage() for record in caplog.records)

    def test_malformed_business_days_json_fails_safe(self, db, caplog) -> None:
        _seed_config(db, business_days="1,2,3,4,5")  # invalid JSON (no brackets)
        now = datetime(2026, 7, 7, 11, 0, 0, tzinfo=self.tz)
        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            result = policy.is_within_business_hours(db, now)
        assert result is True
        assert any("business_days" in record.getMessage() for record in caplog.records)

    def test_malformed_timezone_fails_safe(self, db, caplog) -> None:
        _seed_config(db, timezone="Not/A_Real_Zone")
        now = datetime(2026, 7, 7, 11, 0, 0, tzinfo=self.tz)
        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            result = policy.is_within_business_hours(db, now)
        assert result is True
        assert any("timezone" in record.getMessage() for record in caplog.records)

    def test_malformed_config_does_not_raise(self, db) -> None:
        _seed_config(db, business_hours_start="930", business_days="bogus", timezone="Bogus/Zone")
        now = datetime(2026, 7, 7, 11, 0, 0, tzinfo=self.tz)
        # Must not raise any exception.
        policy.is_within_business_hours(db, now)

    @pytest.mark.parametrize("bad_business_days", ["5", "true", "null", '"mon"'])
    def test_valid_json_non_list_business_days_fails_safe(self, db, caplog, bad_business_days: str) -> None:
        """Fix 1/CRITICAL: business_days that parses as valid JSON but is not a
        list (e.g. a bare number, bool, null, or string) must not reach
        `isoweekday() not in business_days` — that raises an uncaught
        TypeError for non-container types. Must fail safe instead."""
        _seed_config(db, business_days=bad_business_days)
        now = datetime(2026, 7, 7, 11, 0, 0, tzinfo=self.tz)
        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            result = policy.is_within_business_hours(db, now)
        assert result is True
        assert any("business_days" in record.getMessage() for record in caplog.records)

    @pytest.mark.parametrize("bad_hour", ["25:00", "09:99"])
    def test_out_of_range_hour_or_minute_fails_safe(self, db, caplog, bad_hour: str) -> None:
        """Fix 4/INFO: "25:00" or "09:99" parse as ints fine but are out of
        range for hour/minute and must fail safe rather than silently
        producing wrong boundaries."""
        _seed_config(db, business_hours_start=bad_hour)
        now = datetime(2026, 7, 7, 11, 0, 0, tzinfo=self.tz)
        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            result = policy.is_within_business_hours(db, now)
        assert result is True
        assert any("business_hours_start" in record.getMessage() for record in caplog.records)


class TestResolveWaitMinutesHardening:
    """Fix 3/WARNING: non-numeric wait_minutes / wait_minutes_business_hours
    must not crash `resolve_wait_minutes` — same class as the round-1 config
    fix for empty-string handling in `get_config`."""

    tz = ZoneInfo("America/Argentina/Buenos_Aires")

    _LOGGER_NAME = "app.services.ml_questions.policy"

    @pytest.fixture(autouse=True)
    def _allow_log_propagation(self):
        app_logger = logging.getLogger("app")
        original = app_logger.propagate
        app_logger.propagate = True
        try:
            yield
        finally:
            app_logger.propagate = original

    def test_malformed_wait_minutes_falls_back_to_default(self, db, caplog) -> None:
        _seed_config(db, operating_mode="off_hours_only", wait_minutes="five")
        now = datetime(2026, 7, 7, 22, 0, 0, tzinfo=self.tz)
        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            result = policy.resolve_wait_minutes(db, now)
        assert result == policy._DEFAULT_WAIT_MINUTES
        assert any("wait_minutes" in record.getMessage() for record in caplog.records)

    def test_malformed_wait_minutes_business_hours_treated_as_unset(self, db, caplog) -> None:
        _seed_config(
            db,
            operating_mode="always_on",
            wait_minutes="5",
            wait_minutes_business_hours="5m",
        )
        now = datetime(2026, 7, 7, 11, 0, 0, tzinfo=self.tz)  # in-hours
        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            result = policy.resolve_wait_minutes(db, now)
        assert result == 5  # falls back to standard wait_minutes
        assert any("wait_minutes_business_hours" in record.getMessage() for record in caplog.records)


class TestBusinessDaysBooleanElementsFailSafe:
    """Judgment Day follow-up: `business_days` elements must reject booleans.
    In Python, `isinstance(True, int)` is True, so `[true, false]` parses as
    valid JSON, passes the old `isinstance(day, int)` element check, and
    silently behaves as `[1, 0]` instead of failing safe."""

    tz = ZoneInfo("America/Argentina/Buenos_Aires")

    _LOGGER_NAME = "app.services.ml_questions.policy"

    @pytest.fixture(autouse=True)
    def _allow_log_propagation(self):
        app_logger = logging.getLogger("app")
        original = app_logger.propagate
        app_logger.propagate = True
        try:
            yield
        finally:
            app_logger.propagate = original

    def test_boolean_business_days_elements_fail_safe(self, db, caplog) -> None:
        _seed_config(db, business_days="[true, false]")
        now = datetime(2026, 7, 7, 11, 0, 0, tzinfo=self.tz)
        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            result = policy.is_within_business_hours(db, now)
        assert result is True  # fail-safe: treated as in-hours
        assert any("business_days" in record.getMessage() for record in caplog.records)

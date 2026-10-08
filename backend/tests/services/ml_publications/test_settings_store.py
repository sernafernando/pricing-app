"""DB-backed runtime settings with env defaults and an env-only kill switch (design D19)."""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.ml_publications import settings_store
from app.services.ml_publications.settings_store import get_setting, get_settings, is_enabled, set_setting


@pytest.fixture()
def settings_db(monkeypatch, engine):
    """SQLite session factory behind `get_background_db()`; table emptied around each test."""
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.core.database.SessionLocal", factory)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ml_pub_settings"))
    yield factory
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ml_pub_settings"))


def _insert_raw(engine, key: str, json_literal: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO ml_pub_settings (key, value, updated_at) VALUES (:k, :v, CURRENT_TIMESTAMP)"),
            {"k": key, "v": json_literal},
        )


class TestDefaults:
    def test_missing_row_falls_back_to_env_default_and_is_flagged(self, settings_db) -> None:
        got = get_setting("refresh.enabled")
        assert (got.value, got.source) == (False, "env")

    def test_env_default_is_read_at_call_time(self, settings_db, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ML_PUB_REFRESH_ENABLED", True)
        got = get_setting("refresh.enabled")
        assert (got.value, got.source) == (True, "env")

    def test_numeric_and_list_defaults_come_from_config(self, settings_db) -> None:
        assert get_setting("rate_per_sec").value == 2.0
        assert get_setting("bundle_resources").value == ["core"]

    def test_the_default_bundle_does_not_fetch_stock(self, settings_db) -> None:
        """S74.1: the per-location stock columns are filled only once an operator adds `stock`."""
        assert "stock" not in get_setting("bundle_resources").value

    def test_mutating_a_returned_default_does_not_corrupt_the_config(self, settings_db) -> None:
        get_setting("bundle_resources").value.append("prices")
        assert get_setting("bundle_resources").value == ["core"]


class TestScanNextMode:
    """`scan.next_mode` is how an operator asks for the next scan lap to be a full backfill (design D17)."""

    def test_defaults_to_rescan_from_the_env(self, settings_db) -> None:
        got = get_setting("scan.next_mode")
        assert (got.value, got.source) == ("rescan", "env")

    def test_full_can_be_requested_and_consumed_back_to_rescan(self, settings_db) -> None:
        set_setting("scan.next_mode", "full", updated_by="tester")
        assert get_setting("scan.next_mode").value == "full"
        set_setting("scan.next_mode", "rescan", updated_by="scan")
        assert get_setting("scan.next_mode").value == "rescan"

    @pytest.mark.parametrize("value", ["everything", "", True, 1, ["full"]])
    def test_any_other_value_is_rejected_and_nothing_is_written(self, settings_db, engine, value) -> None:
        with pytest.raises(ValueError):
            set_setting("scan.next_mode", value, updated_by="tester")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM ml_pub_settings")).scalar() == 0

    def test_an_invalid_env_value_fails_at_startup_instead_of_being_served(self) -> None:
        with pytest.raises(ValueError):
            type(settings)(ML_PUB_SCAN_NEXT_MODE="everything")

    def test_an_invalid_stored_value_falls_back_to_the_env_default(self, settings_db, engine) -> None:
        _insert_raw(engine, "scan.next_mode", '"everything"')
        got = get_setting("scan.next_mode")
        assert (got.value, got.source) == ("rescan", "env")


class TestScanStatuses:
    @pytest.mark.parametrize("value", [["closd"], [], ["closed", "everything"], "closed", [1]])
    def test_a_misspelled_or_empty_status_list_is_rejected_at_write(self, settings_db, engine, value) -> None:
        with pytest.raises(ValueError):
            set_setting("scan.statuses", value, updated_by="tester")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM ml_pub_settings")).scalar() == 0

    def test_every_scannable_status_is_accepted_in_any_order(self, settings_db) -> None:
        every = ["active", "paused", "closed", "under_review", "inactive", "pending"]
        set_setting("scan.statuses", every, updated_by="tester")
        assert get_setting("scan.statuses").value == every

    def test_an_invalid_stored_list_falls_back_to_the_env_default(self, settings_db, engine) -> None:
        _insert_raw(engine, "scan.statuses", '["closd"]')
        got = get_setting("scan.statuses")
        assert got.source == "env" and got.value[0] == "closed"


class TestScanStatusesEnv:
    @pytest.mark.parametrize("value", [["closd"], []])
    def test_a_bad_env_default_fails_at_startup(self, value) -> None:
        with pytest.raises(ValueError):
            type(settings)(ML_PUB_SCAN_STATUSES=value)

    def test_the_env_validation_and_the_store_share_one_status_vocabulary(self) -> None:
        from app.core.config import SCAN_STATUS_NAMES

        from app.services.ml_publications import scans

        assert scans.ALL_SCAN_STATUSES is SCAN_STATUS_NAMES


class TestSweepStatuses:
    """`sweep.statuses` narrows the sweep without a deploy; closed items are never swept."""

    @pytest.mark.parametrize("value", [["activ"], [], ["closed"], ["active", "closed"], "active", [1]])
    def test_a_misspelled_empty_or_closed_status_list_is_rejected_at_write(self, settings_db, engine, value) -> None:
        with pytest.raises(ValueError):
            set_setting("sweep.statuses", value, updated_by="tester")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM ml_pub_settings")).scalar() == 0

    def test_narrowing_to_active_is_accepted_and_read_back(self, settings_db) -> None:
        set_setting("sweep.statuses", ["active"], updated_by="tester")
        got = get_setting("sweep.statuses")
        assert (got.value, got.source) == (["active"], "db")

    def test_the_default_is_every_non_closed_status(self, settings_db) -> None:
        from app.core.config import SCAN_STATUS_NAMES

        got = get_setting("sweep.statuses")
        assert got.source == "env" and set(got.value) == set(SCAN_STATUS_NAMES) - {"closed"}

    def test_an_invalid_stored_list_falls_back_to_the_env_default(self, settings_db, engine) -> None:
        _insert_raw(engine, "sweep.statuses", '["closed"]')
        assert get_setting("sweep.statuses").source == "env"

    @pytest.mark.parametrize("value", [["closd"], [], ["closed"]])
    def test_a_bad_env_default_fails_at_startup(self, value) -> None:
        with pytest.raises(ValueError):
            type(settings)(ML_PUB_SWEEP_STATUSES=value)


class TestDbOverridesEnv:
    def test_db_row_overrides_env(self, settings_db) -> None:
        set_setting("rate_per_sec", 5.0, updated_by="tester")
        got = get_setting("rate_per_sec")
        assert (got.value, got.source) == (5.0, "db")
        assert settings.ML_PUB_RATE_PER_SEC == 2.0

    def test_flag_can_be_enabled_at_runtime(self, settings_db) -> None:
        assert is_enabled("refresh") is False
        set_setting("refresh.enabled", True, updated_by="tester")
        assert is_enabled("refresh") is True
        set_setting("refresh.enabled", False, updated_by="tester")
        assert is_enabled("refresh") is False

    def test_set_setting_records_who_changed_it(self, settings_db, engine) -> None:
        set_setting("bulk_max_ids", 10, updated_by="fernando")
        set_setting("bulk_max_ids", 12, updated_by="ops")
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT value, updated_by FROM ml_pub_settings WHERE key = 'bulk_max_ids'")).all()
        assert [r[1] for r in rows] == ["ops"]
        assert get_setting("bulk_max_ids").value == 12


class TestBatchRead:
    def test_get_settings_reads_many_keys_in_one_session(self, settings_db, monkeypatch) -> None:
        set_setting("rate_per_sec", 4.0, updated_by="tester")
        set_setting("refresh.enabled", True, updated_by="tester")
        opened = []

        def counting_factory():
            opened.append(1)
            return settings_db()

        monkeypatch.setattr("app.core.database.SessionLocal", counting_factory)
        got = get_settings(["refresh.enabled", "rate_per_sec", "bundle_resources"])
        assert len(opened) == 1
        assert {k: (v.value, v.source) for k, v in got.items()} == {
            "refresh.enabled": (True, "db"),
            "rate_per_sec": (4.0, "db"),
            "bundle_resources": (["core"], "env"),
        }

    def test_get_settings_applies_kill_switch_and_validation_per_key(self, settings_db, engine, monkeypatch) -> None:
        set_setting("events.enabled", True, updated_by="tester")
        _insert_raw(engine, "bulk_max_ids", "99")  # invalid: above the ML hard limit
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)
        got = get_settings(["events.enabled", "bulk_max_ids"])
        assert (got["events.enabled"].value, got["events.enabled"].source) == (False, "kill_switch")
        assert (got["bulk_max_ids"].value, got["bulk_max_ids"].source) == (20, "env")

    def test_get_settings_rejects_an_unknown_key_before_reading(self, settings_db) -> None:
        with pytest.raises(ValueError, match="unknown"):
            get_settings(["rate_per_sec", "made.up"])

    def test_get_settings_with_no_keys_returns_nothing_without_a_query(self, settings_db, monkeypatch) -> None:
        monkeypatch.setattr("app.core.database.SessionLocal", lambda: pytest.fail("no session expected"))
        assert get_settings([]) == {}


class TestKillSwitch:
    def test_kill_switch_overrides_every_enabled_flag(self, settings_db, monkeypatch) -> None:
        for handler in ("refresh", "intake", "events"):
            set_setting(f"{handler}.enabled", True, updated_by="tester")
            assert is_enabled(handler) is True
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)
        for handler in ("refresh", "intake", "events"):
            assert is_enabled(handler) is False
        got = get_setting("refresh.enabled")
        assert (got.value, got.source) == (False, "kill_switch")

    def test_kill_switch_does_not_rewrite_tunables(self, settings_db, monkeypatch) -> None:
        set_setting("rate_per_sec", 3.0, updated_by="tester")
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)
        assert get_setting("rate_per_sec").value == 3.0

    def test_kill_switch_does_not_touch_the_database(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)

        def boom():
            raise AssertionError("the kill switch must answer before any DB read")

        monkeypatch.setattr("app.core.database.SessionLocal", boom)
        assert is_enabled("refresh") is False


class TestFailClosed:
    @pytest.fixture()
    def unreadable(self, monkeypatch):
        empty = create_engine("sqlite://")  # no ml_pub_settings table at all
        monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=empty))

    def test_unreadable_table_disables_the_handler(self, unreadable, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ML_PUB_REFRESH_ENABLED", True)  # env says on; unreadable still wins
        assert is_enabled("refresh") is False
        got = get_setting("refresh.enabled")
        assert (got.value, got.source) == (False, "unreadable")

    def test_unreadable_table_keeps_tunables_on_their_env_default(self, unreadable) -> None:
        got = get_setting("rate_per_sec")
        assert (got.value, got.source) == (2.0, "env")


class TestInvalidValues:
    @pytest.mark.parametrize(
        ("key", "literal", "expected"),
        [
            ("rate_per_sec", '"fast"', 2.0),
            ("refresh.enabled", '"yes"', False),
            ("bundle_resources", "7", ["core"]),
            ("bulk_max_ids", "21", 20),
            ("stock_rate_per_min", "0", 60),
        ],
    )
    def test_invalid_db_value_falls_back_to_env_and_is_logged(
        self, settings_db, engine, caplog, key, literal, expected
    ) -> None:
        _insert_raw(engine, key, literal)
        with caplog.at_level(logging.WARNING, logger=settings_store.logger.name):
            got = get_setting(key)
        assert (got.value, got.source) == (expected, "env")
        assert key in caplog.text

    @pytest.mark.parametrize(
        ("key", "value"),
        [("refresh.enabled", "true"), ("rate_per_sec", -1), ("bulk_max_ids", 21), ("bundle_resources", "core")],
    )
    def test_set_setting_rejects_an_invalid_value_and_writes_nothing(self, settings_db, engine, key, value) -> None:
        with pytest.raises(ValueError):
            set_setting(key, value, updated_by="tester")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM ml_pub_settings")).scalar() == 0


class TestAllowList:
    def test_unknown_key_is_rejected_on_write(self, settings_db, engine) -> None:
        with pytest.raises(ValueError, match="unknown"):
            set_setting("lease_seconds", 10, updated_by="tester")  # env-only, not runtime-settable
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM ml_pub_settings")).scalar() == 0

    def test_unknown_key_is_rejected_on_read(self, settings_db) -> None:
        with pytest.raises(ValueError, match="unknown"):
            get_setting("made.up")

    def test_unknown_handler_is_rejected(self, settings_db) -> None:
        with pytest.raises(ValueError, match="unknown"):
            is_enabled("nope")


@pytest.mark.postgres
class TestPostgresJsonb:
    def test_list_and_object_values_round_trip_as_jsonb(self, mlpub_pg) -> None:
        set_setting("bundle_resources", ["core", "prices"], updated_by="tester")
        topics = {"items": {"kind": "item", "resources": ["bundle"]}, "items_prices": {"kind": "item"}}
        set_setting("intake.topics", topics, updated_by="tester")
        assert get_setting("bundle_resources").value == ["core", "prices"]
        assert get_setting("intake.topics").value == topics
        with mlpub_pg.connect() as conn:
            kind = conn.execute(text("SELECT jsonb_typeof(value) FROM ml_pub_settings WHERE key='bundle_resources'"))
            assert kind.scalar() == "array"

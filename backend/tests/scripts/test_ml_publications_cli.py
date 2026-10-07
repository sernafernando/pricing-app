"""Operator CLIs of the ML publications store: runtime settings, single-item enqueue and
on-demand job requests. They share the service functions the handlers use and never call ML.

Postgres only: the queue and the request flag use Postgres statements.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.scripts import ml_publications_enqueue, ml_publications_request, ml_publications_settings
from app.services.ml_publications import ml_http
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401  (fixture re-export)

pytestmark = pytest.mark.postgres


@pytest.fixture()
def env(mlpub_pg, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)

    def no_ml_client(*args, **kwargs):
        raise AssertionError("the CLIs must never build an ML client")

    monkeypatch.setattr(ml_http.MlHttpClient, "__init__", no_ml_client)
    with mlpub_pg.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE worker_job_state (name varchar(64) PRIMARY KEY, last_run_at timestamptz, "
                "last_success_at timestamptz, state varchar(32), detail jsonb, heartbeat_at timestamptz)"
            )
        )
    return mlpub_pg


def rows(engine, statement: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement), params).mappings().all()


class TestSettingsGet:
    def test_prints_the_env_default_with_its_source_when_there_is_no_row(self, env, capsys) -> None:
        assert ml_publications_settings.main(["get", "refresh.enabled"]) == 0

        assert capsys.readouterr().out.strip() == "refresh.enabled = false (source: env)"

    def test_prints_the_db_value_with_its_source(self, env, capsys) -> None:
        ml_publications_settings.main(["set", "refresh.enabled", "true"])
        capsys.readouterr()

        ml_publications_settings.main(["get", "refresh.enabled"])

        assert capsys.readouterr().out.strip() == "refresh.enabled = true (source: db)"

    def test_without_a_key_prints_every_allow_listed_setting(self, env, capsys) -> None:
        ml_publications_settings.main(["get"])

        out = capsys.readouterr().out
        assert "refresh.enabled = false (source: env)" in out
        assert 'bundle_resources = ["core"] (source: env)' in out

    def test_a_kill_switch_is_reported_as_the_source(self, env, capsys, monkeypatch) -> None:
        ml_publications_settings.main(["set", "refresh.enabled", "true"])
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)
        capsys.readouterr()

        ml_publications_settings.main(["get", "refresh.enabled"])

        assert capsys.readouterr().out.strip() == "refresh.enabled = false (source: kill_switch)"

    def test_an_unknown_key_is_rejected(self, env, capsys) -> None:
        assert ml_publications_settings.main(["get", "nope"]) != 0
        assert "unknown" in capsys.readouterr().err


class TestSettingsSet:
    def test_writes_the_row_with_the_operator_name(self, env) -> None:
        assert ml_publications_settings.main(["set", "refresh.enabled", "true", "--by", "fernando"]) == 0

        (row,) = rows(env, "SELECT key, value, updated_by FROM ml_pub_settings")
        assert (row["key"], row["value"], row["updated_by"]) == ("refresh.enabled", True, "fernando")

    def test_values_are_json(self, env) -> None:
        ml_publications_settings.main(["set", "bundle_resources", '["core","prices"]'])

        (row,) = rows(env, "SELECT value FROM ml_pub_settings WHERE key = 'bundle_resources'")
        assert row["value"] == ["core", "prices"]

    def test_rejects_keys_that_are_not_allow_listed_and_writes_nothing(self, env, capsys) -> None:
        assert ml_publications_settings.main(["set", "ML_PUB_KILL_SWITCH", "true"]) != 0

        assert "unknown" in capsys.readouterr().err
        assert rows(env, "SELECT * FROM ml_pub_settings") == []

    def test_rejects_an_invalid_value_and_writes_nothing(self, env, capsys) -> None:
        assert ml_publications_settings.main(["set", "bulk_max_ids", "99"]) != 0
        assert ml_publications_settings.main(["set", "refresh.enabled", "yes"]) != 0

        assert rows(env, "SELECT * FROM ml_pub_settings") == []

    def test_the_default_operator_name_identifies_the_cli(self, env) -> None:
        ml_publications_settings.main(["set", "refresh.enabled", "false"])

        (row,) = rows(env, "SELECT updated_by FROM ml_pub_settings")
        assert row["updated_by"].startswith("cli:")


class TestEnqueue:
    def test_writes_a_manual_lane_entry_for_the_whole_bundle(self, env, capsys) -> None:
        assert ml_publications_enqueue.main(["MLA935110613", "MLA934406852"]) == 0

        found = rows(env, "SELECT entity_id, kind, lane, resources FROM ml_pub_refresh_queue ORDER BY entity_id")
        assert [(r["entity_id"], r["kind"], r["lane"], list(r["resources"])) for r in found] == [
            ("MLA934406852", "item", 0, ["bundle"]),
            ("MLA935110613", "item", 0, ["bundle"]),
        ]
        assert "enqueued 2" in capsys.readouterr().out

    def test_says_so_when_processing_is_disabled_but_still_accepts_the_entry(self, env, capsys) -> None:
        ml_publications_enqueue.main(["MLA935110613"])

        out = capsys.readouterr().out
        assert "processing is disabled" in out and "refresh.enabled" in out
        assert len(rows(env, "SELECT 1 FROM ml_pub_refresh_queue")) == 1

    def test_is_quiet_about_it_when_refresh_is_enabled(self, env, capsys) -> None:
        ml_publications_settings.main(["set", "refresh.enabled", "true"])
        capsys.readouterr()

        ml_publications_enqueue.main(["MLA935110613"])

        assert "disabled" not in capsys.readouterr().out

    def test_enqueuing_twice_keeps_one_entry(self, env) -> None:
        ml_publications_enqueue.main(["MLA935110613"])
        ml_publications_enqueue.main(["MLA935110613"])

        assert len(rows(env, "SELECT 1 FROM ml_pub_refresh_queue")) == 1

    def test_rejects_an_id_that_is_not_an_item_id_and_enqueues_nothing(self, env, capsys) -> None:
        assert ml_publications_enqueue.main(["MLA935110613", "not-an-id"]) != 0

        assert "not-an-id" in capsys.readouterr().err
        assert rows(env, "SELECT 1 FROM ml_pub_refresh_queue") == []

    def test_a_mistyped_resource_is_rejected_and_nothing_is_enqueued(self, env, capsys) -> None:
        with pytest.raises(SystemExit) as exit_info:
            ml_publications_enqueue.main(["MLA935110613", "--resources", "corre"])

        assert exit_info.value.code != 0
        assert "corre" in capsys.readouterr().err
        assert rows(env, "SELECT 1 FROM ml_pub_refresh_queue") == []

    def test_every_resource_the_design_names_is_accepted(self, env) -> None:
        for resource in ("bundle", "core", "description", "prices", "sale_price", "promotions", "stock", "family"):
            assert ml_publications_enqueue.main(["MLA935110613", "--resources", resource]) == 0

    def test_a_resource_can_be_named_explicitly(self, env) -> None:
        ml_publications_enqueue.main(["MLA935110613", "--resources", "core"])

        (row,) = rows(env, "SELECT resources FROM ml_pub_refresh_queue")
        assert list(row["resources"]) == ["core"]


class TestRequestJob:
    def test_marks_the_handler_as_requested(self, env, capsys) -> None:
        assert ml_publications_request.main(["ml_publications.refresh"]) == 0

        (row,) = rows(env, "SELECT name, state FROM worker_job_state")
        assert (row["name"], row["state"]) == ("ml_publications.refresh", "requested")
        assert "requested" in capsys.readouterr().out

    def test_keeps_the_schedule_columns_of_an_existing_row(self, env) -> None:
        with env.begin() as conn:
            conn.execute(
                text("INSERT INTO worker_job_state (name, last_success_at) VALUES ('ml_publications.refresh', now())")
            )

        ml_publications_request.main(["ml_publications.refresh"])

        (row,) = rows(env, "SELECT state, last_success_at FROM worker_job_state")
        assert row["state"] == "requested" and row["last_success_at"] is not None

    def test_rejects_a_name_that_is_not_an_ml_publications_handler(self, env, capsys) -> None:
        assert ml_publications_request.main(["order_metrics.drain"]) != 0

        assert "ml_publications.refresh" in capsys.readouterr().err
        assert rows(env, "SELECT 1 FROM worker_job_state") == []


class TestRequestScanMode:
    """`--mode` asks the scan for a full backfill (or an explicit rescan) on its next lap (design D17)."""

    def test_full_sets_the_next_mode_and_requests_the_scan(self, env, capsys) -> None:
        assert ml_publications_request.main(["ml_publications.scan", "--mode", "full"]) == 0

        (row,) = rows(env, "SELECT name, state FROM worker_job_state")
        assert (row["name"], row["state"]) == ("ml_publications.scan", "requested")
        (mode,) = rows(env, "SELECT value, updated_by FROM ml_pub_settings WHERE key = 'scan.next_mode'")
        assert mode["value"] == "full" and mode["updated_by"].startswith("cli:")
        assert "full" in capsys.readouterr().out

    def test_rescan_overrides_an_earlier_full_request(self, env) -> None:
        ml_publications_request.main(["ml_publications.scan", "--mode", "full"])
        ml_publications_request.main(["ml_publications.scan", "--mode", "rescan"])

        (mode,) = rows(env, "SELECT value FROM ml_pub_settings WHERE key = 'scan.next_mode'")
        assert mode["value"] == "rescan"

    def test_without_a_mode_the_setting_is_left_alone(self, env) -> None:
        ml_publications_request.main(["ml_publications.scan"])

        assert rows(env, "SELECT 1 FROM ml_pub_settings WHERE key = 'scan.next_mode'") == []
        (row,) = rows(env, "SELECT state FROM worker_job_state")
        assert row["state"] == "requested"

    def test_a_mode_is_only_valid_for_the_scan_and_nothing_is_written(self, env, capsys) -> None:
        assert ml_publications_request.main(["ml_publications.refresh", "--mode", "full"]) != 0

        assert "scan" in capsys.readouterr().err
        assert rows(env, "SELECT 1 FROM worker_job_state") == []
        assert rows(env, "SELECT 1 FROM ml_pub_settings") == []

    def test_an_unknown_mode_is_rejected(self, env) -> None:
        with pytest.raises(SystemExit):
            ml_publications_request.main(["ml_publications.scan", "--mode", "everything"])
        assert rows(env, "SELECT 1 FROM worker_job_state") == []

    def test_the_mode_and_the_request_are_written_together_or_not_at_all(self, env) -> None:
        with env.begin() as conn:
            conn.execute(text("DROP TABLE worker_job_state"))  # the request insert fails

        with pytest.raises(Exception):
            ml_publications_request.main(["ml_publications.scan", "--mode", "full"])

        assert rows(env, "SELECT 1 FROM ml_pub_settings WHERE key = 'scan.next_mode'") == []

    def test_an_unresolvable_os_user_falls_back_to_cli_unknown(self, env, monkeypatch) -> None:
        import getpass

        def no_user():
            raise KeyError("getpwuid(): uid not found")

        monkeypatch.setattr(getpass, "getuser", no_user)

        assert ml_publications_request.main(["ml_publications.scan", "--mode", "full"]) == 0

        (mode,) = rows(env, "SELECT updated_by FROM ml_pub_settings WHERE key = 'scan.next_mode'")
        assert mode["updated_by"] == "cli:unknown"

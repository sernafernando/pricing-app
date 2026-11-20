"""One-off backfill: queue every active catalog listing that never had a catalog-competition snapshot.

Postgres only. Listings are synthetic `ml_items` rows (only the columns the selection reads).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.models.catalog_competition_refresh_pending import CatalogCompetitionRefreshPending
from app.models.ml_catalog_competition import MLCatalogCompetition
from app.scripts.catalog_competition_backfill import enqueue_never_consulted, main
from app.services.ml_publications import store as store_module

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def env(mlpub_pg):
    CatalogCompetitionRefreshPending.__table__.create(bind=mlpub_pg, checkfirst=True)
    # mlpub_schema may already apply 20260731_ml_catalog_competition for hay_mejores prefetch.
    MLCatalogCompetition.__table__.create(bind=mlpub_pg, checkfirst=True)
    return mlpub_pg


def add_item(engine, item_id: str, *, catalog: bool = True, status: str = "active") -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_items (item_id, status, catalog_listing, raw, raw_hash, fetched_at, last_checked_at, "
                "first_seen_at) VALUES (:i, :s, :c, '{}', '\\x00', now(), now(), now())"
            ),
            {"i": item_id, "s": status, "c": catalog},
        )


def add_snapshot(engine, mla: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_catalog_competition (mla, fecha_consulta, fetch_status, competitors, competitor_count) "
                "VALUES (:m, now(), 'ok', '[]', 0)"
            ),
            {"m": mla},
        )


def pending(engine) -> list[tuple[str, datetime]]:
    with engine.connect() as conn:
        return [
            (r.mla, r.due_at)
            for r in conn.execute(
                text("SELECT mla, due_at FROM catalog_competition_refresh_pending ORDER BY due_at, mla")
            )
        ]


def run(**kwargs) -> int:
    with store_module.database.get_background_db() as db:
        return enqueue_never_consulted(db, NOW, **kwargs)


class TestSelection:
    def test_only_active_catalog_listings_without_a_snapshot_are_queued(self, env) -> None:
        add_item(env, "MLA1000000001")
        add_item(env, "MLA1000000002")
        add_snapshot(env, "MLA1000000002")
        add_item(env, "MLA1000000003", catalog=False)
        add_item(env, "MLA1000000004", status="paused")

        assert run(spacing_seconds=6) == 1
        assert [mla for mla, _ in pending(env)] == ["MLA1000000001"]

    def test_queued_entries_are_spaced_so_the_drain_never_starves_live_changes(self, env) -> None:
        for n in range(1, 4):
            add_item(env, f"MLA100000000{n}")

        run(spacing_seconds=6)

        assert [due for _, due in pending(env)] == [NOW + timedelta(seconds=6 * i) for i in range(3)]

    def test_limit_caps_one_run(self, env) -> None:
        for n in range(1, 4):
            add_item(env, f"MLA100000000{n}")

        assert run(spacing_seconds=6, limit=2) == 2
        assert len(pending(env)) == 2


class TestResumable:
    def test_a_second_run_skips_what_is_already_queued(self, env) -> None:
        add_item(env, "MLA1000000001")
        run(spacing_seconds=6)
        add_item(env, "MLA1000000002")

        assert run(spacing_seconds=6) == 1
        assert sorted(mla for mla, _ in pending(env)) == ["MLA1000000001", "MLA1000000002"]

    def test_dry_run_counts_without_queueing(self, env) -> None:
        add_item(env, "MLA1000000001")

        assert run(spacing_seconds=6, dry_run=True) == 1
        assert pending(env) == []


class TestSpacingMustBePositive:
    @pytest.mark.parametrize("spacing", ["0", "-6"])
    def test_the_command_line_rejects_a_non_positive_spacing(self, spacing, capsys) -> None:
        with pytest.raises(SystemExit) as exit_info:
            main(["--spacing-seconds", spacing, "--dry-run"])

        assert exit_info.value.code == 2
        assert "--spacing-seconds must be greater than 0" in capsys.readouterr().err

    @pytest.mark.parametrize("spacing", [0, -6.0])
    def test_the_function_rejects_a_non_positive_spacing_before_reading_anything(self, spacing) -> None:
        with pytest.raises(ValueError, match="spacing_seconds must be greater than 0"):
            enqueue_never_consulted(None, NOW, spacing_seconds=spacing)

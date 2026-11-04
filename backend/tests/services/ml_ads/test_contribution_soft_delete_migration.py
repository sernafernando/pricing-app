"""ml-ads-aportes-robust S6 -- `deleted_at` / `deleted_by_id` on `ml_ads_campaign_contributions`.

Rows loaded before the columns stay live. Who and when go together: the database rejects one without the other.
Downgrading would bring every deleted aporte back into the figures, so it refuses while one exists. Runs in a
throwaway Postgres schema built by the earlier contribution migrations.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.services.ml_ads.test_account_level_migration import _script_directory
from tests.services.ml_ads.test_contributions_migration import (
    _CHANNEL_PATH,
    _INSERT,
    _SETTLEMENT_PATH,
    run_migration,
    throwaway_schema,
)

REVISION = "20261231_ml_ads_contribution_soft_delete"
_PATH = Path(__file__).resolve().parents[3] / "alembic" / "versions" / f"{REVISION}.py"
_ROWS = "SELECT id, deleted_at IS NULL, deleted_by_id FROM ml_ads_campaign_contributions ORDER BY id"
_MARK = "UPDATE ml_ads_campaign_contributions SET deleted_at = {at}, deleted_by_id = {by}"


def _rows_before_the_columns(eng) -> None:
    run_migration(eng, "upgrade")
    run_migration(eng, "upgrade", _SETTLEMENT_PATH)
    run_migration(eng, "upgrade", _CHANNEL_PATH)
    with eng.begin() as conn:
        conn.execute(text(_INSERT), {"kind": "percentage", "value": "30", "desde": "2026-10-01", "hasta": "2026-10-31"})
    run_migration(eng, "upgrade", _PATH)


def _columns(eng) -> set[str]:
    with eng.connect() as conn:
        return set(
            conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'ml_ads_campaign_contributions'"
                )
            ).scalars()
        )


def test_one_parent_and_an_ancestor_of_the_single_head() -> None:
    script = _script_directory()
    assert isinstance(script.get_revision(REVISION).down_revision, str)
    [head] = script.get_heads()
    assert REVISION in {r.revision for r in script.walk_revisions(base="base", head=head)}


@pytest.mark.postgres
def test_existing_rows_stay_live() -> None:
    with throwaway_schema(_rows_before_the_columns) as eng:
        with eng.connect() as conn:
            assert [tuple(r)[1:] for r in conn.execute(text(_ROWS))] == [(True, None)]


@pytest.mark.postgres
@pytest.mark.parametrize("at, by", [("now()", "NULL"), ("NULL", "7")], ids=["when-without-who", "who-without-when"])
def test_who_and_when_go_together(at, by) -> None:
    with throwaway_schema(_rows_before_the_columns) as eng:
        with pytest.raises(IntegrityError), eng.begin() as conn:
            conn.execute(text(_MARK.format(at=at, by=by)))


@pytest.mark.postgres
def test_a_row_is_marked_deleted_with_who_and_when() -> None:
    with throwaway_schema(_rows_before_the_columns) as eng:
        with eng.begin() as conn:
            conn.execute(text(_MARK.format(at="now()", by="7")))
        with eng.connect() as conn:
            assert [tuple(r)[1:] for r in conn.execute(text(_ROWS))] == [(False, 7)]


@pytest.mark.postgres
def test_downgrade_without_deleted_rows_drops_the_columns_and_keeps_the_rows() -> None:
    with throwaway_schema(_rows_before_the_columns) as eng:
        run_migration(eng, "downgrade", _PATH)
        assert not {"deleted_at", "deleted_by_id"} & _columns(eng)
        with eng.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM ml_ads_campaign_contributions")).scalar_one() == 1


@pytest.mark.postgres
def test_downgrade_refuses_while_a_deleted_row_exists_and_changes_nothing() -> None:
    with throwaway_schema(_rows_before_the_columns) as eng:
        with eng.begin() as conn:
            conn.execute(text(_MARK.format(at="now()", by="7")))
        with pytest.raises(RuntimeError, match="1 deleted contribution"):
            run_migration(eng, "downgrade", _PATH)
        assert {"deleted_at", "deleted_by_id"} <= _columns(eng)
        with eng.connect() as conn:
            assert [tuple(r)[1:] for r in conn.execute(text(_ROWS))] == [(False, 7)]

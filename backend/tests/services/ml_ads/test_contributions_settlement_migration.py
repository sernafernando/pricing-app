"""ml-ads-brand-contribution T1c -- `settlement` on `ml_ads_campaign_contributions` (S6).

A fixed amount says whether the brand pays it whole (`full`) or only up to what the campaign spent
(`refund_difference`); a percentage has none. Rows loaded before the column existed are backfilled
`refund_difference`. Runs in a throwaway Postgres schema built by the T1a migration.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.services.ml_ads.test_account_level_migration import _script_directory
from tests.services.ml_ads.test_contributions_migration import _INSERT, run_migration, throwaway_schema

REVISION = "20261116_ml_ads_contribution_settlement"
_PATH = Path(__file__).resolve().parents[3] / "alembic" / "versions" / f"{REVISION}.py"
_SETTLEMENTS = "SELECT kind, settlement FROM ml_ads_campaign_contributions ORDER BY kind"
_INSERT_SETTLED = _INSERT.replace("updated_by_id)", "updated_by_id, settlement)").replace("7, 7)", "7, 7, :settlement)")


def _rows_before_the_column(eng) -> None:
    run_migration(eng, "upgrade")
    with eng.begin() as conn:
        for kind, value in (("fixed_amount", "500000"), ("percentage", "30")):
            conn.execute(text(_INSERT), {"kind": kind, "value": value, "desde": "2026-10-01", "hasta": "2026-10-31"})
    run_migration(eng, "upgrade", _PATH)


def test_one_parent_and_an_ancestor_of_the_single_head() -> None:
    script = _script_directory()
    assert script.get_revision(REVISION).down_revision == "20261115_sell_in_bono_queue_alcance"
    [head] = script.get_heads()
    assert REVISION in {r.revision for r in script.walk_revisions(base="base", head=head)}


@pytest.mark.postgres
def test_existing_fixed_amounts_are_backfilled_and_downgrade_drops_the_column() -> None:
    with throwaway_schema(_rows_before_the_column) as eng:
        with eng.connect() as conn:
            assert [tuple(r) for r in conn.execute(text(_SETTLEMENTS))] == [
                ("fixed_amount", "refund_difference"),
                ("percentage", None),
            ]
        run_migration(eng, "downgrade", _PATH)
        with eng.connect() as conn:
            columns = conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema()")
            ).scalars()
            assert "settlement" not in set(columns)
            assert conn.execute(text("SELECT count(*) FROM ml_ads_campaign_contributions")).scalar_one() == 2


@pytest.mark.postgres
@pytest.mark.parametrize(
    "row",
    [
        {"kind": "fixed_amount", "settlement": None},
        {"kind": "fixed_amount", "settlement": "partial"},
        {"kind": "percentage", "settlement": "full"},
    ],
)
def test_the_database_rejects_a_settlement_that_does_not_fit_the_kind(row) -> None:
    with throwaway_schema(_rows_before_the_column) as eng:
        with pytest.raises(IntegrityError), eng.begin() as conn:
            conn.execute(text(_INSERT_SETTLED), {"value": "10", "desde": "2026-11-01", "hasta": "2026-11-30", **row})


@pytest.mark.postgres
@pytest.mark.parametrize("settlement", ["full", "refund_difference"])
def test_both_settlements_are_accepted_on_a_fixed_amount(settlement) -> None:
    with throwaway_schema(_rows_before_the_column) as eng:
        with eng.begin() as conn:
            conn.execute(
                text(_INSERT_SETTLED),
                {
                    "kind": "fixed_amount",
                    "value": "10",
                    "desde": "2026-11-01",
                    "hasta": "2026-11-30",
                    "settlement": settlement,
                },
            )

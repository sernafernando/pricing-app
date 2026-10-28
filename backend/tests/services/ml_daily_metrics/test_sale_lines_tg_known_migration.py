"""Audit A3 -- `ml_sale_lines.tg_known`: a stored line says whether its Total Gauss is known.

Before the column, `tg` = 0 meant both "Total Gauss not resolved" and "Total Gauss exactly 0", and the board read
every 0 as unknown. Lines stored before the column keep that meaning (`tg_known = tg <> 0`); the writer re-derives
the flag from the order's metrics on every rewrite, and the divergence check rewrites a line whose flag is stale.
Runs in a throwaway Postgres schema with a minimal `ml_sale_lines` (the columns the migration touches).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.services.ml_ads.test_account_level_migration import _script_directory
from tests.services.ml_ads.test_contributions_migration import run_migration, throwaway_schema

REVISION = "20261208_ml_sale_lines_tg_unknown"
PARENT = "20261211_sell_in_bono_tope"
_PATH = Path(__file__).resolve().parents[3] / "alembic" / "versions" / f"{REVISION}.py"


def _lines_before_the_column(eng) -> None:
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE ml_sale_lines (item_row_id INTEGER PRIMARY KEY, tg NUMERIC NOT NULL)"))
        conn.execute(text("INSERT INTO ml_sale_lines VALUES (1, 0), (2, 12.5), (3, -3), (4, 0.0001)"))
    run_migration(eng, "upgrade", _PATH)


def test_one_parent_and_an_ancestor_of_the_single_head() -> None:
    script = _script_directory()
    assert script.get_revision(REVISION).down_revision == PARENT
    [head] = script.get_heads()
    assert REVISION in {r.revision for r in script.walk_revisions(base="base", head=head)}


@pytest.mark.postgres
def test_existing_lines_keep_their_meaning_and_downgrade_drops_the_column() -> None:
    with throwaway_schema(_lines_before_the_column) as eng:
        with eng.connect() as conn:
            rows = conn.execute(text("SELECT item_row_id, tg_known FROM ml_sale_lines ORDER BY item_row_id")).all()
            # The board's rule before the column: a 0 is unknown, anything else is known.
            assert [tuple(r) for r in rows] == [(1, False), (2, True), (3, True), (4, True)]

        run_migration(eng, "downgrade", _PATH)
        with eng.connect() as conn:
            columns = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'ml_sale_lines'"
                )
            ).scalars()
            assert set(columns) == {"item_row_id", "tg"}
            assert conn.execute(text("SELECT count(*) FROM ml_sale_lines")).scalar_one() == 4


@pytest.mark.postgres
def test_a_line_written_without_the_flag_reads_as_unknown() -> None:
    # The deploy migrates before it restarts the drain: the old writer, which does not know the column, keeps
    # storing lines in between. Failing them would retry each order until it is parked; an unknown flag only keeps
    # the line out of sell in / sell out until the divergence check rewrites it.
    with throwaway_schema(_lines_before_the_column) as eng:
        with eng.begin() as conn:
            conn.execute(text("INSERT INTO ml_sale_lines (item_row_id, tg) VALUES (5, 12.5)"))
            flag = conn.execute(text("SELECT tg_known FROM ml_sale_lines WHERE item_row_id = 5")).scalar_one()
        assert flag is False


@pytest.mark.postgres
def test_the_flag_is_never_null() -> None:
    with throwaway_schema(_lines_before_the_column) as eng:
        with pytest.raises(IntegrityError), eng.begin() as conn:
            conn.execute(text("INSERT INTO ml_sale_lines (item_row_id, tg, tg_known) VALUES (5, 0, NULL)"))

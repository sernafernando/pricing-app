"""Migration `20261122_producto_stock_diario` (auditoria-stock-rotacion L1): the daily stock photo's table."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from tests.services.ml_ads.test_account_level_migration import _script_directory
from tests.services.ml_ads.test_contributions_migration import run_migration, throwaway_schema

REVISION = "20261122_producto_stock_diario"
_PATH = Path(__file__).resolve().parents[4] / "alembic" / "versions" / f"{REVISION}.py"


def test_one_parent_and_an_ancestor_of_the_single_head() -> None:
    script = _script_directory()
    assert script.get_revision(REVISION).down_revision == "20261121_ml_publicaciones_auditoria_stock_perm"
    [head] = script.get_heads()
    assert REVISION in {r.revision for r in script.walk_revisions(base="base", head=head)}


@pytest.mark.postgres
def test_one_row_per_product_and_day() -> None:
    with throwaway_schema(lambda eng: run_migration(eng, "upgrade", _PATH)) as eng:
        insert = text("INSERT INTO producto_stock_diario VALUES ('2026-11-18', 100, 5, 2)")
        with eng.begin() as conn:
            conn.execute(insert)
        with pytest.raises(IntegrityError), eng.begin() as conn:
            conn.execute(insert)


@pytest.mark.postgres
def test_downgrade_drops_the_table() -> None:
    def build(eng) -> None:
        run_migration(eng, "upgrade", _PATH)
        run_migration(eng, "downgrade", _PATH)

    with throwaway_schema(build) as eng:
        assert "producto_stock_diario" not in inspect(eng).get_table_names()

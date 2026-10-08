"""P8a.T4: the statements `scripts/measure_pubml_p8a.py` picks its publications with, run on the real store schema.

The script is run once, on production data, by a person: a statement that fails there costs a whole round trip, so
each is exercised here against the tables the migrations build.
"""

# ruff: noqa: F811 -- the fixture is imported and used by name

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_pubml_p8a.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("measure_pubml_p8a_pg", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves its annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def pick(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


def test_each_statement_picks_the_publication_it_is_named_for(script, mlpub_pg) -> None:
    with mlpub_pg.begin() as conn:
        seed.add_item(conn, "MLA1", last_trigger_received_at=seed.hours_ago(1))  # many variations
        for variation in (1, 2, 3):
            seed.add_variation(conn, "MLA1", variation)
        seed.add_item(conn, "MLA2", last_trigger_received_at=seed.hours_ago(2))  # two variations (fewer)
        for variation in (1, 2):
            seed.add_variation(conn, "MLA2", variation)
        seed.add_item(conn, "MLA3", logistic_type="fulfillment", user_product_id="MLAU3")  # Full + replenishment
        seed.add_replenishment(conn, "MLAU3", units_30d=1)
        seed.add_item(conn, "MLA4", logistic_type="fulfillment", user_product_id="MLAU4", gone_at=seed.NOW)
        seed.add_replenishment(conn, "MLAU4", units_30d=1)  # gone: never picked
        seed.add_item(conn, "MLA5", last_trigger_received_at=seed.hours_ago(3))  # linked, no variations
        seed.add_link(conn, "MLA5", 70)
        seed.add_item(conn, "MLA6", last_trigger_received_at=seed.hours_ago(1))  # no variations but not linked
    assert pick(mlpub_pg, script.BIG_SQL) == "MLA1"
    assert pick(mlpub_pg, script.FULL_SQL) == "MLA3"
    assert pick(mlpub_pg, script.PLAIN_SQL) == "MLA5"


def test_an_empty_store_picks_nothing(script, mlpub_pg) -> None:
    assert [pick(mlpub_pg, sql) for sql in (script.BIG_SQL, script.FULL_SQL, script.PLAIN_SQL)] == [None] * 3

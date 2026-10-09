"""P9b.T3: the brand the measurement script picks is the one with the most linked publications, on real Postgres."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_pubml_p9b.py"


def _script():
    spec = importlib.util.spec_from_file_location("measure_pubml_p9b", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_busiest_brand_ties_break_by_codepoint(env) -> None:  # noqa: F811
    with env.begin() as conn:
        seed.add_product(conn, 1, "A", "a", marca="b-brand", categoria="c")
        seed.add_product(conn, 2, "B", "b", marca="B-brand", categoria="c")
        seed.add_product(conn, 3, "C", "c", marca="Busy", categoria="c")
        for n, product in enumerate((1, 2, 3, 3), start=1):
            seed.add_item(conn, f"MLA{n}")
            seed.add_link(conn, f"MLA{n}", product)
        assert conn.execute(text(_script().BUSIEST_BRAND_SQL)).scalar() == "Busy"
        conn.execute(text("DELETE FROM ml_item_product_links WHERE item_id = 'MLA4'"))
        assert conn.execute(text(_script().BUSIEST_BRAND_SQL)).scalar() == "B-brand"  # 1 each: "B" < "b" in "C"

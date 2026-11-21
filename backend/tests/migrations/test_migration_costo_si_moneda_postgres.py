"""Migration `20261126_costo_si_moneda`: `costo_si_pasos.moneda` (owner L18), 'USD' for every row stored before it
(all were computed in USD); the downgrade drops it."""

from __future__ import annotations

import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from tests.migrations.test_migration_costo_si_drop_full_postgres import _step
from tests.migrations.test_migration_costo_si_postgres import _NUEVAS
from tests.services.costo_si import _world as w
from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261126_costo_si_moneda"


@pytest.fixture
def migrada() -> Iterator[Engine]:
    tablas = [t for t in w.TABLES if t.name not in _NUEVAS]
    with throwaway_schema("costo_si_moneda_mig", tablas, w.STUBS) as engine:
        for previa in ("20261125_costo_si", "20261125_costo_si_drop_full", "20261125_costo_si_bono_unidad"):
            _step(engine, previa, "upgrade")
        yield engine


def test_it_chains_on_bono_unidad_and_the_graph_has_one_head() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_revision(_REVISION).down_revision == "20261125_costo_si_bono_unidad"
    # Not `get_heads() == [this]`: later revisions chain on top.
    (head,) = script.get_heads()
    assert _REVISION in {r.revision for r in script.iterate_revisions(head, "base")}


def _columnas(engine: Engine) -> set:
    return {
        r[0]
        for r in w.rows(
            engine,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'costo_si_pasos'",
        )
    }


@pytest.mark.postgres
def test_upgrade_marks_the_stored_rows_usd_and_downgrade_drops_the_column(migrada: Engine) -> None:
    w.run(
        migrada,
        "INSERT INTO costo_si_pasos (item_id, orden, tipo, fecha, cantidad, stock_antes, stock_base, stock_despues,"
        " promedio_usd) VALUES (5401, 0, 'inicio', '2026-10-01', 0, 0, 0, 0, 25)",
    )

    _step(migrada, _REVISION, "upgrade")
    assert w.rows(migrada, "SELECT moneda FROM costo_si_pasos") == [("USD",)]

    _step(migrada, _REVISION, "downgrade")
    assert "moneda" not in _columnas(migrada)

"""Migration `20261125_costo_si_bono_unidad`: `costo_si_encolar_bono` also queues the products of a per-unit sell-in
line (L4.2); the downgrade puts back the %-only body."""

from __future__ import annotations

import os
from datetime import date
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from app.services.costo_si import queue
from tests.migrations.test_migration_costo_si_drop_full_postgres import _step
from tests.migrations.test_migration_costo_si_postgres import _NUEVAS
from tests.services.costo_si import _world as w
from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261125_costo_si_bono_unidad"


@pytest.fixture
def migrada() -> Iterator[Engine]:
    tablas = [t for t in w.TABLES if t.name not in _NUEVAS]
    with throwaway_schema("costo_si_bono_unidad", tablas, w.STUBS) as engine:
        _step(engine, "20261125_costo_si", "upgrade")
        _step(engine, "20261125_costo_si_drop_full", "upgrade")
        yield engine


def test_it_chains_on_drop_full_and_the_graph_has_one_head() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_revision(_REVISION).down_revision == "20261125_costo_si_drop_full"
    # Not `get_heads() == [this]`: 20261126_costo_si_moneda (and later revisions) chain on top.
    (head,) = script.get_heads()
    assert _REVISION in {r.revision for r in script.iterate_revisions(head, "base")}


@pytest.mark.postgres
def test_upgrade_queues_a_per_unit_line_edit_and_downgrade_does_not(migrada: Engine) -> None:
    """Loading the line queues its models through `sell_in_bono_items` already; editing the line itself (its amount)
    goes through `costo_si_encolar_bono`, which only queued % lines before this revision."""
    w.producto(migrada, 5201)
    tactical = w.tactical(migrada, date(2026, 10, 5), date(2026, 12, 31))
    bono = w.bono_modelos(
        migrada, [5201], "por_unidad", "170", date(2026, 10, 5), date(2026, 12, 31), moneda="USD", tactical_id=tactical
    )

    def editar(monto: int) -> list:
        w.run(migrada, "DELETE FROM costo_si_dirty")
        w.run(migrada, "UPDATE sell_in_bonos_marca SET monto_unit = :m WHERE id = :b", m=monto, b=bono)
        return w.encolados(migrada)

    assert editar(180) == []  # as 20261125_costo_si left it: % lines only

    _step(migrada, _REVISION, "upgrade")
    assert editar(190) == [(5201, date(2026, 10, 5))]

    _step(migrada, _REVISION, "downgrade")
    assert editar(200) == []


def test_the_frozen_copy_is_the_live_bono_function() -> None:
    assert queue._BONO in queue.UPGRADE_SQL
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "m", os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.BONO_SQL == queue._BONO

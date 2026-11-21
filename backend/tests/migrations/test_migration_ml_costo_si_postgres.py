"""Migration `20261127_ml_costo_si` (sell-in-costo-si T3 PR 7): the ML re-freeze queue and the backups of re-frozen
rows; it rewrites nothing that exists, and the downgrade drops both tables."""

from __future__ import annotations

import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from tests.migrations.test_migration_costo_si_drop_full_postgres import _step
from tests.services.costo_si import _world as w
from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261127_ml_costo_si"
_NUEVAS = {"ml_costo_si_dirty", "ml_order_item_costos_backups"}


def test_it_chains_on_costo_si_moneda_and_the_graph_has_one_head() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_revision(_REVISION).down_revision == "20261126_costo_si_moneda"
    (head,) = script.get_heads()
    assert _REVISION in {r.revision for r in script.iterate_revisions(head, "base")}


@pytest.fixture
def antes() -> Iterator[Engine]:
    with throwaway_schema("ml_costo_si_mig", [t for t in w.TABLES if t.name not in _NUEVAS], w.STUBS) as engine:
        yield engine


def _tablas(engine: Engine) -> set:
    return {
        r[0]
        for r in w.rows(
            engine, "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
        )
    }


@pytest.mark.postgres
def test_upgrade_creates_the_queue_and_the_backups_and_downgrade_drops_them(antes: Engine) -> None:
    _step(antes, _REVISION, "upgrade")
    assert _NUEVAS <= _tablas(antes)
    w.run(antes, "INSERT INTO ml_costo_si_dirty (producto_item_id) VALUES (1)")
    assert w.rows(antes, "SELECT producto_item_id, desde, attempts FROM ml_costo_si_dirty") == [(1, None, 0)]

    _step(antes, _REVISION, "downgrade")
    assert not (_NUEVAS & _tablas(antes))

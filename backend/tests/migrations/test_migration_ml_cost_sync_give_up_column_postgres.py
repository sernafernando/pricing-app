"""Migration `20261204_ml_cost_sync_give_up_column` (remove-ml-divergences D2): the cost-sync give-up counter moves
from `ml_ops_divergence` rows (`order_id=0`, `field='cost_sync:<shipment_id>'`, count in `ml_value`) to
`ml_shipments_ops.cost_sync_attempts`, keeping every existing count. Downgrade copies them back.

Runs the migration itself on a throwaway schema holding bare stand-ins of both tables (production's columns).
"""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from app.services.ml_orders_ingestion.backfill_payments_costs_service import MAX_COST_SYNC_ATTEMPTS
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261204_ml_cost_sync_give_up_column"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_STUBS = [
    "CREATE TABLE ml_shipments_ops (shipment_id BIGINT PRIMARY KEY, order_id BIGINT, costs_synced_at TIMESTAMPTZ)",
    "INSERT INTO ml_shipments_ops (shipment_id) VALUES (700), (701), (702), (703), (704)",
    """CREATE TABLE ml_ops_divergence (
        id SERIAL PRIMARY KEY,
        order_id BIGINT NOT NULL,
        detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        kind VARCHAR(30) NOT NULL,
        field VARCHAR(40),
        ml_value TEXT,
        gbp_value TEXT,
        state VARCHAR(20) NOT NULL DEFAULT 'open',
        assigned_to_id INTEGER,
        note TEXT,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_ml_ops_divergence_order_kind_field UNIQUE NULLS NOT DISTINCT (order_id, kind, field)
    )""",
    """INSERT INTO ml_ops_divergence (order_id, kind, field, ml_value) VALUES
        (0, 'unknown', 'cost_sync:700', '5'),
        (0, 'unknown', 'cost_sync:701', '2'),
        (0, 'unknown', 'cost_sync:702', '9'),
        (0, 'unknown', 'cost_sync:703', 'garbage'),
        (0, 'unknown', 'cost_sync:999', '3'),
        (704, 'unknown', 'activity_unresolved', NULL)""",
]


def _module():
    spec = importlib.util.spec_from_file_location("ml_cost_sync_give_up_column_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _attempts(engine: Engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT shipment_id, cost_sync_attempts FROM ml_shipments_ops ORDER BY 1"))
        return {shipment_id: attempts for shipment_id, attempts in rows}


def _divergence(engine: Engine) -> list:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT order_id, field, ml_value FROM ml_ops_divergence ORDER BY order_id, field"))
        return [tuple(r) for r in rows]


@pytest.fixture()
def engine() -> Iterator[Engine]:
    with throwaway_schema("ml_cost_sync_mig", [], _STUBS) as eng:
        yield eng


def test_the_revision_chains_on_the_current_head() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config).get_revision(_REVISION)
    assert script.down_revision == "20261203_etiquetas_logistica_historial"
    assert _module().MAX_ATTEMPTS == MAX_COST_SYNC_ATTEMPTS


def test_upgrade_carries_every_counter_over_to_its_shipment(engine) -> None:
    before = _divergence(engine)

    _step(engine, "upgrade")

    # 702 is clamped like the code clamps; a non-numeric count and a shipment we do not hold are skipped.
    assert _attempts(engine) == {700: 5, 701: 2, 702: MAX_COST_SYNC_ATTEMPTS, 703: 0, 704: 0}
    # The legacy rows stay: a later revision drops the table.
    assert _divergence(engine) == before


def test_a_new_shipment_starts_at_zero(engine) -> None:
    _step(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO ml_shipments_ops (shipment_id) VALUES (800)"))

    assert _attempts(engine)[800] == 0


def test_downgrade_copies_the_counters_back_and_drops_the_column(engine) -> None:
    _step(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(text("UPDATE ml_shipments_ops SET cost_sync_attempts = 3 WHERE shipment_id = 701"))
        conn.execute(text("UPDATE ml_shipments_ops SET cost_sync_attempts = 1 WHERE shipment_id = 704"))
        # 700 settled after the upgrade: its pre-upgrade legacy row ('5') must not come back as "given up".
        conn.execute(text("UPDATE ml_shipments_ops SET cost_sync_attempts = 0 WHERE shipment_id = 700"))

    _step(engine, "downgrade")

    with engine.connect() as conn:
        columns = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'ml_shipments_ops'"
            )
        ).scalars()
        assert "cost_sync_attempts" not in set(columns)
    rows = {(order_id, field): value for order_id, field, value in _divergence(engine)}
    assert (0, "cost_sync:700") not in rows
    assert rows[(0, "cost_sync:701")] == "3"
    assert rows[(0, "cost_sync:704")] == "1"
    assert rows[(704, "activity_unresolved")] is None


def test_the_lock_timeout_is_restored_after_each_step(engine) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            conn.execute(text("SET LOCAL lock_timeout = '42s'"))
            _module().upgrade()
            assert conn.execute(text("SHOW lock_timeout")).scalar() == "42s"
            _module().downgrade()
            assert conn.execute(text("SHOW lock_timeout")).scalar() == "42s"

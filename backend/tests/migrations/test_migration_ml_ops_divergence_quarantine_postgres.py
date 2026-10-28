"""Migration `20261205_ml_ops_divergence_quarantine` (remove-ml-divergences D2b): the activity receiver's unresolved
orders move from `ml_ops_divergence` rows (`kind='unknown'`, `field='activity_unresolved'`) to
`ml_orders_ops_cuarentena` rows with no `raw_order`, keeping every open debt. Downgrade copies them back.

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

from app.services.ml_orders_ingestion.activity_receiver_service import UNRESOLVED_ERROR
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261205_ml_ops_divergence_quarantine"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_STUBS = [
    """CREATE TABLE ml_orders_ops_cuarentena (
        order_id BIGINT PRIMARY KEY,
        raw_order JSONB NOT NULL,
        error TEXT NOT NULL,
        intentos INTEGER NOT NULL DEFAULT 1,
        primera_falla_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        ultimo_intento_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """INSERT INTO ml_orders_ops_cuarentena (order_id, raw_order, error, intentos) VALUES
        (14, '{"id": 14}', '[permanent] boom', 3),
        (20, '{"id": 20}', '[transient] pool', 2)""",
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
    """INSERT INTO ml_ops_divergence (order_id, kind, field, ml_value, state, detected_at) VALUES
        (10, 'unknown', 'activity_unresolved', NULL, 'open', '2026-10-01 10:00+00'),
        (11, 'unknown', 'activity_unresolved', NULL, 'acknowledged', '2026-10-02 10:00+00'),
        (12, 'unknown', 'activity_unresolved', NULL, 'ignored', '2026-10-03 10:00+00'),
        (13, 'unknown', 'activity_unresolved', NULL, 'resolved', '2026-10-04 10:00+00'),
        (14, 'unknown', 'activity_unresolved', NULL, 'open', '2026-10-05 10:00+00'),
        (0, 'unknown', 'cost_sync:700', '5', 'open', '2026-10-06 10:00+00'),
        (15, 'out_of_window_update', NULL, NULL, 'open', '2026-10-07 10:00+00'),
        (16, 'unknown', 'other_field', NULL, 'open', '2026-10-08 10:00+00')""",
]


def _module():
    spec = importlib.util.spec_from_file_location("ml_ops_divergence_quarantine_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _quarantine(engine: Engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT order_id, raw_order, error, intentos, ultimo_intento_at > now() - interval '1 hour', "
                "to_char(primera_falla_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') FROM ml_orders_ops_cuarentena ORDER BY 1"
            )
        )
        return {row[0]: tuple(row[1:]) for row in rows}


def _divergence(engine: Engine) -> list:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT order_id, kind, field, state, to_char(detected_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') "
                "FROM ml_ops_divergence ORDER BY order_id, kind, field"
            )
        )
        return [tuple(r) for r in rows]


def _raw_order_nullable(engine: Engine) -> bool:
    with engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns WHERE table_schema = current_schema() "
                    "AND table_name = 'ml_orders_ops_cuarentena' AND column_name = 'raw_order'"
                )
            ).scalar()
            == "YES"
        )


@pytest.fixture()
def engine() -> Iterator[Engine]:
    with throwaway_schema("ml_div_quarantine_mig", [], _STUBS) as eng:
        yield eng


def test_the_revision_chains_on_the_current_head() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config).get_revision(_REVISION)
    assert script.down_revision == "20261204_ml_cost_sync_give_up_column"
    assert _module().UNRESOLVED_ERROR == UNRESOLVED_ERROR


def test_upgrade_carries_every_open_debt_over_to_the_quarantine(engine) -> None:
    before = _divergence(engine)

    _step(engine, "upgrade")

    assert _raw_order_nullable(engine)
    assert _quarantine(engine) == {
        # Open and acknowledged debts become rows with no payload, first failed when the debt was detected and last
        # tried now: the replay of a worker still on the old code (deploy window) does not see them for its backoff.
        10: (None, UNRESOLVED_ERROR, 1, True, "2026-10-01"),
        11: (None, UNRESOLVED_ERROR, 1, True, "2026-10-02"),
        # An order quarantined with its payload keeps its row.
        14: ({"id": 14}, "[permanent] boom", 3, True, _quarantine_day(engine, 14)),
        20: ({"id": 20}, "[transient] pool", 2, True, _quarantine_day(engine, 20)),
    }
    # Ignored and resolved debts, and every other row, are not copied; the legacy rows stay (a later revision drops
    # the table).
    assert _divergence(engine) == before


def _quarantine_day(engine: Engine, order_id: int) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT to_char(primera_falla_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') FROM ml_orders_ops_cuarentena "
                "WHERE order_id = :id"
            ),
            {"id": order_id},
        ).scalar()


def test_downgrade_copies_the_debts_back_and_restores_not_null(engine) -> None:
    _step(engine, "upgrade")
    with engine.begin() as conn:
        # 10 landed after the upgrade: its pre-upgrade legacy row must not come back.
        conn.execute(text("DELETE FROM ml_orders_ops_cuarentena WHERE order_id = 10"))
        # 31 was re-quarantined by the old replay during the deploy window: JSON null, still no payload.
        conn.execute(
            text(
                "INSERT INTO ml_orders_ops_cuarentena (order_id, raw_order, error, primera_falla_at, ultimo_intento_at) "
                "VALUES (31, 'null'::jsonb, '[permanent] mapping error on retry', '2026-10-22 10:00+00', "
                "'2026-10-22 10:00+00')"
            )
        )
        # New misses after the upgrade: 30 is new, 12 has an ignored legacy row.
        conn.execute(
            text(
                "INSERT INTO ml_orders_ops_cuarentena (order_id, raw_order, error, primera_falla_at, ultimo_intento_at) "
                "VALUES (30, NULL, :e, '2026-10-20 10:00+00', '2026-10-20 10:00+00'), "
                "(12, NULL, :e, '2026-10-21 10:00+00', '2026-10-21 10:00+00')"
            ),
            {"e": UNRESOLVED_ERROR},
        )

    _step(engine, "downgrade")

    assert not _raw_order_nullable(engine)
    assert sorted(_quarantine(engine)) == [14, 20]
    assert _divergence(engine) == [
        (0, "unknown", "cost_sync:700", "open", "2026-10-06"),
        (11, "unknown", "activity_unresolved", "open", "2026-10-02"),
        (12, "unknown", "activity_unresolved", "ignored", "2026-10-21"),
        (13, "unknown", "activity_unresolved", "resolved", "2026-10-04"),
        # Quarantined with its payload: its debt was never copied, so it is left as it was.
        (14, "unknown", "activity_unresolved", "open", "2026-10-05"),
        (15, "out_of_window_update", None, "open", "2026-10-07"),
        (16, "unknown", "other_field", "open", "2026-10-08"),
        (30, "unknown", "activity_unresolved", "open", "2026-10-20"),
        (31, "unknown", "activity_unresolved", "open", "2026-10-22"),
    ]


def test_the_lock_timeout_is_restored_after_each_step(engine) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            conn.execute(text("SET LOCAL lock_timeout = '42s'"))
            _module().upgrade()
            assert conn.execute(text("SHOW lock_timeout")).scalar() == "42s"
            _module().downgrade()
            assert conn.execute(text("SHOW lock_timeout")).scalar() == "42s"

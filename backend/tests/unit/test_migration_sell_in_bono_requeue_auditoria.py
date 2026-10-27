"""Migration `20261202_sell_in_bono_requeue_auditoria`: puts back the bonus keys the `tipoaccion` audit error
parked, and only those."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

from tests.models import test_sell_in_schema_postgres as base

pytestmark = pytest.mark.postgres

_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261202_sell_in_bono_requeue_auditoria.py"
_QUEUE = """
CREATE TABLE sell_in_bono_dirty (
    tipo TEXT NOT NULL, ref BIGINT NOT NULL,
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now(), attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
    PRIMARY KEY (tipo, ref)
)
"""


def _build(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(_QUEUE))
        conn.execute(
            text(
                "INSERT INTO sell_in_bono_dirty (tipo, ref, enqueued_at, attempts, last_error) VALUES "
                "('pedido', 278, now() - interval '1 day', 5, 'ProgrammingError: no existe el tipo «tipoaccion»'), "
                "('bono', 1, now() - interval '1 day', 5, 'no BNA USD rate on 2026-10-22')"
            )
        )


def test_it_requeues_only_the_keys_parked_by_the_audit_error() -> None:
    with base._throwaway_schema("si_bono_requeue", _build) as engine:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with ctx.begin_transaction(), Operations.context(ctx):
                base._load_migration(_PATH).upgrade()
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT tipo, ref, attempts, last_error, enqueued_at > now() - interval '1 hour' "
                    "FROM sell_in_bono_dirty ORDER BY tipo"
                )
            ).all()

    assert [tuple(r) for r in rows] == [
        ("bono", 1, 5, "no BNA USD rate on 2026-10-22", False),
        ("pedido", 278, 0, None, True),
    ]

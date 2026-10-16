"""The divergence check also covers the stored TP-Link line shares
(`tg_tp`/`mtg_tp`/`mcosto_tp`, metricas-ml-tplink-mode P3), but only for orders
stored at the formula version that introduced them: lines stored before it
carry NULL there, and bringing those up to date is reconcile's job (the version
bump), not a divergence.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.services.order_metrics.store import recompute_order_metrics
from app.workers.context import WorkerContext
from app.workers.handlers.order_metrics import divergence, drain
from tests.workers.handlers.test_order_metrics_divergence import (  # noqa: F401  (fixture re-export)
    _far_deadline,
    _order_metrics_db_session,
    _seed_sold_order,
)

_SET_TP_COST = (
    "UPDATE ml_order_item_costos SET costo_tp_origen = 40, costo_tp_moneda = 'ARS', costo_tp_unitario_ars = 40, "
    "costo_tp_fuente = 'lista8_ingesta', costo_tp_at = now() WHERE order_id = :oid"
)


# What resolves Total Gauss for `_seed_sold_order`'s order (2 x 100): a payment
# whose net received reconciles with the items, and a "% de varios" rate. Total
# TP needs Total Gauss: without it the TP shares are NULL (unknown), and a drift
# could not change their value.
_RESOLVE_GAUSS = (
    "UPDATE ml_payments_ops SET net_received_amount = 200 WHERE order_id = :oid",
    "INSERT INTO ml_venta_varios_pct (porcentaje, fecha_desde) "
    "SELECT 0, DATE '2020-01-01' WHERE NOT EXISTS (SELECT 1 FROM ml_venta_varios_pct)",
)


def _seed_with_tp(engine, order_id: int) -> None:
    """A sold order with a resolved Total Gauss whose item has a TP cost, stored
    by the real writer at the current formula version: its lines carry non-NULL
    TP shares."""
    _seed_sold_order(engine, order_id)
    with engine.connect() as conn:
        for statement in (_SET_TP_COST, *_RESOLVE_GAUSS):
            conn.execute(text(statement), {"oid": order_id})
        conn.execute(text("DELETE FROM ml_order_metrics_dirty"))
        conn.commit()
    with sessionmaker(bind=engine)() as session:
        recompute_order_metrics(session, [order_id])
        session.commit()


def _tg_tp(engine, order_id: int):
    with engine.connect() as conn:
        return conn.execute(text("SELECT tg_tp FROM ml_sale_lines WHERE order_id = :oid"), {"oid": order_id}).scalar()


def _gauss_status(engine, order_id: int):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT gauss_status FROM ml_order_metrics WHERE order_id = :oid"), {"oid": order_id}
        ).scalar()


def _queued(engine, order_id: int):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT reason FROM ml_order_metrics_dirty WHERE order_id = :oid"), {"oid": order_id}
        ).scalar()


@pytest.mark.postgres
@pytest.mark.usefixtures("_order_metrics_db_session")
class TestTpLineDivergence:
    @pytest.fixture(autouse=True)
    def _seller(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "ML_USER_ID", 999)

    def _ctx(self) -> WorkerContext:
        return WorkerContext(deadline=_far_deadline(), worker_name="w")

    def test_a_drifted_tp_share_is_flagged_and_repaired(self, pg_order_metrics_divergence_engine) -> None:
        engine = pg_order_metrics_divergence_engine
        _seed_with_tp(engine, 620001)
        status, good = _gauss_status(engine, 620001), _tg_tp(engine, 620001)
        assert status == "ok" and good is not None
        with engine.connect() as conn:
            conn.execute(text("UPDATE ml_sale_lines SET tg_tp = tg_tp + 1 WHERE order_id = 620001"))
            conn.commit()

        result = divergence.run(self._ctx())

        assert result.detail["lines_divergent_count"] == 1
        assert _queued(engine, 620001) == "divergence"

        drain.run(self._ctx())

        assert _queued(engine, 620001) is None
        assert _tg_tp(engine, 620001) == good

    def test_lines_stored_before_the_tp_version_are_not_flagged(self, pg_order_metrics_divergence_engine) -> None:
        engine = pg_order_metrics_divergence_engine
        _seed_with_tp(engine, 620002)
        # What a row stored at version 6 looks like after the migration: the
        # metrics carry an older version and the lines have NULL TP shares.
        with engine.connect() as conn:
            conn.execute(text("UPDATE ml_order_metrics SET formula_version = 6 WHERE order_id = 620002"))
            conn.execute(
                text("UPDATE ml_sale_lines SET tg_tp = NULL, mtg_tp = NULL, mcosto_tp = NULL WHERE order_id = 620002")
            )
            conn.commit()

        result = divergence.run(self._ctx())

        assert result.detail["lines_divergent_count"] == 0

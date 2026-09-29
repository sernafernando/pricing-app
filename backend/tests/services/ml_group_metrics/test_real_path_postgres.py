"""The group record as the REAL worker path produces it (ventas-ml-rediseno PR20).

WHY THIS FILE EXISTS: every other test of `recompute_group_metrics` calls it
directly, or through `recompute_order_metrics`, with no dirty row in the
picture. The production path is `order_metrics.queue.fenced_store`, and there
the order's dirty row is STILL PRESENT while `store_order_metrics` runs -- it
is only deleted afterwards, once the fence check has passed.

That ordering matters, because the group hook inside `store_order_metrics`
asks `metrics_state_for_orders` what state its members are in, and a member
with a dirty row answers `'recalculating'`. So the group of a perfectly
resolved order resolved to `'unresolved'` for the only caller that runs in
production, while every test saw `'ok'`.

Postgres-only: `fenced_store` is built on `FOR UPDATE` and claim-token
fencing, which SQLite's single-writer model cannot reproduce.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.services.order_metrics.queue import claim_dirty, fenced_store
from app.services.order_metrics.types import GaussStatus, OrderMetrics


def _metrics(order_id: int) -> OrderMetrics:
    return OrderMetrics(
        order_id=order_id,
        neto=Decimal("100.00"),
        neto_sin_iva=Decimal("82.64"),
        iva_reconcilia=True,
        costo_mercaderia=Decimal("50.00"),
        total_gauss=Decimal("40.00"),
        markup_pct=Decimal("80.00"),
        gauss_status=GaussStatus.OK,
        provisional_falta=None,
        unresolved_reason=None,
        formula_version=1,
        computed_at=datetime.now(timezone.utc),
        lineas=[],
    )


def _insert_order(conn, order_id: int, pack_id: int | None = None) -> None:
    conn.execute(
        text(
            "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created, pack_id) "
            "VALUES (:order_id, 999, 'paid', now(), now(), :pack_id) ON CONFLICT (order_id) DO NOTHING"
        ),
        {"order_id": order_id, "pack_id": pack_id},
    )


def _insert_dirty(conn, order_id: int) -> None:
    conn.execute(
        text(
            "INSERT INTO ml_order_metrics_dirty (order_id, version, reason, attempts, suspect) "
            "VALUES (:order_id, 1, 'input_write', 0, false) ON CONFLICT (order_id) DO NOTHING"
        ),
        {"order_id": order_id},
    )


@pytest.fixture()
def worker_db(monkeypatch, pg_order_metrics_engine):
    """Points `get_background_db()` -- what `queue.py` uses exclusively -- at
    the Postgres test engine, and clears every table these tests touch,
    `ml_group_metrics` included (the sibling queue fixture predates it)."""
    session_factory = sessionmaker(bind=pg_order_metrics_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.core.database.SessionLocal", session_factory)
    yield
    with pg_order_metrics_engine.connect() as conn:
        conn.execute(text("DELETE FROM ml_group_metrics"))
        conn.execute(text("DELETE FROM ml_venta_deducciones"))
        conn.execute(text("DELETE FROM ml_order_metrics"))
        conn.execute(text("DELETE FROM ml_order_metrics_dirty"))
        conn.execute(text("DELETE FROM ml_orders_ops"))
        conn.commit()


@pytest.mark.postgres
class TestGroupRecordThroughTheWorkerPath:
    def test_a_standalone_order_stored_by_the_worker_gets_a_resolved_group(
        self, worker_db, pg_order_metrics_engine
    ) -> None:
        """The order resolved fine, so its group must too. If the group hook
        counts the order's own still-present dirty row as "recalculating",
        this reads `unresolved` with every amount null -- which is what the
        detail panel and the KPI would then show forever."""
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 810001)
            _insert_dirty(conn, 810001)
            conn.commit()
        [claim] = claim_dirty(limit=10, lease=timedelta(seconds=120), worker_id="w")

        fenced_store([claim], {810001: _metrics(810001)})

        with pg_order_metrics_engine.connect() as conn:
            fila = conn.execute(
                text("SELECT gauss_status, total_gauss FROM ml_group_metrics WHERE group_key = 'o:810001'")
            ).fetchone()
        assert fila is not None, "el camino real tiene que dejar la fila del grupo"
        assert fila.gauss_status == "ok"
        assert fila.total_gauss == Decimal("40.00")

    def test_a_pack_whose_other_member_is_still_dirty_stays_unresolved(
        self, worker_db, pg_order_metrics_engine
    ) -> None:
        """La contracara, y la que hace que la de arriba signifique algo: el
        hook no puede ignorar la cola entera. Un hermano que TODAVÍA no se
        computó deja al grupo sin resolver, porque la suma es todo o nada."""
        with pg_order_metrics_engine.connect() as conn:
            _insert_order(conn, 810010, pack_id=8100)
            _insert_order(conn, 810011, pack_id=8100)
            _insert_dirty(conn, 810010)
            _insert_dirty(conn, 810011)
            conn.commit()
        claims = claim_dirty(limit=10, lease=timedelta(seconds=120), worker_id="w")
        solo_uno = [c for c in claims if c.order_id == 810010]

        fenced_store(solo_uno, {810010: _metrics(810010)})

        with pg_order_metrics_engine.connect() as conn:
            fila = conn.execute(
                text("SELECT gauss_status, total_gauss FROM ml_group_metrics WHERE group_key = 'p:8100'")
            ).fetchone()
        assert fila is not None
        assert fila.gauss_status == "unresolved"
        assert fila.total_gauss is None

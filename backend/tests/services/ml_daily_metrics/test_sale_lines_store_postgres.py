"""`ml_sale_lines` (the persisted per-sold-line base): written by
`store_order_metrics` in the transaction that stores the order's metrics, with
exactly what `sales.sale_lines` derives -- the board's single definition of the
day, product, cancellation and money rules.

Real Postgres: the writer is PostgreSQL-only, like the queue it hangs from.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.ml_sale_line import MlSaleLine
from app.services.ml_daily_metrics.sales import sale_lines
from app.services.order_metrics.sale_lines_store import COLUMNS, store_sale_lines
from app.services.order_metrics.store import store_order_metrics
from app.services.order_metrics.types import GaussStatus, OrderMetrics
from tests.services.ml_daily_metrics.seed import Line, seed_order

DAY = datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def _metrics(order_id: int, tg="50.00", costo="30.00") -> OrderMetrics:
    return OrderMetrics(
        order_id=order_id,
        neto=Decimal("100.00"),
        neto_sin_iva=Decimal("82.64"),
        iva_reconcilia=True,
        costo_mercaderia=Decimal(costo),
        total_gauss=Decimal(tg),
        markup_pct=Decimal("166.67"),
        gauss_status=GaussStatus.OK,
        provisional_falta=None,
        unresolved_reason=None,
        formula_version=5,
        computed_at=datetime.now(timezone.utc),
    )


def _stored(db):
    rows = db.execute(
        select(*(MlSaleLine.__table__.c[name] for name in COLUMNS)).order_by(MlSaleLine.item_row_id)
    ).all()
    return [tuple(row) for row in rows]


def _live(db):
    lines = sale_lines(sqlite=False, queue=False, keyed=True)
    return [
        tuple(row) for row in db.execute(select(*(lines.c[name] for name in COLUMNS)).order_by(lines.c.item_row_id))
    ]


def _seed_world(db):
    """A pack of two orders (one with two items), a standalone order, an order
    cancelled without coverage, one covered by ML, and one never accredited."""
    two = [Line(100, "MLA1", 2, Decimal("100")), Line(101, "MLA2", 1, Decimal("50"), unit_cost=Decimal("20"))]
    seed_order(db, 1, DAY, two, tg="60", costo="40", pack_id=900)
    seed_order(db, 2, DAY, [Line(102, "MLA3", 3, Decimal("10"))], tg="9", costo="6", pack_id=900)
    seed_order(db, 3, DAY, [Line(103, "MLA4", 1, Decimal("70"))], tg="25", costo="30")
    seed_order(db, 4, DAY, [Line(104, "MLA5", 1, Decimal("70"))], tg="25", costo="30", status="cancelled")
    seed_order(db, 5, DAY, [Line(105, "MLA6", 1, Decimal("70"))], tg="25", costo="30", status="cancelled", covered=True)
    seed_order(db, 6, None, [Line(106, "MLA7", 1, Decimal("70"))], tg="25", costo="30")
    db.flush()
    store_order_metrics(db, {oid: _metrics(oid) for oid in range(1, 7)})


@pytest.mark.postgres
class TestSaleLinesStore:
    def test_the_stored_lines_are_what_sale_lines_derives(self, board_pg):
        _seed_world(board_pg)

        stored = _stored(board_pg)
        assert stored == _live(board_pg)
        # 3 lines of the pack + 1 standalone + 1 covered cancellation; the uncovered
        # cancellation and the never-accredited order are not sales.
        assert {row[1] for row in stored} == {1, 2, 3, 5}
        assert len(stored) == 5

    def test_lines_are_written_in_the_transaction_of_the_metrics(self, board_pg):
        seed_order(board_pg, 7, DAY, [Line(100, "MLA1", 1, Decimal("10"))], tg="5", costo="3")
        board_pg.flush()

        nested = board_pg.begin_nested()
        store_order_metrics(board_pg, {7: _metrics(7)})
        assert _stored(board_pg)
        nested.rollback()

        assert _stored(board_pg) == []
        assert board_pg.execute(text("SELECT count(*) FROM ml_order_metrics WHERE order_id = 7")).scalar() == 1

    def test_a_recompute_replaces_the_lines_it_wrote(self, board_pg):
        _seed_world(board_pg)
        board_pg.execute(text("UPDATE ml_order_items_ops SET quantity = 9 WHERE order_id = 3"))
        board_pg.execute(text("UPDATE ml_order_metrics SET total_gauss = 77 WHERE order_id = 3"))

        store_order_metrics(board_pg, {3: _metrics(3, tg="77")})

        after = _stored(board_pg)
        assert after == _live(board_pg)
        assert [row[7] for row in after if row[1] == 3] == [9]
        assert len(after) == 5

    def test_an_order_that_moves_to_another_pack_leaves_its_old_group(self, board_pg):
        _seed_world(board_pg)
        board_pg.execute(text("UPDATE ml_orders_ops SET pack_id = 901 WHERE order_id = 2"))

        store_order_metrics(board_pg, {2: _metrics(2)})

        keys = {row[2] for row in _stored(board_pg) if row[1] == 2}
        assert keys == {"p:901"}

    def test_the_pack_an_order_left_is_rewritten_when_its_siblings_are_stored(self, board_pg):
        """The capture trigger enqueues the surviving siblings of the pack an order
        left; storing one of them rewrites the group without the departed member."""
        _seed_world(board_pg)
        board_pg.execute(text("UPDATE ml_orders_ops SET pack_id = 901 WHERE order_id = 2"))
        store_order_metrics(board_pg, {2: _metrics(2)})

        store_order_metrics(board_pg, {1: _metrics(1)})

        assert _stored(board_pg) == _live(board_pg)

    def test_deleting_an_order_deletes_its_lines(self, board_pg):
        _seed_world(board_pg)

        board_pg.execute(text("DELETE FROM ml_order_items_ops WHERE order_id = 3"))

        assert 3 not in {row[1] for row in _stored(board_pg)}

    def test_two_transactions_storing_one_group_do_not_collide(self, board_pg_engine):
        """The second writer waits for the first one's group lock and then replaces
        its lines, instead of colliding with them on the primary key."""
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        with board_pg_engine.connect() as setup:
            setup.execute(
                text(
                    "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created) "
                    "VALUES (810, 999, 'paid', now(), now())"
                )
            )
            setup.execute(
                text(
                    "INSERT INTO ml_order_items_ops (id, order_id, item_id, quantity, unit_price) VALUES (8100, 810, 'MLA810', 1, 10)"
                )
            )
            setup.execute(
                text(
                    "INSERT INTO ml_payments_ops (payment_id, order_id, status, date_approved) VALUES (8101, 810, 'approved', now())"
                )
            )
            setup.execute(
                text(
                    "INSERT INTO ml_order_metrics (order_id, gauss_status, formula_version, computed_at, neto) VALUES (810, 'ok', 5, now(), 0)"
                )
            )
            setup.execute(
                text(
                    "INSERT INTO ml_group_metrics (group_key, gauss_status, member_order_ids, group_date, formula_version, computed_at) "
                    "VALUES ('o:810', 'ok', ARRAY[810]::bigint[], now(), 5, now())"
                )
            )
            setup.commit()
        barrier = Barrier(2)

        def write(_):
            with sessionmaker(bind=board_pg_engine)() as session:
                # Both hold the group before either writes: the lock is what orders them.
                session.execute(text("SELECT 1"))
                barrier.wait()
                store_sale_lines(session, [810], ["o:810"])
                session.commit()

        try:
            with ThreadPoolExecutor(2) as pool:
                list(pool.map(write, range(2)))
            with board_pg_engine.connect() as conn:
                assert conn.execute(text("SELECT count(*) FROM ml_sale_lines WHERE order_id = 810")).scalar() == 1
        finally:
            with board_pg_engine.connect() as conn:
                for table in (
                    "ml_sale_lines",
                    "ml_group_metrics",
                    "ml_order_metrics",
                    "ml_payments_ops",
                    "ml_order_items_ops",
                    "ml_orders_ops",
                ):
                    conn.execute(
                        text(
                            f"DELETE FROM {table} WHERE "
                            + (
                                "group_key = 'o:810'"
                                if table == "ml_group_metrics"
                                else "order_id = 810"
                                if table != "ml_payments_ops"
                                else "payment_id = 8101"
                            )
                        )
                    )
                conn.commit()

    def test_the_writer_ignores_the_recompute_queue(self, board_pg):
        """Money is written as if every order were settled; the board applies the
        queue when it reads."""
        _seed_world(board_pg)
        board_pg.execute(text("INSERT INTO ml_order_metrics_dirty (order_id, version, reason) VALUES (3, 1, 'x')"))

        store_sale_lines(board_pg, [3], ["o:3"])

        live_ignoring_queue = _live(board_pg)
        assert _stored(board_pg) == live_ignoring_queue
        assert [row[9] for row in _stored(board_pg) if row[1] == 3] == [Decimal("50.00")]
        # ... while the live, queue-aware derivation gives the queued order no money.
        queued = sale_lines(sqlite=False, keyed=True)
        live = board_pg.execute(select(queued.c.tg).where(queued.c.order_id == 3)).scalars().all()
        assert live == [0]

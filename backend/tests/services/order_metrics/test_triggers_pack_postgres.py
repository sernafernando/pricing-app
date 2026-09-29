"""Pack fan-out and orphan group cleanup (ventas-ml-rediseno PR20, SM R12/R14).

Postgres-only: these assert what a plpgsql trigger does, and SQLite has no
trigger to run. They skip locally when no Postgres is reachable and RUN in
CI, where the `postgres` service is available.

WHY THIS FILE EXISTS SEPARATELY from `test_triggers_postgres.py`: that file
pins PR4's fan-out by `shipping_id`. The cases here are the ones a review
found missing from the plan, and they share a property that makes them easy
to get wrong -- they only break when NO SIBLING SURVIVES. A test that leaves
a sibling behind exercises the fan-out, which works; the orphan only appears
when there is nothing left to enqueue, so nothing ever revisits the group.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text


def _order(session, order_id: int, pack_id: int | None = None) -> None:
    """Same column set the sibling Postgres trigger tests insert. `status`,
    `ml_last_updated` and `date_created` are NOT NULL on this table -- a
    leaner INSERT aborts the transaction, and every later statement in the
    test then fails with a misleading "transaction is aborted"."""
    session.execute(
        text(
            "INSERT INTO ml_orders_ops "
            "(order_id, seller_id, status, ml_last_updated, date_created, pack_id) "
            "VALUES (:oid, 999, 'paid', now(), now(), :pid)"
        ),
        {"oid": order_id, "pid": pack_id},
    )


def _group_row(session, group_key: str):
    return session.execute(
        text("SELECT group_key FROM ml_group_metrics WHERE group_key = :k"),
        {"k": group_key},
    ).first()


def _seed_group(session, group_key: str) -> None:
    """A group record standing in for one the worker already computed.

    Every NOT NULL column of `ml_group_metrics` is set explicitly
    (`gauss_status`, `member_order_ids`, `formula_version`, `computed_at`).
    Leaving one out aborts the transaction, and the test then fails with a
    misleading "transaction is aborted" from a LATER statement instead of
    from the insert that actually broke.
    """
    session.execute(
        text(
            "INSERT INTO ml_group_metrics "
            "(group_key, member_order_ids, gauss_status, formula_version, computed_at) "
            "VALUES (:k, ARRAY[]::bigint[], 'ok', 2, now()) "
            "ON CONFLICT (group_key) DO NOTHING"
        ),
        {"k": group_key},
    )


@pytest.fixture()
def slate(pg_order_metrics_triggers_db):
    session = pg_order_metrics_triggers_db
    session.execute(text("DELETE FROM ml_group_metrics"))
    session.execute(text("DELETE FROM ml_order_metrics_dirty"))
    session.execute(text("DELETE FROM ml_orders_ops WHERE seller_id = 999"))
    session.commit()
    yield session
    session.execute(text("DELETE FROM ml_group_metrics"))
    session.execute(text("DELETE FROM ml_order_metrics_dirty"))
    session.execute(text("DELETE FROM ml_orders_ops WHERE seller_id = 999"))
    session.commit()


@pytest.mark.postgres
class TestPackFanOut:
    def test_deleting_a_member_enqueues_the_surviving_sibling(self, slate) -> None:
        """SM R12: the group lost a member, so what the survivor's group
        record covers changed and it has to recompute."""
        session = slate
        _order(session, 700001, pack_id=7100)
        _order(session, 700002, pack_id=7100)
        session.commit()
        session.execute(text("DELETE FROM ml_order_metrics_dirty"))
        session.commit()

        session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = 700001"))
        session.commit()

        encolados = {r[0] for r in session.execute(text("SELECT order_id FROM ml_order_metrics_dirty")).all()}
        assert 700002 in encolados

    def test_a_pack_change_enqueues_both_sides(self, slate) -> None:
        """SM R12: the pack it left no longer covers this order; the pack it
        joined now does. Neither may be left stale."""
        session = slate
        _order(session, 700010, pack_id=7200)  # se queda en A
        _order(session, 700011, pack_id=7200)  # se muda a B
        _order(session, 700012, pack_id=7300)  # ya estaba en B
        session.commit()
        session.execute(text("DELETE FROM ml_order_metrics_dirty"))
        session.commit()

        session.execute(text("UPDATE ml_orders_ops SET pack_id = 7300 WHERE order_id = 700011"))
        session.commit()

        encolados = {r[0] for r in session.execute(text("SELECT order_id FROM ml_order_metrics_dirty")).all()}
        assert 700010 in encolados, "el pack que dejó tiene que refrescarse"
        assert 700012 in encolados, "el pack al que entró también"


@pytest.mark.postgres
class TestOrphanGroupCleanup:
    def test_standalone_joining_a_pack_loses_its_own_group_record(self, slate) -> None:
        """SM R14 case (a). Without this the sale is counted TWICE: once as
        the stale standalone group and once inside the pack."""
        session = slate
        _order(session, 700020, pack_id=None)
        _order(session, 700021, pack_id=7400)
        session.commit()
        _seed_group(session, "o:700020")
        session.commit()
        assert _group_row(session, "o:700020") is not None

        session.execute(text("UPDATE ml_orders_ops SET pack_id = 7400 WHERE order_id = 700020"))
        session.commit()

        assert _group_row(session, "o:700020") is None

    def test_last_member_leaving_removes_the_pack_record(self, slate) -> None:
        """SM R14 case (b). No sibling survives to enqueue, so nothing would
        ever revisit this record -- it would keep its last-known money."""
        session = slate
        _order(session, 700030, pack_id=7500)
        _order(session, 700031, pack_id=7600)
        session.commit()
        _seed_group(session, "p:7500")
        session.commit()

        session.execute(text("UPDATE ml_orders_ops SET pack_id = 7600 WHERE order_id = 700030"))
        session.commit()

        assert _group_row(session, "p:7500") is None

    def test_last_member_deleted_removes_the_pack_record(self, slate) -> None:
        """SM R14 case (b), through DELETE instead of a pack change."""
        session = slate
        _order(session, 700040, pack_id=7700)
        session.commit()
        _seed_group(session, "p:7700")
        session.commit()

        session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = 700040"))
        session.commit()

        assert _group_row(session, "p:7700") is None

    def test_a_pack_that_still_has_members_keeps_its_record(self, slate) -> None:
        """The negative of the two above, and the one that makes them mean
        something: removal must be driven by the group becoming EMPTY, not by
        any membership change at all."""
        session = slate
        _order(session, 700050, pack_id=7800)
        _order(session, 700051, pack_id=7800)
        session.commit()
        _seed_group(session, "p:7800")
        session.commit()

        session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = 700050"))
        session.commit()

        assert _group_row(session, "p:7800") is not None

    def test_deleting_a_standalone_order_removes_its_group_record(self, slate) -> None:
        """SM R14 case (c). `ml_order_metrics` goes through its FK cascade; a
        record keyed by GROUP identity has no FK to cascade from."""
        session = slate
        _order(session, 700060, pack_id=None)
        session.commit()
        _seed_group(session, "o:700060")
        session.commit()

        session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = 700060"))
        session.commit()

        assert _group_row(session, "o:700060") is None

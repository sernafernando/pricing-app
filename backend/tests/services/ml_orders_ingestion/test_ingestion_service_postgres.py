"""Postgres-only proof for the 2026-09-14 quarantine-isolation fix.

`tests/conftest.py`'s in-memory SQLite `db` fixture cannot exercise this:
a failed statement inside a plain SQLAlchemy transaction poisons the WHOLE
surrounding transaction on real PostgreSQL (`current transaction is
aborted, commands ignored until end of transaction block`) -- SQLite has
no equivalent, so a test proving the per-order `db.begin_nested()`
SAVEPOINT actually isolates one order's write failure from its siblings
in the SAME session can only be trusted against a real Postgres
connection. See `pg_orders_ops_db` in `tests/conftest.py`.

MUTATION TARGET (a) from the task's required verification: remove the
`db.begin_nested()` / `except (SQLAlchemyError, DBAPIError)` wrapping in
`ingestion_service.upsert_order` and
`test_a_bad_orders_write_failure_does_not_take_down_sibling_orders_in_the_same_session`
below must fail -- the poisoned transaction takes the healthy siblings
down with it.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOpsDivergence, MlOrderItemOps, MlOrdersOps, MlOrdersOpsCuarentena
from app.services.ml_orders_ingestion import ingestion_service
from app.services.ml_orders_ingestion.ingestion_service import UpsertOutcome, upsert_order


def _order_payload(
    order_id: int,
    status_detail=None,
    last_updated: str = "2026-09-10T10:00:00.000-04:00",
    currency_id: str = "ARS",
) -> dict:
    return {
        "id": order_id,
        "status": "paid",
        "status_detail": status_detail,
        "date_created": "2026-09-09T10:00:00.000-04:00",
        "date_last_updated": last_updated,
        "seller": {"id": 999},
        "buyer": {"id": 55, "nickname": "comprador"},
        "total_amount": 100.0,
        "paid_amount": 100.0,
        "currency_id": currency_id,
        "order_items": [
            {"item": {"id": "MLA1", "seller_sku": "SKU-1"}, "quantity": 1, "unit_price": 100.0},
        ],
    }


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
    # This fixture's engine (`pg_orders_ops_engine`, see conftest.py) does
    # not stand up `congelar`'s own dependency tables on purpose (ENUM
    # type collision with `pg_payments_engine`) -- no-op it instead of
    # testing the cost-snapshot seam this module is not about.
    monkeypatch.setattr(ingestion_service, "congelar", lambda db, order_id, items: None)


@pytest.mark.postgres
class TestQuarantineIsolationOnRealPostgres:
    def test_a_bad_orders_write_failure_does_not_take_down_sibling_orders_in_the_same_session(self, pg_orders_ops_db):
        """Reproduces the incident's exact shape in one batch, ALL in the
        SAME session/transaction the way `sweep_service.process_batch`
        does it: order 1 is healthy, order 2's `status_detail` is a
        genuine DB-level rejection (>60 chars, the real column limit --
        the incident's own payload was a dict, but a length violation is
        an equally real, equally uncaught-by-Python-type-checks Postgres
        error), order 3 is healthy again.

        Without the per-order SAVEPOINT, order 2's failed INSERT aborts
        the whole transaction and orders 1 and 3 are never actually
        committed -- they would look "written" locally but vanish on
        `db.commit()` (or raise `PendingRollbackError` on the very next
        statement). WITH it, 1 and 3 land, 2 is isolated and quarantined,
        and the pass can keep going."""
        db = pg_orders_ops_db
        # POISON: a `currency_id` longer than its `String(5)` column.
        #
        # It used to be an over-long `status_detail`, and that stopped
        # working the day the mapper started truncating that field (the fix
        # for the 2026-09-10 incident). A test whose trigger has been
        # defused silently proves nothing, so the poison moved to a field
        # the mapper still passes through verbatim.
        too_long = "PESOS-ARGENTINOS"  # column is String(5)

        first = upsert_order(db, _order_payload(order_id=1001))
        second = upsert_order(db, _order_payload(order_id=1002, currency_id=too_long))
        third = upsert_order(db, _order_payload(order_id=1003))

        assert first == UpsertOutcome.OK
        assert second == UpsertOutcome.WRITE_ERROR
        assert third == UpsertOutcome.OK

        # The transaction must still be usable -- proves it was not
        # poisoned. `db.flush()` alone (not `commit()`) is enough: a
        # poisoned Postgres transaction rejects ANY further statement,
        # flush included, with `InFailedSqlTransaction`.
        db.flush()

        assert db.query(MlOrdersOps).filter_by(order_id=1001).count() == 1
        assert db.query(MlOrdersOps).filter_by(order_id=1002).count() == 0
        assert db.query(MlOrdersOps).filter_by(order_id=1003).count() == 1
        assert db.query(MlOrderItemOps).filter_by(order_id=1001).count() == 1
        assert db.query(MlOrderItemOps).filter_by(order_id=1003).count() == 1

        quarantined = db.query(MlOrdersOpsCuarentena).filter_by(order_id=1002).one()
        # The payload is stored WHOLE, poison field included.
        assert quarantined.raw_order["currency_id"] == too_long

        divergence = db.query(MlOpsDivergence).filter_by(order_id=1002, kind="ingest_failed").one()
        assert divergence.state == "open"

    def test_committing_after_a_write_error_actually_persists_the_healthy_orders(self, pg_orders_ops_db):
        """The strongest possible proof: an ACTUAL commit to the real
        Postgres connection, then a fresh read. A poisoned transaction
        would refuse the commit outright."""
        db = pg_orders_ops_db
        upsert_order(db, _order_payload(order_id=2001))
        upsert_order(db, _order_payload(order_id=2002, currency_id="PESOS-ARGENTINOS"))
        upsert_order(db, _order_payload(order_id=2003))

        db.commit()

        assert db.query(MlOrdersOps).filter_by(order_id=2001).count() == 1
        assert db.query(MlOrdersOps).filter_by(order_id=2003).count() == 1
        assert db.query(MlOrdersOpsCuarentena).filter_by(order_id=2002).count() == 1


@pytest.mark.postgres
class TestSoldSkuIsKeptOnReingestion:
    """`seller_sku` always follows MercadoLibre (the CURRENT SKU), while
    `seller_sku_vendido` keeps the first SKU ingestion ever saw for the item."""

    @staticmethod
    def _with_sku(payload: dict, sku) -> dict:
        payload["order_items"][0]["item"]["seller_sku"] = sku
        return payload

    def _item(self, db, order_id: int) -> MlOrderItemOps:
        db.expire_all()
        return db.query(MlOrderItemOps).filter_by(order_id=order_id).one()

    def test_first_ingestion_stores_the_incoming_sku_as_sold(self, pg_orders_ops_db):
        db = pg_orders_ops_db
        upsert_order(db, self._with_sku(_order_payload(order_id=3001), "1214"))

        item = self._item(db, 3001)
        assert (item.seller_sku, item.seller_sku_vendido) == ("1214", "1214")

    def test_reingestion_with_a_new_sku_updates_current_but_keeps_the_sold_one(self, pg_orders_ops_db):
        db = pg_orders_ops_db
        upsert_order(db, self._with_sku(_order_payload(order_id=3002), "1214"))
        upsert_order(
            db,
            self._with_sku(_order_payload(order_id=3002, last_updated="2026-09-11T10:00:00.000-04:00"), "1215"),
        )

        item = self._item(db, 3002)
        assert (item.seller_sku, item.seller_sku_vendido) == ("1215", "1214")

    def test_a_third_change_still_keeps_the_first_sku(self, pg_orders_ops_db):
        db = pg_orders_ops_db
        for sku, day in (("1214", "10"), ("1215", "11"), ("1216", "12")):
            upsert_order(
                db,
                self._with_sku(_order_payload(order_id=3003, last_updated=f"2026-09-{day}T10:00:00.000-04:00"), sku),
            )

        item = self._item(db, 3003)
        assert (item.seller_sku, item.seller_sku_vendido) == ("1216", "1214")

    def test_a_row_without_sold_sku_adopts_its_previous_current_sku(self, pg_orders_ops_db):
        """Rows from before the column existed that the backfill left NULL
        (no SKU then) or that predate it: the previous `seller_sku` is the
        best known 'sold' value, never the incoming one."""
        db = pg_orders_ops_db
        upsert_order(db, self._with_sku(_order_payload(order_id=3004), "1214"))
        db.query(MlOrderItemOps).filter_by(order_id=3004).update({"seller_sku_vendido": None})
        db.flush()
        upsert_order(
            db,
            self._with_sku(_order_payload(order_id=3004, last_updated="2026-09-11T10:00:00.000-04:00"), "1215"),
        )

        item = self._item(db, 3004)
        assert (item.seller_sku, item.seller_sku_vendido) == ("1215", "1214")

    def test_an_item_first_ingested_without_sku_adopts_the_first_sku_it_gets(self, pg_orders_ops_db):
        db = pg_orders_ops_db
        upsert_order(db, self._with_sku(_order_payload(order_id=3005), None))
        upsert_order(
            db,
            self._with_sku(_order_payload(order_id=3005, last_updated="2026-09-11T10:00:00.000-04:00"), "1215"),
        )

        item = self._item(db, 3005)
        assert (item.seller_sku, item.seller_sku_vendido) == ("1215", "1215")

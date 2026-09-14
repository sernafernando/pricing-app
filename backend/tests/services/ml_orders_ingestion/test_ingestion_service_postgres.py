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


def _order_payload(order_id: int, status_detail=None, last_updated: str = "2026-09-10T10:00:00.000-04:00") -> dict:
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
        "currency_id": "ARS",
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
        too_long_status_detail = "x" * 200  # column is String(60)

        first = upsert_order(db, _order_payload(order_id=1001))
        second = upsert_order(db, _order_payload(order_id=1002, status_detail=too_long_status_detail))
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
        assert quarantined.raw_order["status_detail"] == too_long_status_detail

        divergence = db.query(MlOpsDivergence).filter_by(order_id=1002, kind="ingest_failed").one()
        assert divergence.state == "open"

    def test_committing_after_a_write_error_actually_persists_the_healthy_orders(self, pg_orders_ops_db):
        """The strongest possible proof: an ACTUAL commit to the real
        Postgres connection, then a fresh read. A poisoned transaction
        would refuse the commit outright."""
        db = pg_orders_ops_db
        upsert_order(db, _order_payload(order_id=2001))
        upsert_order(db, _order_payload(order_id=2002, status_detail="x" * 200))
        upsert_order(db, _order_payload(order_id=2003))

        db.commit()

        assert db.query(MlOrdersOps).filter_by(order_id=2001).count() == 1
        assert db.query(MlOrdersOps).filter_by(order_id=2003).count() == 1
        assert db.query(MlOrdersOpsCuarentena).filter_by(order_id=2002).count() == 1

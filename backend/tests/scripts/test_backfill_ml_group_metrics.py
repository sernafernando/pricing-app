"""Backfill of the per-group record for sales that already exist.

The case this guards is invisible from inside the live path: an order whose
metrics were stored BEFORE `ml_group_metrics` existed is not dirty, has a
current `formula_version`, and will never be re-stored -- so its group record
would never come into being, and the endpoints that read it with no live
fallback would answer unknown forever.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.ml_group_metrics import MlGroupMetrics
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrdersOps
from app.scripts import backfill_ml_group_metrics as script


@pytest.fixture(autouse=True)
def _session_local(db, monkeypatch):
    """Same pattern the sibling backfill tests use: the script opens its OWN
    `SessionLocal()`, so point it at the test session with a no-op `close()`."""

    class _NoClose:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def close(self):
            pass

    monkeypatch.setattr(script, "SessionLocal", lambda: _NoClose(db))


def _order(db, order_id: int, pack_id=None, total_amount=Decimal("100.00")) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status="paid",
            ml_last_updated=datetime(2026, 9, 20, tzinfo=timezone.utc),
            date_created=datetime(2026, 9, 15, tzinfo=timezone.utc),
            seller_id=999,
            total_amount=total_amount,
            currency_id="ARS",
        )
    )


def _stored(db, order_id: int) -> None:
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=Decimal("100.00"),
            neto_sin_iva=Decimal("82.64"),
            iva_reconcilia=True,
            costo_mercaderia=Decimal("30.00"),
            total_gauss=Decimal("50.00"),
            markup_pct=Decimal("166.67"),
            gauss_status="ok",
            formula_version=2,
            computed_at=datetime.now(timezone.utc),
        )
    )


class TestBackfillWritesTheMissingGroupRecords:
    def test_a_pack_with_stored_members_and_no_group_record_gets_one(self, db):
        _order(db, 9001, pack_id=960)
        _order(db, 9002, pack_id=960)
        db.flush()
        _stored(db, 9001)
        _stored(db, 9002)
        db.commit()

        script.main(["--limit", "100"])

        fila = db.query(MlGroupMetrics).filter_by(group_key="p:960").one()
        assert fila.total_gauss == Decimal("100.00")

    def test_a_standalone_order_gets_its_own_record(self, db):
        _order(db, 9010, pack_id=None)
        db.flush()
        _stored(db, 9010)
        db.commit()

        script.main(["--limit", "100"])

        assert db.query(MlGroupMetrics).filter_by(group_key="o:9010").one() is not None

    def test_a_group_that_already_has_a_record_is_left_alone(self, db):
        """The record is not recomputed just because the backfill ran: it is
        for groups that have NONE. Asserting the stored VALUE and not merely
        the row's presence is what makes this discriminate -- a recompute
        would overwrite 999 with the real 50."""
        _order(db, 9020, pack_id=None)
        db.flush()
        _stored(db, 9020)
        db.add(
            MlGroupMetrics(
                group_key="o:9020",
                neto=None,
                neto_sin_iva=None,
                costo_mercaderia=None,
                total_gauss=Decimal("999.00"),
                markup_pct=None,
                gauss_status="ok",
                member_order_ids=[9020],
                formula_version=2,
                computed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        script.main(["--limit", "100"])

        assert db.query(MlGroupMetrics).filter_by(group_key="o:9020").one().total_gauss == Decimal("999.00")

    def test_dry_run_writes_nothing(self, db):
        _order(db, 9030, pack_id=None)
        db.flush()
        _stored(db, 9030)
        db.commit()

        script.main(["--limit", "100", "--dry-run"])

        assert db.query(MlGroupMetrics).filter_by(group_key="o:9030").one_or_none() is None

    def test_the_result_reports_written_and_no_members_separately(self, db):
        """The two counters mean different things, and one of them used to be
        named after the other.

        `no_members` is NOT a count of `unresolved` records: a group whose
        members are not all resolvable still GETS a record and is counted in
        `written`. `no_members` counts the groups `recompute_group_metrics`
        declined to return at all. The key was called `unresolved` while the
        log printed it as `no_members` -- two names for one number, with the
        wrong one facing the caller.
        """
        _order(db, 9040, pack_id=None)
        db.flush()
        _stored(db, 9040)
        db.commit()

        resultado = script.run_backfill(limit=100, dry_run=False)

        assert set(resultado) == {"examined", "written", "no_members"}
        assert resultado["written"] == 1
        assert resultado["no_members"] == 0

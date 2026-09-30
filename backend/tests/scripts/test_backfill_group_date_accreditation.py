"""RED/GREEN + Postgres tests for `backfill_group_date_accreditation`
(ODD `ventas-ml-dia-por-acreditacion`, T5).

Uses `ARRAY(BigInteger)` (`MlGroupMetrics.member_order_ids`) and the
`= ANY(:keys)` Postgres-only operator -- this whole module is
`@pytest.mark.postgres`, no SQLite counterpart.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.scripts import backfill_group_date_accreditation as script
from app.scripts.backfill_group_date_accreditation import count_remaining, run_backfill


def _group_metrics_row(session, group_key: str, member_order_ids, group_date) -> None:
    session.execute(
        text(
            "INSERT INTO ml_group_metrics "
            "(group_key, gauss_status, member_order_ids, group_date, formula_version, computed_at) "
            "VALUES (:gk, 'ok', :members, :gd, 1, now())"
        ),
        {"gk": group_key, "members": member_order_ids, "gd": group_date},
    )


def _order(session, order_id: int) -> None:
    session.execute(
        text(
            "INSERT INTO ml_orders_ops "
            "(order_id, seller_id, status, ml_last_updated, date_created, total_amount, paid_amount, currency_id) "
            "VALUES (:oid, 999, 'paid', now(), now(), 100, 100, 'ARS')"
        ),
        {"oid": order_id},
    )


def _payment(session, payment_id: int, order_id: int, status: str, date_approved) -> None:
    session.execute(
        text(
            "INSERT INTO ml_payments_ops (payment_id, order_id, status, date_approved) "
            "VALUES (:pid, :oid, :status, :da)"
        ),
        {"pid": payment_id, "oid": order_id, "status": status, "da": date_approved},
    )


@pytest.fixture()
def slate(pg_order_metrics_triggers_db, monkeypatch):
    """Same pattern the sibling backfill tests use (`test_backfill_ml_group_metrics.py`):
    the script opens its OWN `SessionLocal()`, so point it at the test session
    with a no-op `close()`."""
    session = pg_order_metrics_triggers_db
    session.execute(text("DELETE FROM ml_group_metrics"))
    session.execute(text("DELETE FROM ml_orders_ops WHERE seller_id = 999"))
    session.commit()

    class _NoClose:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def close(self):
            pass

    monkeypatch.setattr(script, "SessionLocal", lambda: _NoClose(session))
    return session


@pytest.mark.postgres
class TestBackfillGroupDateAccreditation:
    def test_rewrites_stale_group_date_to_the_accreditation_basis(self, slate) -> None:
        """The decisive case: a group's stored `group_date` was computed
        under the OLD `date_created` basis (2026-09-01 here) -- the member's
        real accreditation is 2026-09-30. A real run must overwrite it."""
        _order(slate, 1)
        _payment(slate, 1, 1, "approved", datetime(2026, 9, 30, tzinfo=timezone.utc))
        _group_metrics_row(slate, "o:1", [1], datetime(2026, 9, 1, tzinfo=timezone.utc))
        slate.commit()

        assert count_remaining(slate) == 1

        resultado = run_backfill(limit=None, dry_run=False)

        row = slate.execute(text("SELECT group_date FROM ml_group_metrics WHERE group_key = 'o:1'")).one()
        assert row.group_date == datetime(2026, 9, 30, tzinfo=timezone.utc)
        assert resultado["written"] == 1
        assert resultado["remaining"] == 0

    def test_already_correct_row_is_left_alone(self, slate) -> None:
        _order(slate, 2)
        _payment(slate, 2, 2, "approved", datetime(2026, 9, 15, tzinfo=timezone.utc))
        _group_metrics_row(slate, "o:2", [2], datetime(2026, 9, 15, tzinfo=timezone.utc))
        slate.commit()

        assert count_remaining(slate) == 0

        resultado = run_backfill(limit=None, dry_run=False)

        assert resultado["written"] == 0
        assert resultado["unchanged"] == 1

    def test_dry_run_writes_nothing(self, slate) -> None:
        _order(slate, 3)
        _payment(slate, 3, 3, "approved", datetime(2026, 9, 30, tzinfo=timezone.utc))
        _group_metrics_row(slate, "o:3", [3], datetime(2026, 9, 1, tzinfo=timezone.utc))
        slate.commit()

        resultado = run_backfill(limit=None, dry_run=True)

        assert resultado["remaining"] == 1
        row = slate.execute(text("SELECT group_date FROM ml_group_metrics WHERE group_key = 'o:3'")).one()
        assert row.group_date == datetime(2026, 9, 1, tzinfo=timezone.utc)

    def test_dry_run_examined_counts_rows_actually_scanned_not_rows_that_would_change(self, slate) -> None:
        """`examined` must mean rows actually examined, in BOTH modes. Under
        `--dry-run` it was set to `remaining` (rows that WOULD change), which
        misreports the moment one already-correct row exists alongside a
        stale one: `examined` (scanned) must be 2, `remaining` (would change)
        must stay 1 -- they are different numbers and must not collapse."""
        _order(slate, 20)
        _payment(slate, 20, 20, "approved", datetime(2026, 9, 30, tzinfo=timezone.utc))
        _group_metrics_row(slate, "o:20", [20], datetime(2026, 9, 1, tzinfo=timezone.utc))  # stale -> would change

        _order(slate, 21)
        _payment(slate, 21, 21, "approved", datetime(2026, 9, 15, tzinfo=timezone.utc))
        _group_metrics_row(slate, "o:21", [21], datetime(2026, 9, 15, tzinfo=timezone.utc))  # already correct
        slate.commit()

        resultado = run_backfill(limit=None, dry_run=True)

        assert resultado["remaining"] == 1
        assert resultado["examined"] == 2, "examined must count ALL scanned rows, not only the ones that would change"

    def test_no_accredited_payment_becomes_null_group_date(self, slate) -> None:
        _order(slate, 4)
        _payment(slate, 4, 4, "rejected", None)
        _group_metrics_row(slate, "o:4", [4], datetime(2026, 9, 1, tzinfo=timezone.utc))
        slate.commit()

        run_backfill(limit=None, dry_run=False)

        row = slate.execute(text("SELECT group_date FROM ml_group_metrics WHERE group_key = 'o:4'")).one()
        assert row.group_date is None

    def test_a_limited_run_leaves_remaining_nonzero_never_looking_complete(self, slate) -> None:
        for i in range(5, 7):
            _order(slate, i)
            _payment(slate, i, i, "approved", datetime(2026, 9, 30, tzinfo=timezone.utc))
            _group_metrics_row(slate, f"o:{i}", [i], datetime(2026, 9, 1, tzinfo=timezone.utc))
        slate.commit()

        resultado = run_backfill(limit=1, dry_run=False)

        assert resultado["written"] == 1
        assert resultado["remaining"] == 1, "a partial run must NEVER report 0 remaining"

    def test_writes_go_out_as_one_executemany_per_batch_not_one_update_per_row(self, slate) -> None:
        """BLOCKING finding: the real run touches ~77k rows. Issuing one
        `UPDATE` per changed `group_key` is 77k round trips. The batch must
        build a list of param dicts and hand them to a SINGLE `db.execute(text(...), [...])`
        call (`executemany`), the same pattern `backfill_ml_group_metrics.py`'s
        `store_group_metrics` already uses via `db.execute(stmt, rows)`."""
        for i in range(10, 13):
            _order(slate, i)
            _payment(slate, i, i, "approved", datetime(2026, 9, 30, tzinfo=timezone.utc))
            _group_metrics_row(slate, f"o:{i}", [i], datetime(2026, 9, 1, tzinfo=timezone.utc))
        slate.commit()

        update_calls = []
        real_execute = slate.execute

        def _spy(clause, *args, **kwargs):
            sql_text = str(getattr(clause, "text", clause))
            if sql_text.strip().upper().startswith("UPDATE ML_GROUP_METRICS"):
                update_calls.append(args[0] if args else None)
            return real_execute(clause, *args, **kwargs)

        slate.execute = _spy
        try:
            resultado = run_backfill(limit=None, dry_run=False, batch_size=500)
        finally:
            slate.execute = real_execute

        assert resultado["written"] == 3
        assert len(update_calls) == 1, (
            f"expected exactly ONE executemany UPDATE call for the whole batch of 3 changed rows, "
            f"got {len(update_calls)} calls (one per row = N+1)"
        )
        assert isinstance(update_calls[0], list) and len(update_calls[0]) == 3

"""ml-billing-balance PR 4a-i -- the poison-row gaps store (BS-7).

A page that ML answers with a bare 400 is isolated down to the bad row, and
that row is recorded here instead of halting the period. The gap is a record
of what is missing, never a substitute for it: whether a document is complete
stays a QUERY of the persisted rows (BS-3), so a gap does not change it.

The error text stored with a gap is the real captured 400 envelope.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.ml_billing import MlBillingSweepGap
from app.services.ml_billing.sweep_gaps import open_gaps, record_gap, resolve_gap

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing"
_PERIOD = "2026-09-01"
_T0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _envelope() -> dict:
    return json.loads((_FIXTURES / "captured_400_envelope.json").read_text())


def _record(db, *, position="69805135022", paging="from_id", document_type="BILL", now=_T0, **extra):
    return record_gap(
        db,
        period_key=_PERIOD,
        document_type=document_type,
        billing_source="general",
        paging=paging,
        position=position,
        window=f"({int(position) - 1}, {position}]",
        http_status=400,
        error=json.dumps(_envelope()),
        now=now,
        **extra,
    )


def _count(db) -> int:
    return db.execute(select(func.count()).select_from(MlBillingSweepGap)).scalar_one()


class TestRecordGap:
    def test_first_sight_stores_the_captured_envelope_and_counts_one(self, db) -> None:
        _record(db)
        db.commit()

        gap = db.execute(select(MlBillingSweepGap)).scalar_one()
        assert (gap.period_key, gap.document_type, gap.billing_source) == (_PERIOD, "BILL", "general")
        assert (gap.paging, gap.position, gap.http_status) == ("from_id", "69805135022", 400)
        assert gap.window == "(69805135021, 69805135022]"
        assert json.loads(gap.error) == _envelope()
        assert gap.seen_count == 1
        assert gap.first_seen_at == gap.last_seen_at
        assert gap.resolved_at is None

    def test_seeing_the_same_position_again_upserts_instead_of_duplicating(self, db) -> None:
        _record(db, now=_T0)
        _record(db, now=_T0 + timedelta(minutes=15))
        db.commit()

        assert _count(db) == 1
        gap = db.execute(select(MlBillingSweepGap)).scalar_one()
        assert gap.seen_count == 2
        assert gap.first_seen_at.replace(tzinfo=None) == _T0.replace(tzinfo=None)
        assert gap.last_seen_at.replace(tzinfo=None) == (_T0 + timedelta(minutes=15)).replace(tzinfo=None)

    def test_the_key_is_period_type_source_paging_and_position(self, db) -> None:
        _record(db)
        _record(db, position="69805135023")
        _record(db, document_type="CREDIT_NOTE")
        _record(db, paging="offset", position="1500")
        db.commit()

        assert _count(db) == 4

    def test_a_gap_that_fails_again_after_resolving_is_open_again(self, db) -> None:
        _record(db)
        resolve_gap(
            db,
            period_key=_PERIOD,
            document_type="BILL",
            billing_source="general",
            paging="from_id",
            position="69805135022",
            now=_T0 + timedelta(minutes=5),
        )
        _record(db, now=_T0 + timedelta(minutes=30))
        db.commit()

        gap = db.execute(select(MlBillingSweepGap)).scalar_one()
        assert gap.resolved_at is None
        assert gap.seen_count == 2


class TestResolveGap:
    def test_a_later_successful_read_of_the_position_sets_resolved_at_once(self, db) -> None:
        _record(db)
        key = dict(
            period_key=_PERIOD,
            document_type="BILL",
            billing_source="general",
            paging="from_id",
            position="69805135022",
        )
        resolved_first = resolve_gap(db, now=_T0 + timedelta(minutes=5), **key)
        resolved_again = resolve_gap(db, now=_T0 + timedelta(minutes=50), **key)
        db.commit()

        gap = db.execute(select(MlBillingSweepGap)).scalar_one()
        assert resolved_first is True
        assert resolved_again is False, "an already resolved gap keeps its first resolution time"
        assert gap.resolved_at.replace(tzinfo=None) == (_T0 + timedelta(minutes=5)).replace(tzinfo=None)

    def test_resolving_a_position_that_was_never_a_gap_is_a_no_op(self, db) -> None:
        resolved = resolve_gap(
            db,
            period_key=_PERIOD,
            document_type="BILL",
            billing_source="general",
            paging="from_id",
            position="1",
            now=_T0,
        )

        assert resolved is False
        assert _count(db) == 0


class TestOpenGaps:
    def test_lists_only_unresolved_gaps_of_the_period_in_position_order(self, db) -> None:
        _record(db, position="69805135030")
        _record(db, position="69805135022")
        _record(db, position="69805135040")
        resolve_gap(
            db,
            period_key=_PERIOD,
            document_type="BILL",
            billing_source="general",
            paging="from_id",
            position="69805135040",
            now=_T0,
        )
        record_gap(
            db,
            period_key="2026-08-01",
            document_type="BILL",
            billing_source="general",
            paging="from_id",
            position="1",
            window="(0, 1]",
            http_status=400,
            error="x",
            now=_T0,
        )
        db.commit()

        assert [g.position for g in open_gaps(db, _PERIOD)] == ["69805135022", "69805135030"]

    @pytest.mark.parametrize("document_type", ["BILL", "CREDIT_NOTE"])
    def test_can_be_narrowed_to_one_document_type(self, db, document_type) -> None:
        _record(db, document_type="BILL")
        _record(db, document_type="CREDIT_NOTE")
        db.commit()

        assert {g.document_type for g in open_gaps(db, _PERIOD, document_type)} == {document_type}

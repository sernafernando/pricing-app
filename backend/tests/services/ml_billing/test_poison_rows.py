"""ml-billing-balance PR 4a-iii -- the poison row engine (BS-7, tasks 4a.3/4a.4).

A page ML answers with a bare 400 is narrowed down to the poison row, a gap is
recorded, the row is stepped over and the period continues. The engine is
driven by an injected `fetch(from_id, limit)`, so nothing sleeps here.

`_Ml` replays the behaviour measured on the real API: `from_id` is exclusive,
`detail_id` is numeric and ascending, a page that contains the poison row is
answered with the captured bare 400 envelope, and a cursor past the last row
gets the empty page with `last_id=0`. Retried requests are scripted separately.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models.ml_billing import MlBillingCharge, MlBillingDocument
from app.services.ml_billing.document_completeness import document_completeness
from app.services.ml_billing.poison_rows import POISON_PROBE_BOUND, read_page_skipping_poison, resolve_recovered_gaps
from app.services.ml_billing.sweep_gaps import open_gaps
from app.services.ml_webhook_client import BillingFetch

_PERIOD = "2026-09-01"
_NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
_ENVELOPE = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing" / "captured_400_envelope.json").read_text()
)
_BARE_400 = BillingFetch(400, _ENVELOPE, "HTTP 400")
# Real ids are ~70.7B and irregularly spaced: the poison row is far from its neighbours.
_IDS = [70714313961, 70714313962, 70714313970, 70714319000, 70714319001, 70714360000, 70714360005]


class _Ml:
    def __init__(self, ids, poison=(), flaky_first=0):
        self.ids, self.poison, self.flaky = sorted(ids), set(poison), flaky_first
        self.calls: list[tuple[int, int]] = []

    def __call__(self, from_id, limit):
        self.calls.append((from_id, limit))
        if self.flaky:
            self.flaky -= 1
            return _BARE_400
        rows = [i for i in self.ids if i > from_id][:limit]
        if self.poison & set(rows):
            return _BARE_400
        body = {
            "results": [{"charge_info": {"detail_id": i}} for i in rows],
            "total": 0,
            "last_id": rows[-1] if rows else 0,
        }
        return BillingFetch(200, body, None)


def _read(db, fetch, from_id=0, limit=1000, **kw):
    return read_page_skipping_poison(
        db, fetch=fetch, period_key=_PERIOD, document_type="BILL", from_id=from_id, limit=limit, now=_NOW, **kw
    )


def _ids(page) -> list[int]:
    return [r["charge_info"]["detail_id"] for r in page["results"]]


def _sweep(db, ml, limit=4):
    """A minimal driver: persist what the engine returns, advance, repeat."""
    seen, from_id = [], 0
    for _ in range(500):
        read = _read(db, ml, from_id=from_id, limit=limit)
        assert read.failure is None
        if read.page is None:
            from_id = read.from_id
            continue
        if not read.page["results"]:
            return seen
        seen += _ids(read.page)
        from_id = read.page["last_id"]
    raise AssertionError("the sweep did not terminate")


class TestEngine:
    def test_a_clean_page_costs_one_call_and_no_gap(self, db) -> None:
        ml = _Ml(_IDS)
        read = _read(db, ml)
        assert _ids(read.page) == _IDS and read.failure is None and len(ml.calls) == 1
        assert open_gaps(db, _PERIOD) == []

    def test_an_intermittent_400_is_retried_once_at_the_same_size(self, db) -> None:
        ml = _Ml(_IDS, flaky_first=1)
        read = _read(db, ml, limit=1000)
        assert _ids(read.page) == _IDS
        assert ml.calls == [(0, 1000), (0, 1000)]
        assert open_gaps(db, _PERIOD) == []

    def test_the_limit_is_halved_and_a_good_prefix_is_returned(self, db) -> None:
        ml = _Ml(_IDS, poison=[70714319000])
        read = _read(db, ml, limit=8)
        assert [limit for _, limit in ml.calls] == [8, 8, 4, 2]
        assert _ids(read.page) == _IDS[:2] and open_gaps(db, _PERIOD) == []

    def test_the_exact_poison_id_is_found_and_skipped(self, db) -> None:
        poison = 70714319000
        ml = _Ml(_IDS, poison=[poison])
        read = _read(db, ml, from_id=70714313970, limit=1)
        assert read.failure is None and read.gaps == (poison,)
        # Resumed past the poison row: the page read there starts right after it.
        assert read.from_id == poison and _ids(read.page) == [70714319001]
        [gap] = open_gaps(db, _PERIOD, "BILL")
        assert (gap.position, gap.paging, gap.billing_source, gap.http_status) == (
            str(poison),
            "from_id",
            "general",
            400,
        )
        assert gap.window == f"(70714313970, {poison}]" and json.loads(gap.error) == _ENVELOPE
        # Exponential then binary probe, not a scan of the 5,000 ids between neighbours.
        assert len(ml.calls) <= 2 + 2 * 2 * 13 + 1

    def test_adjacent_poison_rows_are_covered_by_the_recorded_window(self, db) -> None:
        # The probe cannot tell where a run of consecutive poison rows starts: it
        # only finds the last one. The window must start at the cursor so the first
        # poison row is not lost without a pointer.
        x, first, last = 70714313970, 70714319000, 70714319001
        read = _read(db, _Ml(_IDS, poison=[first, last]), from_id=x, limit=1)
        assert read.gaps == (last,) and _ids(read.page) == [70714360000]
        [gap] = open_gaps(db, _PERIOD)
        assert gap.position == str(last) and gap.window == f"({x}, {last}]"

    def test_a_spurious_400_inside_the_probe_does_not_skip_good_rows(self, db) -> None:
        x, poison = 70714313970, 70714319000
        ml, spurious = _Ml(_IDS, poison=[poison]), []

        def fetch(from_id, limit):
            # A probe past the poison row would succeed, but ML answers 400 once.
            if from_id == x + 6144 and not spurious:
                spurious.append(from_id)
                return _BARE_400
            return ml(from_id, limit)

        read = _read(db, fetch, from_id=x, limit=1)
        assert spurious and read.gaps == (poison,) and _ids(read.page) == [70714319001]

    def test_a_whole_sweep_loses_only_the_poison_row(self, db) -> None:
        ml = _Ml(_IDS, poison=[70714319000, 70714360005])
        assert _sweep(db, ml) == [i for i in _IDS if i not in ml.poison]
        assert [g.position for g in open_gaps(db, _PERIOD)] == ["70714319000", "70714360005"]

    def test_a_poison_row_at_the_end_ends_the_pass_with_an_empty_page(self, db) -> None:
        ml = _Ml(_IDS, poison=[_IDS[-1]])
        read = _read(db, ml, from_id=_IDS[-2], limit=1)
        assert read.gaps == (_IDS[-1],) and read.page["results"] == []

    def test_a_400_that_never_isolates_records_the_window_and_moves_on(self, db) -> None:
        calls = []

        def always_400(from_id, limit):
            calls.append((from_id, limit))
            return _BARE_400

        read = _read(db, always_400, from_id=10, limit=1)
        assert read.page is None and read.failure is None and read.from_id == 10 + POISON_PROBE_BOUND
        [gap] = open_gaps(db, _PERIOD)
        assert gap.position == str(10 + POISON_PROBE_BOUND) and gap.window == f"(10, {10 + POISON_PROBE_BOUND}]"
        assert len(calls) <= 2 + 2 * 41

    @pytest.mark.parametrize(
        "failure",
        [
            BillingFetch(429, {}, "HTTP 429"),
            BillingFetch(503, None, "HTTP 503"),
            BillingFetch(None, None, "ReadTimeout"),
        ],
    )
    def test_a_throttle_or_outage_stops_without_a_gap(self, db, failure) -> None:
        calls = []

        def fetch(from_id, limit):
            calls.append(limit)
            return failure

        read = _read(db, fetch)
        assert read.failure is failure and read.page is None and calls == [1000]
        assert open_gaps(db, _PERIOD) == []

    def test_a_failure_in_the_middle_of_the_probe_leaves_no_gap(self, db) -> None:
        ml = _Ml(_IDS, poison=[70714319000])
        outage = BillingFetch(429, {}, "HTTP 429")

        def fetch(from_id, limit):
            return outage if from_id >= 70714313970 + 4 else ml(from_id, limit)

        read = _read(db, fetch, from_id=70714313970, limit=1)
        assert read.failure is outage and open_gaps(db, _PERIOD) == []

    def test_a_400_that_names_a_cause_is_not_skipped(self, db) -> None:
        rejected = BillingFetch(400, {**_ENVELOPE, "error": "invalid_param"}, "HTTP 400")
        read = _read(db, lambda from_id, limit: rejected)
        assert read.failure is rejected and open_gaps(db, _PERIOD) == []


class TestGapLifecycle:
    def test_a_later_read_of_the_position_resolves_the_gap(self, db) -> None:
        poison = 70714319000
        _read(db, _Ml(_IDS, poison=[poison]), from_id=70714313970, limit=1)
        later = datetime(2026, 10, 9, tzinfo=timezone.utc)
        # Another row of the page does not resolve it; the poison row itself does.
        assert (
            resolve_recovered_gaps(
                db, period_key=_PERIOD, document_type="BILL", detail_ids=[70714319001], read_from_id=0, now=later
            )
            == 0
        )
        assert open_gaps(db, _PERIOD)
        assert (
            resolve_recovered_gaps(
                db, period_key=_PERIOD, document_type="BILL", detail_ids=[poison], read_from_id=0, now=later
            )
            == 1
        )
        assert open_gaps(db, _PERIOD) == []

    def test_a_page_that_does_not_cover_the_window_does_not_resolve_it(self, db) -> None:
        # P1 and P2 are not adjacent: the sparse probe skips the good row between them.
        x, p1, good, p2 = 70714313970, 70714319000, 70714319001, 70714360000
        ml = _Ml([*_IDS], poison=[p1, p2])
        read = _read(db, ml, from_id=x, limit=1)
        [gap] = open_gaps(db, _PERIOD)
        assert read.gaps == (p2,) and good not in _ids(read.page) and gap.window == f"({x}, {p2}]"
        later = datetime(2026, 10, 9, tzinfo=timezone.utc)
        kw = dict(period_key=_PERIOD, document_type="BILL", detail_ids=[p2], now=later)
        # A page that starts inside the window (so it misses `good`) leaves it open.
        assert resolve_recovered_gaps(db, read_from_id=p1, **kw) == 0 and open_gaps(db, _PERIOD)
        # A page that starts at the window start holds every row of the window.
        assert resolve_recovered_gaps(db, read_from_id=x, **kw) == 1

    def test_a_missing_row_keeps_the_document_incomplete(self, db) -> None:
        db.add(
            MlBillingDocument(
                document_id="DOC",
                period_key=_PERIOD,
                document_type="BILL",
                group="ML",
                count_details=3,
                amount=30,
                raw={},
            )
        )
        for detail_id in (70714313970, 70714319001):
            db.add(
                MlBillingCharge(
                    detail_id=str(detail_id),
                    period_key=_PERIOD,
                    document_id="DOC",
                    document_type="BILL",
                    detail_type="CHARGE",
                    amount=10,
                )
            )
        db.commit()
        _read(db, _Ml(_IDS, poison=[70714319000]), from_id=70714313970, limit=1)
        db.commit()
        # The gap is a pointer, never a substitute: the document is still incomplete.
        [doc] = document_completeness(db, _PERIOD, "BILL")
        assert (doc.complete, doc.stored_count, doc.expected_count) == (False, 2, 3) and open_gaps(db, _PERIOD)
        # The row comes back: it is stored, the gap resolves, the document closes.
        db.add(
            MlBillingCharge(
                detail_id="70714319000",
                period_key=_PERIOD,
                document_id="DOC",
                document_type="BILL",
                detail_type="CHARGE",
                amount=10,
            )
        )
        resolve_recovered_gaps(
            db, period_key=_PERIOD, document_type="BILL", detail_ids=[70714319000], read_from_id=0, now=_NOW
        )
        db.commit()
        [doc] = document_completeness(db, _PERIOD, "BILL")
        assert doc.complete and open_gaps(db, _PERIOD) == []

"""ml-billing-balance PR 4a-iv -- the offset poison engine (flex details, BS-7).

Flex `/details` pages by `offset` (limit 500) and ML answers intermittent bare
400s. A read at `offset=O, limit=1` returns exactly row O, so halving the limit
at the same offset finds the poison offset with no probing. `_Ml` replays the
captured shape (`captured_flex_offset_pages.json`) and the captured 400 envelope.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.services.ml_billing.offset_poison_rows import read_offset_page_skipping_poison, resolve_recovered_offset_gaps
from app.services.ml_billing.poison_rows import resolve_recovered_gaps
from app.services.ml_billing.sweep_gaps import open_gaps, record_gap
from app.services.ml_webhook_client import BillingFetch

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing"
_ENVELOPE = json.loads((_FIXTURES / "captured_400_envelope.json").read_text())
_CAPTURE = json.loads((_FIXTURES / "captured_flex_offset_pages.json").read_text())
_BARE_400 = BillingFetch(400, _ENVELOPE, "HTTP 400")
_PERIOD = "2026-10-01"
_NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
_TOTAL = _CAPTURE["pages"][0]["total"]  # 3324, as ML reported it


class _Ml:
    """Rows are the offsets 0.._TOTAL-1; a page holding a poison offset is a bare 400."""

    def __init__(self, poison=(), flaky_first=0, total=_TOTAL):
        self.poison, self.flaky, self.total = set(poison), flaky_first, total
        self.calls: list[tuple[int, int]] = []

    def __call__(self, offset, limit):
        self.calls.append((offset, limit))
        if self.flaky:
            self.flaky -= 1
            return _BARE_400
        rows = list(range(offset, min(offset + limit, self.total)))
        if self.poison & set(rows):
            return _BARE_400
        return BillingFetch(200, {"offset": offset, "limit": limit, "total": self.total, "results": rows}, None)


def _read(db, fetch, offset=0, limit=500, **kw):
    return read_offset_page_skipping_poison(
        db, fetch=fetch, period_key=_PERIOD, document_type="CREDIT_NOTE", offset=offset, limit=limit, now=_NOW, **kw
    )


def _sweep(db, ml, limit=500):
    """A minimal driver: persist what the engine returns, advance, repeat."""
    seen, offset = [], 0
    for _ in range(2000):
        read = _read(db, ml, offset=offset, limit=limit)
        assert read.failure is None
        if read.page is not None:
            if not read.page["results"]:
                return seen
            seen += read.page["results"]
            resolve_recovered_offset_gaps(
                db,
                period_key=_PERIOD,
                document_type="CREDIT_NOTE",
                read_offset=offset,
                n_results=len(read.page["results"]),
                now=_NOW,
            )
        offset = read.offset if read.page is None else offset + len(read.page["results"])
    raise AssertionError("the sweep did not terminate")


class TestEngine:
    def test_the_captured_pages_are_contiguous_offset_pages(self) -> None:
        pages = _CAPTURE["pages"]
        assert [p["offset"] for p in pages] == [0, 500, 1000, 1500, 2000, 2500, 3000]
        assert pages[-1]["n_results"] == 325 and {p["limit"] for p in pages} == {500}

    def test_a_clean_page_costs_one_call_and_no_gap(self, db) -> None:
        ml = _Ml()
        read = _read(db, ml, offset=500)
        assert len(read.page["results"]) == 500 and read.gaps == () and ml.calls == [(500, 500)]
        assert open_gaps(db, _PERIOD) == []

    def test_an_intermittent_400_is_retried_once_at_the_same_size(self, db) -> None:
        ml = _Ml(flaky_first=1)
        assert len(_read(db, ml).page["results"]) == 500
        assert ml.calls == [(0, 500), (0, 500)] and open_gaps(db, _PERIOD) == []

    def test_a_non_bare_failure_stops_without_a_gap(self, db) -> None:
        read = _read(db, lambda o, n: BillingFetch(429, None, "HTTP 429"))
        assert read.failure.status == 429 and read.page is None and read.gaps == ()
        assert open_gaps(db, _PERIOD) == []

    def test_the_limit_is_halved_and_a_good_prefix_is_returned(self, db) -> None:
        ml = _Ml(poison=[5])
        read = _read(db, ml, limit=8)
        assert [n for _, n in ml.calls] == [8, 8, 4]
        assert read.page["results"] == [0, 1, 2, 3]
        assert open_gaps(db, _PERIOD) == []

    def test_the_exact_poison_offset_is_recorded_and_stepped_over(self, db) -> None:
        ml, offset = _Ml(poison=[1203]), 1000
        read = _read(db, ml, offset=offset)
        while read.page is not None:  # good prefixes first, each narrower than the last
            offset += len(read.page["results"])
            assert offset <= 1203
            read = _read(db, ml, offset=offset)
        assert offset == 1203 and read.failure is None and read.gaps == (1203,) and read.offset == 1204
        [gap] = open_gaps(db, _PERIOD, "CREDIT_NOTE")
        assert (gap.position, gap.paging, gap.billing_source, gap.http_status) == ("1203", "offset", "flex", 400)
        assert gap.window == "[1203, 1203]" and json.loads(gap.error) == _ENVELOPE

    def test_a_spurious_400_at_limit_one_does_not_record_a_phantom_gap(self, db) -> None:
        ml = _Ml(flaky_first=3)  # limit 2, its retry and the first limit-1 call
        read = _read(db, ml, limit=2)
        assert read.gaps == () and read.page["results"] == [0] and open_gaps(db, _PERIOD) == []

    def test_adjacent_poison_offsets_each_get_their_own_exact_gap(self, db) -> None:
        seen = _sweep(db, _Ml(poison=[40, 41, 42]), limit=64)
        assert [g.position for g in open_gaps(db, _PERIOD)] == ["40", "41", "42"]
        assert seen == [i for i in range(_TOTAL) if i not in (40, 41, 42)]

    def test_the_whole_period_is_swept_around_poison_offsets_at_limit_500(self, db) -> None:
        ml = _Ml(poison=[7, 1999, _TOTAL - 1])
        seen = _sweep(db, ml)
        assert seen == [i for i in range(_TOTAL) if i not in (7, 1999, _TOTAL - 1)]
        assert [g.position for g in open_gaps(db, _PERIOD)] == ["7", "1999", str(_TOTAL - 1)]
        assert len(ml.calls) < 200  # halving per poison offset (~40 calls each), not a scan of 3,324 rows


class TestGapLifecycle:
    def test_a_gap_closes_when_a_page_covering_its_offset_reads_clean(self, db) -> None:
        _sweep(db, _Ml(poison=[1203]))
        assert [g.position for g in open_gaps(db, _PERIOD)] == ["1203"]
        _sweep(db, _Ml())  # ML recovered: the same sweep reads offset 1203
        assert open_gaps(db, _PERIOD) == []

    def test_a_page_that_does_not_cover_the_offset_does_not_close_it(self, db) -> None:
        _sweep(db, _Ml(poison=[1203]))
        for read_offset, n in ((0, 1203), (1204, 500)):  # ends before / starts after
            assert (
                resolve_recovered_offset_gaps(
                    db, period_key=_PERIOD, document_type="CREDIT_NOTE", read_offset=read_offset, n_results=n, now=_NOW
                )
                == 0
            )
        assert [g.position for g in open_gaps(db, _PERIOD)] == ["1203"]

    def test_only_offset_flex_gaps_are_touched_by_each_resolver(self, db) -> None:
        record_gap(
            db,
            period_key=_PERIOD,
            document_type="CREDIT_NOTE",
            billing_source="general",
            paging="from_id",
            position="10",
            window="(0, 10]",
            http_status=400,
            error=None,
            now=_NOW,
        )
        assert (
            resolve_recovered_offset_gaps(
                db, period_key=_PERIOD, document_type="CREDIT_NOTE", read_offset=0, n_results=500, now=_NOW
            )
            == 0
        )
        _sweep(db, _Ml(poison=[10]))
        assert (
            resolve_recovered_gaps(
                db, period_key=_PERIOD, document_type="CREDIT_NOTE", detail_ids=[10], read_from_id=0, now=_NOW
            )
            == 1
        )
        assert [g.paging for g in open_gaps(db, _PERIOD)] == ["offset"]

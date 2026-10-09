"""ml-billing-balance PR 5-ii -- the flex offset poison probe as a step machine (one request per step).

State is plain JSON (it will live in the lap's unit state), so every step round-trips it
through `json`. `_Ml` replays the measured flex shape: rows are positions 0..total-1,
a page holding a poison position is the captured bare 400 envelope. The poison
positions and totals below are DERIVED (the capture stopped at its 400 and holds no
rows after it); the envelope and the 3324 total are captured.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.ml_billing.offset_poison_probe import advance, new_probe, next_request
from app.services.ml_webhook_client import BillingFetch

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing"
_ENVELOPE = json.loads((_FIXTURES / "captured_400_envelope.json").read_text())
_BARE_400 = BillingFetch(400, _ENVELOPE, "HTTP 400")
_TOTAL = json.loads((_FIXTURES / "captured_flex_offset_pages.json").read_text())["pages"][0]["total"]


class _Ml:
    def __init__(self, poison=(), flaky_first=0, total=_TOTAL):
        self.poison, self.flaky, self.total, self.calls = set(poison), flaky_first, total, []

    def __call__(self, offset, limit):
        self.calls.append((offset, limit))
        if self.flaky:
            self.flaky -= 1
            return _BARE_400
        rows = list(range(offset, min(offset + limit, self.total)))
        if self.poison & set(rows):
            return _BARE_400
        return BillingFetch(200, {"offset": offset, "limit": limit, "total": self.total, "results": rows}, None)


def _run(probe, ml):
    """Drives the machine to its end, one request per step, the state through JSON."""
    for _ in range(100):
        probe = json.loads(json.dumps(probe))
        step = advance(probe, ml(*next_request(probe)))
        if step.kind != "next":
            return step
    raise AssertionError("the probe did not end")


def test_a_clean_read_is_a_page_in_one_request() -> None:
    ml = _Ml()
    step = _run(new_probe(500, 500), ml)
    assert step.kind == "page" and len(step.page["results"]) == 500 and ml.calls == [(500, 500)]


def test_one_flaky_400_is_retried_and_never_becomes_a_gap() -> None:
    ml = _Ml(flaky_first=1)
    step = _run(new_probe(0, 500), ml)
    assert step.kind == "page" and ml.calls == [(0, 500), (0, 500)]


def test_a_poison_position_is_isolated_by_halving_the_limit_at_the_same_offset() -> None:
    ml = _Ml(poison=[1500])
    step = _run(new_probe(1500, 500), ml)
    assert (step.kind, step.position, step.window) == ("gap", 1500, "[1500, 1500]")
    assert step.error == {"status": 400, "body": _ENVELOPE}
    # 500 twice (retry), 250, 125, 62, 31, 15, 7, 3, 1 (verdict, retried once)
    assert [limit for _, limit in ml.calls] == [500, 500, 250, 125, 62, 31, 15, 7, 3, 1, 1]
    assert {offset for offset, _ in ml.calls} == {1500}


def test_a_poison_row_inside_the_page_yields_the_prefix_as_a_page_first() -> None:
    ml = _Ml(poison=[1507])
    step = _run(new_probe(1500, 500), ml)
    assert step.kind == "page" and step.page["results"] == list(range(1500, 1507))


def test_the_probe_resumes_after_the_gap_with_the_next_offset() -> None:
    ml = _Ml(poison=[1500])
    assert _run(new_probe(1500, 500), ml).position == 1500
    step = _run(new_probe(1501, 500), ml)  # derived post-gap page: captured rows after the 400 do not exist
    assert step.kind == "page" and step.page["results"][0] == 1501


def test_consecutive_poison_positions_each_get_their_own_gap() -> None:
    ml = _Ml(poison=[10, 11])
    first = _run(new_probe(10, 500), ml)
    second = _run(new_probe(first.position + 1, 500), ml)
    assert (first.position, second.position) == (10, 11)


def test_a_limit_one_read_is_retried_once_then_it_is_the_gap() -> None:
    ml = _Ml(poison=[7])
    step = _run(new_probe(7, 1), ml)
    assert step.kind == "gap" and ml.calls == [(7, 1), (7, 1)]


def test_a_failure_that_is_not_a_bare_400_stops_without_a_gap() -> None:
    probe = new_probe(0, 500)
    for result in (BillingFetch(429, {"message": "slow"}, "HTTP 429"), BillingFetch(502, None, "HTTP 502")):
        step = advance(dict(probe), result)
        assert step.kind == "failure" and step.failure is result
    named = BillingFetch(400, {"message": "bad period", "error": "x", "status": 400}, "HTTP 400")
    assert advance(dict(probe), named).kind == "failure"

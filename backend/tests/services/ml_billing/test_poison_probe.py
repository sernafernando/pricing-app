"""ml-billing-balance PR 4c-v -- the poison probe as a step machine (one request per step).

The probe state is plain JSON (it lives in the lap's unit state), so every step
here round-trips it through `json`. `_Ml` replays the measured API: `from_id` is
exclusive, ids ascend, a page holding the poison row is the captured bare 400.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.ml_billing.poison_probe import advance, new_probe, next_request
from app.services.ml_webhook_client import BillingFetch

_ENVELOPE = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing" / "captured_400_envelope.json").read_text()
)
_BARE_400 = BillingFetch(400, _ENVELOPE, "HTTP 400")
_IDS = [70714313961, 70714313962, 70714313970, 70714319000, 70714319001, 70714360000, 70714360005]


class _Ml:
    def __init__(self, ids, poison=(), flaky_first=0):
        self.ids, self.poison, self.flaky, self.calls = sorted(ids), set(poison), flaky_first, []

    def __call__(self, position, limit):
        self.calls.append((position, limit))
        if self.flaky:
            self.flaky -= 1
            return _BARE_400
        rows = [i for i in self.ids if i > position][:limit]
        if self.poison & set(rows):
            return _BARE_400
        return BillingFetch(200, {"results": [{"charge_info": {"detail_id": i}} for i in rows]}, None)


def _run(probe, ml, bound=None):
    """Drives the machine to its end, one request per step, the state through JSON."""
    for _ in range(400):
        probe = json.loads(json.dumps(probe))
        step = advance(probe, ml(*next_request(probe)))
        if step.kind != "next":
            return step
    raise AssertionError("the probe did not end")


def test_the_probe_finds_the_exact_poison_id_one_request_per_step() -> None:
    poison = 70714319000
    ml = _Ml(_IDS, poison=[poison])
    step = _run(new_probe(70714313970, 1), ml)
    assert (step.kind, step.position, step.window) == ("gap", poison, f"(70714313970, {poison}]")
    assert step.error == {"status": 400, "body": _ENVELOPE}
    assert len(ml.calls) <= 2 + 2 * 2 * 13 + 1


def test_a_narrowed_page_is_returned_as_a_page() -> None:
    ml = _Ml(_IDS, poison=[70714319000])
    step = _run(new_probe(0, 8), ml)
    assert step.kind == "page" and [limit for _, limit in ml.calls] == [8, 8, 4, 2]


def test_an_intermittent_400_is_retried_once_at_the_same_position() -> None:
    ml = _Ml(_IDS, flaky_first=1)
    step = _run(new_probe(0, 1000), ml)
    assert step.kind == "page" and ml.calls == [(0, 1000), (0, 1000)]


def test_a_spurious_400_inside_the_probe_does_not_skip_good_rows() -> None:
    x, poison, spurious = 70714313970, 70714319000, []
    ml = _Ml(_IDS, poison=[poison])

    def fetch(position, limit):
        if position == x + 6144 and not spurious:
            spurious.append(position)
            return _BARE_400
        return ml(position, limit)

    step = _run(new_probe(x, 1), fetch)
    assert spurious and step.position == poison


def test_consecutive_poison_rows_are_covered_by_one_window_from_the_cursor() -> None:
    x, last = 70714313970, 70714319001
    step = _run(new_probe(x, 1), _Ml(_IDS, poison=[70714319000, last]))
    assert (step.position, step.window) == (last, f"({x}, {last}]")


def test_a_400_that_never_isolates_gives_a_bound_window() -> None:
    step = _run(new_probe(10, 1, bound=2**10), lambda *_: _BARE_400)
    assert (step.kind, step.position, step.window) == ("gap", 10 + 2**10, f"(10, {10 + 2**10}]")


def test_a_failure_that_is_not_a_poison_row_stops_the_probe() -> None:
    outage = BillingFetch(429, {}, "HTTP 429")
    probe = new_probe(0, 1)
    assert advance(probe, _BARE_400).kind == "next"  # the first 400 is retried
    assert advance(probe, _BARE_400).kind == "next"  # the verdict moves on to the probes
    step = advance(probe, outage)
    assert step.kind == "failure" and step.failure is outage

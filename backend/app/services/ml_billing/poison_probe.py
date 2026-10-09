"""The poison probe of the general `/details` sweep as a step machine (BS-7, ml-billing-balance PR 4c-v).

`poison_rows` documents the strategy (retry, halve the limit, exponential then
binary `from_id` probe). This module is the same strategy cut into STEPS of one
request each, so the billing lap can spend one request per worker tick and keep
the probe in its JSON unit state instead of blocking the worker for the 40-70
requests a poison row costs.

The state is a plain dict (`new_probe`); `next_request(probe)` says what to ask
and `advance(probe, result)` feeds the answer back and returns a `Step`. The
three rules that cost real debugging are kept as they are:

1. the window is `(cursor, poison]`, so consecutive poison rows are covered;
2. every probe is retried once on a bare 400 (and so is the first read and the
   limit-1 verdict, but not the intermediate halvings);
3. a gap closes elsewhere, only by a page that started at or before the window.

The machine does no I/O and never sleeps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services.ml_webhook_client import BillingFetch

POISON_PROBE_BOUND = 2**40
NARROW, EXPAND, BISECT = "narrow", "expand", "bisect"


@dataclass(frozen=True)
class Step:
    """`next`: ask `next_request` again. `page`: a narrowed read succeeded (a
    good page at the cursor). `failure`: not a poison row, stop and retry later.
    `gap`: the poison row at `position` was isolated (`error` is the last 400)."""

    kind: str
    page: Optional[dict] = None
    failure: Optional[BillingFetch] = None
    position: Optional[int] = None
    window: Optional[str] = None
    error: Optional[dict] = None


_NEXT = Step("next")


def new_probe(from_id: int, limit: int, bound: int = POISON_PROBE_BOUND) -> dict:
    return {
        "from_id": int(from_id),
        "limit": limit,
        "bound": bound,
        "phase": NARROW,
        "size": limit,
        "retried": False,
        "step": 1,
        "lo": 0,
        "hi": None,
        "last_400": None,
    }


def next_request(probe: dict) -> tuple[int, int]:
    """(`from_id`, `limit`) of the next request."""
    x, phase = probe["from_id"], probe["phase"]
    if phase == NARROW:
        return x, probe["size"]
    if phase == EXPAND:
        return x + probe["step"], 1
    return x + (probe["lo"] + probe["hi"]) // 2, 1


def _gap(probe: dict, position: int) -> Step:
    return Step("gap", position=position, window=f"({probe['from_id']}, {position}]", error=probe["last_400"])


def advance(probe: dict, result: BillingFetch) -> Step:
    """Applies the answer to the request `next_request` named. Mutates `probe`."""
    phase = probe["phase"]
    if result.ok:
        probe["retried"] = False
        if phase == NARROW:
            return Step("page", page=result.body)
        probe["hi"] = probe["step"] if phase == EXPAND else (probe["lo"] + probe["hi"]) // 2
        return _after_bracket(probe)
    if not result.is_bare_400:
        return Step("failure", failure=result)
    # A first read and the limit-1 verdict are retried; so is every probe.
    retriable = phase != NARROW or probe["size"] in (probe["limit"], 1)
    if retriable and not probe["retried"]:
        probe["retried"] = True
        return _NEXT
    probe["retried"] = False
    last = {"status": result.status, "body": result.body}
    if phase == NARROW:
        if probe["size"] > 1:
            probe["size"] //= 2
        else:
            probe.update(phase=EXPAND, last_400=last)
        return _NEXT
    probe["last_400"] = last
    if phase == EXPAND:
        probe["lo"], probe["step"] = probe["step"], probe["step"] * 2
        if probe["step"] > probe["bound"]:  # a 400 that is not about a row: the bound is the window
            return _gap(probe, probe["from_id"] + probe["bound"])
        return _NEXT
    probe["lo"] = (probe["lo"] + probe["hi"]) // 2
    return _after_bracket(probe)


def _after_bracket(probe: dict) -> Step:
    if probe["hi"] - probe["lo"] <= 1:
        return _gap(probe, probe["from_id"] + probe["hi"])
    probe["phase"] = BISECT
    return _NEXT

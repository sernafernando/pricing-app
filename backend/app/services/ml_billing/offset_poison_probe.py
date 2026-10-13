"""The flex offset poison probe as a step machine (ml-billing-balance PR 5-ii).

`offset_poison_rows` documents the strategy for flex `/details` (paged by
`offset`): a read at `offset=O, limit=1` is exactly row O, so the poison position
is found by halving `limit` at the SAME offset, with no probing. This module is
that strategy cut into steps of one request each, like `poison_probe` does for
`from_id`, so the billing lap can spend one request per worker tick and keep the
probe in its JSON unit state. It reuses `poison_probe.Step`.

The retry rule is the one of `poison_rows.narrow_bare_400`: the first read and the
limit-1 verdict are retried once on a bare 400, the intermediate halvings are not.
A `page` step can be a narrowed prefix (fewer rows than `limit`): the caller
advances by `len(page["results"])`. A `gap` step names the poisoned position
(window `[O, O]`); the caller records it and resumes at `O + 1`.

The machine does no I/O and never sleeps, and it is NOT wired into any sweep yet.
"""

from __future__ import annotations

from app.services.ml_billing.poison_probe import Step
from app.services.ml_webhook_client import BillingFetch

_NEXT = Step("next")


def new_probe(offset: int, limit: int) -> dict:
    return {"offset": int(offset), "limit": limit, "size": limit, "retried": False}


def next_request(probe: dict) -> tuple[int, int]:
    """(`offset`, `limit`) of the next request."""
    return probe["offset"], probe["size"]


def advance(probe: dict, result: BillingFetch) -> Step:
    """Applies the answer to the request `next_request` named. Mutates `probe`."""
    if result.ok:
        probe["retried"] = False
        return Step("page", page=result.body)
    if not result.is_bare_400:
        return Step("failure", failure=result)
    if probe["size"] in (probe["limit"], 1) and not probe["retried"]:
        probe["retried"] = True
        return _NEXT
    probe["retried"] = False
    if probe["size"] > 1:
        probe["size"] //= 2
        return _NEXT
    offset = probe["offset"]
    return Step(
        "gap",
        position=offset,
        window=f"[{offset}, {offset}]",
        error={"status": result.status, "body": result.body},
    )

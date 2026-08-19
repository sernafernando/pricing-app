"""Sequential batch execution with 429-aware adaptive-delay backoff (R1/PC10).

**Batch is the only execution path** (design Decision 6): a single-item
publish is `execute_batch([item])` — there is no second code path for bulk
to grow into.

A 429 is a *rejection* — nothing was created — categorically different from
the ambiguous 5xx/timeout `tn_publish_service.publish_product` must never
blind-retry (see that module's docstring). `TnRateLimited` is caught and
retried HERE, honouring `Retry-After` when TN sends it, else an exponential
1/2/4/8s backoff, up to `MAX_RATE_LIMIT_ATTEMPTS`. Once a 429 has been
observed, the inter-item delay for the REMAINDER of the batch increases too
(adaptive delay) instead of reverting to zero on the very next item.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from app.services.tienda_nube_product_client import TnRateLimited

logger = logging.getLogger(__name__)

DEFAULT_BACKOFF_STEPS = (1.0, 2.0, 4.0, 8.0)
MAX_RATE_LIMIT_ATTEMPTS = 4
# `Retry-After` is honoured but never verbatim: a misbehaving/proxy-mangled
# header (e.g. 3600) must not park the whole batch on a synchronous sleep.
RETRY_AFTER_CAP_SECONDS = 60.0


@dataclass
class ItemOutcome:
    ean: str
    status: str
    detail: Optional[str] = None
    product_id: Optional[int] = None


def execute_batch(
    items: List[Any],
    publish_fn: Callable[[Any], dict],
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    ean_of: Callable[[Any], str] = lambda item: item["ean"],
) -> List[ItemOutcome]:
    """Runs `publish_fn` once per item, sequentially (TN's Weighted Token
    Bucket makes concurrency a guaranteed 429 storm — see design Decision
    6). Only `TnRateLimited` is handled here: every 429-resolved item gets
    an `ItemOutcome`. Any OTHER exception from `publish_fn` propagates
    immediately and the outcomes of already-processed items are discarded
    with it — deliberate, mirroring the no-blind-retry rule for ambiguous
    failures (a caller needing partial results must make `publish_fn`
    return them as outcome dicts instead of raising)."""
    outcomes: List[ItemOutcome] = []
    inter_item_delay = 0.0

    for item in items:
        ean = ean_of(item)
        if inter_item_delay:
            sleep_fn(inter_item_delay)

        attempt = 0
        while True:
            try:
                result = publish_fn(item)
                outcomes.append(
                    ItemOutcome(
                        ean=ean,
                        status=result.get("status", "submitted"),
                        product_id=result.get("product_id"),
                        detail=result.get("detail"),
                    )
                )
                break
            except TnRateLimited as exc:
                if attempt >= MAX_RATE_LIMIT_ATTEMPTS:
                    logger.warning("execute_batch: ean=%s exhausted rate-limit retries", ean)
                    outcomes.append(ItemOutcome(ean=ean, status="rate_limited", detail=str(exc)))
                    break
                wait = (
                    min(exc.retry_after, RETRY_AFTER_CAP_SECONDS)
                    if exc.retry_after
                    else DEFAULT_BACKOFF_STEPS[min(attempt, len(DEFAULT_BACKOFF_STEPS) - 1)]
                )
                sleep_fn(wait)
                inter_item_delay = max(inter_item_delay, wait)
                attempt += 1
                continue

    return outcomes

"""Unit tests for the 429-aware batch executor (R1/PC10).

Uses a fake `sleep_fn` throughout — NEVER a real 2s sleep — per the strict
TDD instructions for this slice.
"""

from app.services.tienda_nube_product_client import TnRateLimited
from app.services.tn_publish_core.batch import RETRY_AFTER_CAP_SECONDS, execute_batch


class _FakeSleep:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


class TestSingleItemIsABatchOfOne:
    """PC10/R1, design Decision 6 — no second code path for bulk to grow
    into."""

    def test_single_item_publish_runs_through_execute_batch(self):
        calls = []

        def publish_fn(item):
            calls.append(item)
            return {"status": "submitted", "product_id": 123}

        outcomes = execute_batch([{"ean": "111"}], publish_fn, sleep_fn=_FakeSleep())

        assert len(calls) == 1
        assert len(outcomes) == 1
        assert outcomes[0].ean == "111"
        assert outcomes[0].status == "submitted"
        assert outcomes[0].product_id == 123

    def test_multi_item_batch_calls_publish_fn_once_per_item_same_code_path(self):
        calls = []

        def publish_fn(item):
            calls.append(item["ean"])
            return {"status": "submitted", "product_id": len(calls)}

        outcomes = execute_batch([{"ean": "111"}, {"ean": "222"}, {"ean": "333"}], publish_fn, sleep_fn=_FakeSleep())

        assert calls == ["111", "222", "333"]
        assert [o.status for o in outcomes] == ["submitted", "submitted", "submitted"]


class TestRateLimitDistinctFromAmbiguousNoRetryRule:
    """Required per the proposal's risk table (task 5.15) — a 429 with
    `Retry-After: 2` waits >= 2s and CONTINUES the batch. This is
    categorically distinct from the existing no-blind-retry rule for
    ambiguous 5xx/timeout on `publish_product`: THAT rule never retries
    because the outcome is unknown; a 429 is a definitive rejection (nothing
    was created), so waiting and retrying it is safe by construction."""

    def test_429_with_retry_after_waits_at_least_2s_and_continues_the_batch(self):
        attempts = {"111": 0}

        def publish_fn(item):
            ean = item["ean"]
            if ean == "111" and attempts[ean] == 0:
                attempts[ean] += 1
                raise TnRateLimited(retry_after=2)
            return {"status": "submitted", "product_id": 1}

        sleep_fn = _FakeSleep()
        outcomes = execute_batch([{"ean": "111"}], publish_fn, sleep_fn=sleep_fn)

        assert sleep_fn.calls, "execute_batch must have waited before retrying"
        assert sleep_fn.calls[0] >= 2
        assert outcomes[0].status == "submitted"

    def test_ambiguous_5xx_style_failure_is_never_retried_by_execute_batch(self):
        """`execute_batch` only retries `TnRateLimited` — any other
        exception from `publish_fn` (e.g. the ambiguous timeout/5xx
        `publish_product` itself decides never to retry) is NOT caught or
        retried here; it propagates, proving the two failure classes are
        handled by entirely different code paths."""
        calls = []

        def publish_fn(item):
            calls.append(item["ean"])
            raise RuntimeError("ambiguous TN 5xx/timeout — never blind-retried")

        try:
            execute_batch([{"ean": "111"}], publish_fn, sleep_fn=_FakeSleep())
            raised = False
        except RuntimeError:
            raised = True

        assert raised is True
        assert calls == ["111"]  # exactly one attempt, no retry loop

    def test_adaptive_delay_increases_for_remainder_of_batch_after_a_429(self):
        attempted = {"111": False}

        def publish_fn(item):
            if item["ean"] == "111" and not attempted["111"]:
                attempted["111"] = True
                raise TnRateLimited(retry_after=2)
            return {"status": "submitted"}

        sleep_fn = _FakeSleep()
        execute_batch([{"ean": "111"}, {"ean": "222"}], publish_fn, sleep_fn=sleep_fn)

        # First call: the 2s backoff wait before retrying item 111.
        # Second call: the adaptive inter-item delay before item 222 — must
        # also be >= the observed 429 wait, not reset to zero.
        assert len(sleep_fn.calls) == 2
        assert sleep_fn.calls[1] >= 2

    def test_rate_limit_exhaustion_reports_rate_limited_status_and_stops_retrying(self):
        def publish_fn(item):
            raise TnRateLimited(retry_after=0.01)

        sleep_fn = _FakeSleep()
        outcomes = execute_batch([{"ean": "111"}], publish_fn, sleep_fn=sleep_fn)

        assert outcomes[0].status == "rate_limited"

    def test_absurd_retry_after_is_capped_never_slept_verbatim(self):
        # A misbehaving/proxy-mangled `Retry-After: 3600` must not park the
        # batch for an hour on a synchronous sleep.
        attempts = {"111": 0}

        def publish_fn(item):
            if attempts["111"] == 0:
                attempts["111"] += 1
                raise TnRateLimited(retry_after=3600)
            return {"status": "submitted", "product_id": 1}

        sleep_fn = _FakeSleep()
        outcomes = execute_batch([{"ean": "111"}], publish_fn, sleep_fn=sleep_fn)

        assert outcomes[0].status == "submitted"
        assert max(sleep_fn.calls) <= RETRY_AFTER_CAP_SECONDS

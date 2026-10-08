"""Tests for the read-only replenishment capture script (pubml P4a.T1).

The script talks to the real ML API with a real token, so what must be proven here is the
safety envelope: GET only, paced, backs off on 429, never lets a credential reach the output
and keeps only the whitelisted response headers. The ML payload itself is NOT asserted: it is
what the capture is for (never hand-write that fixture).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import List

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ml_capture_replenishment.py"
_spec = importlib.util.spec_from_file_location("ml_capture_replenishment", SCRIPT)
cap = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cap  # dataclasses resolve their module through sys.modules
_spec.loader.exec_module(cap)

TOKEN = "APP_USR-123456789-secret-token-value"
CALLER_ID = "424242"


class FakeClock:
    """Deterministic clock: `sleep` advances `now`, so pacing is observable without waiting."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: List[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_capture(handler, clock=None, **kwargs):
    clock = clock or FakeClock()
    client = httpx.Client(base_url="https://api.mercadolibre.com", transport=httpx.MockTransport(handler))
    capture = cap.ReplenishmentCapture(
        client=client,
        token=TOKEN,
        caller_id=CALLER_ID,
        site_id="MLA",
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        **kwargs,
    )
    return capture, clock


def ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"sales": {}}, headers={"date": "Thu, 08 Oct 2026 10:00:00 GMT"})


class TestResponseHeaderWhitelist:
    def test_keeps_only_date_and_x_content_missing(self):
        kept = cap.filter_response_headers(
            {
                "Date": "Thu, 08 Oct 2026 10:00:00 GMT",
                "X-Content-Missing": "sales_history",
                "Set-Cookie": "_d2id=abc",
                "Authorization": f"Bearer {TOKEN}",
                "x-request-id": "r-1",
                "Content-Type": "application/json",
            }
        )
        assert kept == {"date": "Thu, 08 Oct 2026 10:00:00 GMT", "x-content-missing": "sales_history"}

    def test_the_captured_record_carries_only_whitelisted_headers(self):
        def handler(request):
            return httpx.Response(
                206,
                json={"sales": {}},
                headers={"x-content-missing": "sales_history", "set-cookie": "s=1", "x-request-id": "r"},
            )

        capture, _ = make_capture(handler)
        record = capture.capture("full", "MLAU1", with_caller=True)
        assert set(record["response_headers"]) <= {"date", "x-content-missing"}
        assert record["response_headers"]["x-content-missing"] == "sales_history"


class TestCredentialsNeverReachTheOutput:
    def test_redact_masks_sensitive_keys_and_literal_secret_values(self):
        out = cap.redact(
            {
                "authorization": f"Bearer {TOKEN}",
                "access_token": TOKEN,
                "nested": {"note": f"echo {TOKEN} back", "ok": 1},
                "list": [TOKEN, "fine"],
            },
            secrets=[TOKEN],
        )
        dumped = json.dumps(out)
        assert TOKEN not in dumped
        assert out["authorization"] == cap.REDACTED
        assert out["access_token"] == cap.REDACTED
        assert out["nested"]["ok"] == 1
        assert out["list"][1] == "fine"

    def test_a_body_that_echoes_the_token_is_redacted_in_the_record(self):
        def handler(request):
            return httpx.Response(403, json={"message": f"invalid {TOKEN}", "error": "forbidden"})

        capture, _ = make_capture(handler)
        record = capture.capture("full", "MLAU1", with_caller=True)
        assert TOKEN not in json.dumps(record)
        assert record["status"] == 403

    def test_the_record_never_holds_the_authorization_header(self):
        capture, _ = make_capture(ok_handler)
        record = capture.capture("full", "MLAU1", with_caller=True)
        dumped = json.dumps(record).lower()
        assert TOKEN.lower() not in dumped
        assert "bearer" not in dumped
        assert "authorization" not in dumped

    def test_a_transport_error_message_is_redacted(self):
        def handler(request):
            raise httpx.ConnectError(f"boom {TOKEN}")

        capture, _ = make_capture(handler)
        record = capture.capture("full", "MLAU1", with_caller=True)
        assert record["status"] == 0
        assert TOKEN not in json.dumps(record)


class TestReadOnlyAndCallerHeaders:
    def test_only_get_requests_are_sent(self):
        seen = []

        def handler(request):
            seen.append(request.method)
            return ok_handler(request)

        capture, _ = make_capture(handler)
        capture.capture("a", "MLAU1", with_caller=True)
        capture.capture("b", "MLAU1", with_caller=False)
        assert seen == ["GET", "GET"]

    def test_path_and_country_param(self):
        seen = []

        def handler(request):
            seen.append(request.url)
            return ok_handler(request)

        capture, _ = make_capture(handler)
        capture.capture("a", "MLAU999", with_caller=True)
        assert seen[0].path == "/marketplace/fbm/user-products/MLAU999/replenishment"
        assert seen[0].params["country"] == "AR"

    def test_caller_headers_are_sent_only_when_requested(self):
        seen = []

        def handler(request):
            seen.append(dict(request.headers))
            return ok_handler(request)

        capture, _ = make_capture(handler)
        with_caller = capture.capture("a", "MLAU1", with_caller=True)
        without = capture.capture("b", "MLAU1", with_caller=False)

        assert seen[0]["x-caller-id"] == CALLER_ID
        assert seen[0]["x-caller-siteid"] == "MLA"
        assert "x-caller-id" not in seen[1] and "x-caller-siteid" not in seen[1]
        assert seen[1]["authorization"] == f"Bearer {TOKEN}"
        # the record says WHICH headers were sent, never their values
        assert with_caller["caller_headers_sent"] is True
        assert without["caller_headers_sent"] is False


class TestPacingAndBackoff:
    def test_calls_are_spaced_by_at_least_0_7_seconds(self):
        stamps = []
        clock = FakeClock()

        def handler(request):
            stamps.append(clock.now)
            return ok_handler(request)

        capture, _ = make_capture(handler, clock=clock)
        for i in range(4):
            capture.capture(f"c{i}", f"MLAU{i}", with_caller=True)
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        assert all(gap >= 0.7 for gap in gaps)

    def test_429_backs_off_honouring_retry_after_then_succeeds(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(429, json={"message": "slow down"}, headers={"retry-after": "7"})
            return ok_handler(request)

        capture, clock = make_capture(handler)
        record = capture.capture("full", "MLAU1", with_caller=True)
        assert record["status"] == 200
        assert calls["n"] == 3
        assert record["attempts"] == 3
        assert sum(1 for s in clock.sleeps if s >= 7) == 2

    def test_429_without_retry_after_still_waits(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(429, json={}) if calls["n"] == 1 else ok_handler(request)

        capture, clock = make_capture(handler)
        capture.capture("full", "MLAU1", with_caller=True)
        assert max(clock.sleeps) >= 5

    def test_persistent_429_gives_up_and_records_it(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(429, json={"message": "slow down"})

        capture, _ = make_capture(handler)
        record = capture.capture("full", "MLAU1", with_caller=True)
        assert record["status"] == 429
        assert calls["n"] == cap.MAX_429_RETRIES + 1

    def test_a_huge_retry_after_is_capped(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(429, headers={"retry-after": "99999"}) if calls["n"] == 1 else ok_handler(request)

        capture, clock = make_capture(handler)
        capture.capture("full", "MLAU1", with_caller=True)
        assert max(clock.sleeps) <= cap.MAX_RETRY_AFTER_SECONDS


class TestRunAndOutput:
    TARGETS = [
        cap.Target("full_1", "MLAUF1", True),
        cap.Target("non_full_1", "MLAUN1", True),
        cap.Target("full_1_no_caller", "MLAUF1", False),
    ]

    def test_run_captures_every_target_and_summarises_status(self):
        def handler(request):
            if "MLAUN1" in request.url.path:
                return httpx.Response(404, json={"message": "not found"})
            return ok_handler(request)

        capture, _ = make_capture(handler)
        records = cap.run_captures(capture, self.TARGETS)
        assert [r["case"] for r in records] == ["full_1", "non_full_1", "full_1_no_caller"]
        assert [r["status"] for r in records] == [200, 404, 200]
        lines = cap.summary_lines(records)
        assert len(lines) == 3
        assert "non_full_1" in lines[1] and "404" in lines[1]
        assert TOKEN not in "\n".join(lines)

    def test_write_output_is_valid_json_without_credentials(self, tmp_path):
        capture, _ = make_capture(ok_handler)
        records = cap.run_captures(capture, self.TARGETS)
        path = cap.write_output(records, directory=tmp_path, stamp="20261008T100000")
        assert path.name == "replenishment_capture_20261008T100000.json"
        text = path.read_text()
        assert TOKEN not in text
        assert len(json.loads(text)["cases"]) == 3

    def test_the_default_output_directory_is_tmp(self):
        assert cap.OUTPUT_DIR == Path("/tmp")


class TestTargetSelection:
    def test_full_and_non_full_targets_plus_no_caller_variants(self):
        targets = cap.build_targets(full=["F1", "F2", "F3"], non_full=["N1", "N2"])
        by_case = {t.case: t for t in targets}
        assert [t.mlau for t in targets if t.case.startswith("full_") and t.with_caller] == ["F1", "F2", "F3"]
        assert by_case["non_full_1"].mlau == "N1"
        # the call WITHOUT caller headers, for a Full and for a non-Full user product
        assert by_case["full_1_no_caller"].mlau == "F1" and by_case["full_1_no_caller"].with_caller is False
        assert by_case["non_full_1_no_caller"].mlau == "N1"

    def test_without_any_full_user_product_it_refuses(self):
        with pytest.raises(cap.NothingToCapture):
            cap.build_targets(full=[], non_full=["N1"])

    def test_without_non_full_it_still_captures_the_full_ones(self):
        targets = cap.build_targets(full=["F1"], non_full=[])
        assert {t.case for t in targets} == {"full_1", "full_1_no_caller"}

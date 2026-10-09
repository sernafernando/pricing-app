"""ml-billing-balance PR 4c-i/iii -- the billing lap, one proxy request per tick (D12).

Data is the real capture: the `monthly/periods` page (OPEN + 11 CLOSED), the
2026-09-01 credit-note pages and the period's documents. Only the client is
scripted. The state is plain JSON, so every test round-trips it through
`json` to prove a restart loses nothing.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from app.models.ml_billing import MlBillingCharge, MlBillingDocument, MlBillingPeriodStat
from app.services.ml_billing import billing_lap
from app.services.ml_webhook_client import BillingFetch, ml_webhook_client

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing"
NOW = datetime(2026, 10, 9, 8, 17, tzinfo=timezone.utc)
PERIODS = json.loads((_FIXTURES / "periods_bill.json").read_text())["body"]
CN_PAGES = json.load(gzip.open(_FIXTURES / "credit_note_2026_09.json.gz"))["pages"]
DOCUMENTS = json.loads((_FIXTURES / "documents_2026_09_01.json").read_text())


def tick(db, state, at):
    """One tick; the state goes through JSON like it does through `worker_job_state.detail`."""
    return json.loads(json.dumps(billing_lap.run_billing_tick(db, json.loads(json.dumps(state)), at), default=str))


def at(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


@pytest.fixture()
def client():
    with (
        mock.patch.object(
            ml_webhook_client, "get_billing_periods", new=mock.AsyncMock(return_value=PERIODS)
        ) as periods,
        mock.patch.object(ml_webhook_client, "fetch_billing_details", new=mock.AsyncMock()) as details,
        mock.patch.object(ml_webhook_client, "get_billing_documents", new=mock.AsyncMock()) as documents,
    ):
        yield mock.Mock(periods=periods, details=details, documents=documents)


def ok(body):
    return BillingFetch(status=200, body=body, error=None)


def started(db, client):
    """A lap built from the captured periods page (the first tick spends its request on `periods`)."""
    return tick(db, {}, NOW)


class TestThrottle:
    def test_a_tick_within_15_seconds_of_the_last_request_makes_no_call(self, db, client) -> None:
        state = started(db, client)
        again = tick(db, state, at(14))
        assert again == state
        assert client.details.call_count == 0
        assert client.periods.call_count == 1

    def test_a_tick_before_retry_at_makes_no_call(self, db, client) -> None:
        client.periods.return_value = None
        failed = tick(db, {}, NOW)
        assert (failed["failures"], failed["complete"]) == (1, False)
        assert tick(db, failed, at(59)) == failed
        assert client.periods.call_count == 1


class TestLapBuild:
    def test_the_first_tick_asks_for_the_periods_and_orders_open_first_then_closed_newest_first(
        self, db, client
    ) -> None:
        state = started(db, client)
        assert client.periods.call_count == 1
        assert state["complete"] is False and state["last_request_at"] == NOW.isoformat()
        keys = [u["period_key"] for u in state["lap"]["units"]]
        assert [k for i, k in enumerate(keys) if i == 0 or keys[i - 1] != k] == [
            "2026-10-01",
            "2026-09-01",
            "2026-08-01",
            "2026-07-01",
            "2026-06-01",
            "2026-05-01",
            "2026-04-01",
            "2026-03-01",
            "2026-02-01",
            "2026-01-01",
            "2025-12-01",
            "2025-11-01",
        ]

    def test_every_period_gets_bill_then_credit_note_details_and_documents(self, db, client) -> None:
        units = started(db, client)["lap"]["units"]
        assert len(units) == 12 * 4
        assert [(u["document_type"], u["kind"]) for u in units[:4]] == [
            ("BILL", "details"),
            ("BILL", "documents"),
            ("CREDIT_NOTE", "details"),
            ("CREDIT_NOTE", "documents"),
        ]

    def test_a_failed_periods_request_backs_off_60_120_240_seconds_and_builds_no_lap(self, db, client) -> None:
        client.periods.return_value = None
        state = tick(db, {}, NOW)
        assert (state["failures"], state["retry_at"], state.get("lap")) == (1, at(60).isoformat(), None)
        state = tick(db, state, at(61))
        assert (state["failures"], state["retry_at"]) == (2, at(61 + 120).isoformat())
        state = tick(db, state, at(61 + 121))
        assert (state["failures"], state["retry_at"]) == (3, at(61 + 121 + 240).isoformat())


class TestDetailsUnit:
    def test_a_good_page_is_persisted_and_the_cursor_moves_to_its_last_id(self, db, client) -> None:
        state = started(db, client)
        state["lap"]["units"] = [
            u
            for u in state["lap"]["units"]
            if (u["period_key"], u["document_type"], u["kind"]) == ("2026-09-01", "CREDIT_NOTE", "details")
        ]
        client.details.return_value = ok(CN_PAGES[0])
        state = tick(db, state, at(15))
        assert db.query(MlBillingCharge).count() == 196
        unit = state["lap"]["units"][0]
        assert unit["from_id"] == CN_PAGES[0]["last_id"] and unit["state"] == "pending"
        sent = client.details.call_args.args
        assert sent[:3] == ("2026-09-01", "ML", "CREDIT_NOTE")

    def test_an_empty_page_finishes_the_unit_and_the_next_tick_moves_on(self, db, client) -> None:
        state = started(db, client)
        client.details.return_value = ok(CN_PAGES[1])
        state = tick(db, state, at(15))  # BILL details of the OPEN period: empty
        assert state["lap"]["index"] == 1 and state["lap"]["units"][0]["state"] == "done"

    def test_a_restart_resumes_the_cursor_from_the_persisted_state(self, db, client) -> None:
        state = started(db, client)
        client.details.return_value = ok(CN_PAGES[0])
        state = tick(db, state, at(15))
        client.details.return_value = ok(CN_PAGES[1])
        tick(db, state, at(30))
        assert client.details.call_args.args[-1] == CN_PAGES[0]["last_id"]


class TestFailures:
    def test_a_429_or_timeout_keeps_the_cursor_and_sets_an_exponential_retry_at(self, db, client) -> None:
        state = started(db, client)
        client.details.return_value = BillingFetch(status=429, body=None, error="HTTP 429")
        state = tick(db, state, at(15))
        assert (state["failures"], state["retry_at"], state["lap"]["index"]) == (1, at(15 + 60).isoformat(), 0)
        client.details.return_value = BillingFetch(status=None, body=None, error="timeout")
        state = tick(db, state, at(80))
        assert (state["failures"], state["retry_at"]) == (2, at(80 + 120).isoformat())

    def test_the_backoff_is_capped_at_15_minutes(self) -> None:
        assert billing_lap.backoff(10) == timedelta(minutes=15)

    def test_five_transport_failures_fail_the_unit_and_the_lap_moves_on(self, db, client) -> None:
        state = started(db, client)
        client.details.return_value = BillingFetch(status=503, body=None, error="HTTP 503")
        now = at(15)
        for _ in range(5):
            state = tick(db, state, now)
            now += timedelta(minutes=16)  # past any backoff
        assert state["lap"]["units"][0]["state"] == "failed" and state["lap"]["index"] == 1
        assert state["failures"] == 0

    def test_a_bare_400_halts_that_unit_and_the_lap_moves_on(self, db, client) -> None:
        """Until the poison engine is wired (4c-ii) a 400 stops the period's details exactly as the cron did."""
        envelope = json.loads((_FIXTURES / "captured_400_envelope.json").read_text())
        state = started(db, client)
        client.details.return_value = BillingFetch(status=400, body=envelope, error="HTTP 400")
        state = tick(db, state, at(15))
        assert state["lap"]["units"][0]["state"] == "failed" and state["lap"]["index"] == 1


class TestDocumentsUnit:
    def test_documents_are_persisted_and_a_bill_unit_records_the_period_observation(self, db, client) -> None:
        state = started(db, client)
        state["lap"]["units"][0].update(total=26056, state="done")
        state["lap"]["index"] = 1  # BILL documents of the OPEN period
        client.documents.return_value = {"results": DOCUMENTS["BILL"]}
        state = tick(db, state, at(15))
        assert db.query(MlBillingDocument).count() == len(DOCUMENTS["BILL"])
        assert state["lap"]["units"][1]["state"] == "done"
        stat = db.query(MlBillingPeriodStat).filter_by(period_key="2026-10-01").one()
        assert (stat.reported_total, stat.documents_count_details) == (
            26056,
            sum(d["count_details"] for d in DOCUMENTS["BILL"]),
        )

    def test_a_lap_in_flight_from_before_the_verify_key_still_finishes_its_units(self, db, client) -> None:
        state = started(db, client)
        for unit in state["lap"]["units"]:
            del unit["verify"]  # the shape persisted by the previous release
        state["lap"]["index"] = 1
        client.documents.return_value = {"results": DOCUMENTS["BILL"]}
        state = tick(db, state, at(15))
        assert (state["lap"]["units"][1]["state"], state["lap"]["index"]) == ("done", 2)

    def test_no_period_observation_is_recorded_when_the_bill_details_failed(self, db, client) -> None:
        state = started(db, client)
        state["lap"]["units"][0].update(total=26056, state="failed")
        state["lap"]["index"] = 1
        client.documents.return_value = {"results": DOCUMENTS["BILL"]}
        tick(db, state, at(15))
        assert db.query(MlBillingPeriodStat).filter_by(period_key="2026-10-01").count() == 0

    def test_a_failed_documents_request_keeps_the_unit_for_the_retry(self, db, client) -> None:
        state = started(db, client)
        state["lap"]["index"] = 1
        client.documents.return_value = None
        state = tick(db, state, at(15))
        assert (state["failures"], state["lap"]["index"]) == (1, 1)

    def test_the_lap_ends_complete_after_the_last_unit(self, db, client) -> None:
        state = started(db, client)
        state["lap"]["index"] = len(state["lap"]["units"]) - 1  # CN documents of the oldest period
        client.documents.return_value = {"results": []}
        state = tick(db, state, at(15))
        assert state["complete"] is True and state["lap"] is None


class TestSettled:
    def _settle(self, db, client):
        """Ingests the 2026-09-01 credit notes completely, through the lap itself."""
        state = started(db, client)
        state["lap"]["units"] = [
            u for u in state["lap"]["units"] if (u["period_key"], u["document_type"]) == ("2026-09-01", "CREDIT_NOTE")
        ]
        client.details.side_effect = [ok(CN_PAGES[0]), ok(CN_PAGES[1])]
        client.documents.return_value = {"results": DOCUMENTS["CREDIT_NOTE"]}
        for i in range(1, 4):
            state = tick(db, state, at(15 * i))
        assert state["complete"] is True

    def test_the_verification_is_only_recorded_once_every_documents_unit_of_the_period_is_done(
        self, db, client
    ) -> None:
        self._settle(db, client)
        state = tick(db, {"complete": True}, at(600))
        state["lap"]["units"] = [u for u in state["lap"]["units"] if u["period_key"] == "2026-09-01"]
        client.documents.side_effect = [{"results": DOCUMENTS["BILL"]}, None]
        state = tick(db, state, at(700))
        assert state["verified"] == {}
        state["lap"]["units"][1]["state"] = "failed"
        state["lap"]["index"] = 0
        state = tick(db, state, at(800))
        assert state["verified"] == {}

    def _units_of(self, state, period):
        return [(u["document_type"], u["kind"]) for u in state["lap"]["units"] if u["period_key"] == period]

    def test_a_complete_period_without_processing_documents_is_verified_through_documents_only(
        self, db, client
    ) -> None:
        self._settle(db, client)
        state = tick(db, {"complete": True}, at(600))
        assert self._units_of(state, "2026-09-01") == [("BILL", "documents"), ("CREDIT_NOTE", "documents")]

    def test_a_verified_settled_period_is_skipped_until_a_week_has_passed(self, db, client) -> None:
        self._settle(db, client)
        state = {"complete": True, "verified": {"2026-09-01": at(600).isoformat()}}
        assert self._units_of(tick(db, state, at(700)), "2026-09-01") == []
        week = at(600 + 7 * 86400 + 1)
        assert self._units_of(tick(db, state, week), "2026-09-01") == [
            ("BILL", "documents"),
            ("CREDIT_NOTE", "documents"),
        ]

    def test_a_charge_without_its_legal_number_keeps_the_period_in_the_full_sweep(self, db, client) -> None:
        self._settle(db, client)
        db.query(MlBillingCharge).filter_by(detail_id=db.query(MlBillingCharge.detail_id).first()[0]).update(
            {"legal_document_number": None, "legal_document_status": "PROCESSING"}
        )
        state = tick(db, {"complete": True}, at(600))
        assert len(self._units_of(state, "2026-09-01")) == 4

    def test_an_open_period_is_never_settled(self, db, client) -> None:
        state = tick(db, {"complete": True, "verified": {"2026-10-01": at(0).isoformat()}}, at(600))
        assert len(self._units_of(state, "2026-10-01")) == 4

"""ml-billing-balance PR 5-iii -- flex BILL / CREDIT_NOTE details inside the billing lap.

Rows are the captured flex rows of `flex_rows.json` (the three CREDIT_NOTE ones, verbatim) and the
captured bare-400 envelope. Only the client is scripted. DERIVED: the page size is patched down to
2 so three captured rows span two pages; the real size is 500 (`captured_flex_offset_pages.json`).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from app.core.config import settings
from app.models.ml_billing import MlBillingCharge
from app.services.ml_billing import billing_lap, flex_lap
from app.services.ml_billing.sweep_gaps import open_gaps
from app.services.ml_webhook_client import BillingFetch, ml_webhook_client

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing"
NOW = datetime(2026, 10, 9, 8, 17, tzinfo=timezone.utc)
PERIODS = json.loads((_FIXTURES / "periods_bill.json").read_text())["body"]
_BARE_400 = BillingFetch(400, json.loads((_FIXTURES / "captured_400_envelope.json").read_text()), "HTTP 400")
_FLEX = json.loads((_FIXTURES / "flex_rows.json").read_text())
ROWS = [_FLEX[k]["row"] for k in ("bflx_599", "bflx_8990", "bflx_reciprocal")]
CN = ("2026-09-01", "CREDIT_NOTE", "details")


def tick(db, state, at):
    return json.loads(json.dumps(billing_lap.run_billing_tick(db, json.loads(json.dumps(state)), at), default=str))


def at(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


@pytest.fixture()
def client():
    with (
        mock.patch.object(ml_webhook_client, "get_billing_periods", new=mock.AsyncMock(return_value=PERIODS)),
        mock.patch.object(ml_webhook_client, "fetch_billing_details", new=mock.AsyncMock()) as general,
        mock.patch.object(ml_webhook_client, "fetch_billing_flex_details", new=mock.AsyncMock()) as flex,
        mock.patch.object(ml_webhook_client, "get_billing_documents", new=mock.AsyncMock()),
    ):
        yield mock.Mock(general=general, flex=flex)


@pytest.fixture()
def flex_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_BILLING_ENABLED", True)
    monkeypatch.setattr(settings, "ML_BILLING_FLEX_ENABLED", True)
    monkeypatch.setattr(flex_lap, "FLEX_PAGE_LIMIT", 2)


def _units(state, kind="details", source=None):
    return [u for u in state["lap"]["units"] if u["kind"] == kind and u.get("source") == source]


def _flex_cn_state(db):
    """A lap holding only the flex CREDIT_NOTE details unit of 2026-09-01."""
    state = tick(db, {}, NOW)
    state["lap"]["units"] = [
        u
        for u in state["lap"]["units"]
        if (u["period_key"], u["document_type"], u["kind"]) == CN and u.get("source") == "flex"
    ]
    return state


class _FlexMl:
    """The captured rows paged by `offset`; a read that covers a poison offset is a bare 400."""

    def __init__(self, poison=()):
        self.poison, self.calls = set(poison), []

    def __call__(self, period, group, document_type, limit, offset):
        self.calls.append((offset, limit))
        rows = ROWS[offset : offset + limit]
        if self.poison & set(range(offset, offset + len(rows))):
            return _BARE_400
        return BillingFetch(200, {"results": rows, "total": len(ROWS)}, None)


def _run(db, client, state, ml, start=15, max_ticks=60):
    client.flex.side_effect = ml
    for n in range(max_ticks):
        before = client.flex.call_count
        state = tick(db, state, at(start + 15 * n))
        assert client.flex.call_count - before <= 1  # ONE request per tick, always
        if state["lap"] is None:
            return state
    raise AssertionError("the unit did not end")


class TestFlag:
    def test_flex_is_off_by_default_and_the_lap_has_no_flex_unit(self, db, client, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ML_BILLING_ENABLED", True)
        assert settings.ML_BILLING_FLEX_ENABLED is False
        state = tick(db, {}, NOW)
        assert _units(state, source="flex") == [] and len(state["lap"]["units"]) == 48

    def test_the_flex_flag_needs_the_billing_flag(self, db, client, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ML_BILLING_ENABLED", False)
        monkeypatch.setattr(settings, "ML_BILLING_FLEX_ENABLED", True)
        assert _units(tick(db, {}, NOW), source="flex") == []

    def test_turning_the_flag_off_mid_lap_skips_the_flex_units_without_a_request(
        self, db, client, flex_on, monkeypatch
    ) -> None:
        state = _flex_cn_state(db)
        monkeypatch.setattr(settings, "ML_BILLING_FLEX_ENABLED", False)
        state = tick(db, state, at(15))
        assert client.flex.call_count == 0 and state["last_lap"]["failed"] == [] and state["complete"] is True


class TestLapBuild:
    def test_every_period_gets_flex_bill_and_credit_note_details_and_no_documents_unit(
        self, db, client, flex_on
    ) -> None:
        state = tick(db, {}, NOW)
        flex = _units(state, source="flex")
        assert len(flex) == 24 and {u["document_type"] for u in flex} == {"BILL", "CREDIT_NOTE"}
        assert _units(state, "documents", source="flex") == []
        assert all(u["offset"] == 0 and u["documents"] == "document_unknown" and not u["verify"] for u in flex)
        assert len(state["lap"]["units"]) == 48 + 24

    def test_a_settled_and_recently_verified_period_still_gets_its_flex_units(self, db, client, flex_on) -> None:
        with mock.patch.object(billing_lap, "_settled", return_value=True):
            verified = {"2026-09-01": NOW.isoformat()}
            state = tick(db, {"verified": verified}, NOW)
        mine = [u for u in state["lap"]["units"] if u["period_key"] == "2026-09-01"]
        assert [(u["document_type"], u.get("source")) for u in mine] == [("BILL", "flex"), ("CREDIT_NOTE", "flex")]


class TestFlexUnit:
    def test_pages_by_offset_persist_as_flex_and_an_empty_page_ends_the_unit(self, db, client, flex_on) -> None:
        ml = _FlexMl()
        state = _run(db, client, _flex_cn_state(db), ml)
        assert ml.calls == [(0, 2), (2, 2), (3, 2)] and state["last_lap"]["failed"] == []
        charges = db.query(MlBillingCharge).all()
        assert len(charges) == 3 and {c.billing_source for c in charges} == {"flex"}
        assert client.flex.call_args.args[:3] == ("2026-09-01", "ML", "CREDIT_NOTE")

    def test_a_429_keeps_the_offset_and_backs_off(self, db, client, flex_on) -> None:
        client.flex.return_value = BillingFetch(429, None, "HTTP 429")
        state = tick(db, _flex_cn_state(db), at(15))
        assert state["failures"] == 1 and state["lap"]["units"][0]["offset"] == 0 and state["retry_at"]

    def test_a_400_that_names_its_cause_fails_the_unit(self, db, client, flex_on) -> None:
        client.flex.return_value = BillingFetch(400, {"message": "invalid"}, "HTTP 400")
        state = tick(db, _flex_cn_state(db), at(15))
        assert state["last_lap"]["failed"] == [
            {"period_key": "2026-09-01", "document_type": "CREDIT_NOTE", "kind": "details", "source": "flex"}
        ]

    def test_a_source_that_never_runs_dry_fails_at_the_page_cap(self, db, client, flex_on, caplog) -> None:
        never_dry = BillingFetch(200, {"results": ROWS[:2], "total": 3}, None)
        state = _run(db, client, _flex_cn_state(db), lambda *args: never_dry)
        assert state["last_lap"]["failed"][0]["source"] == "flex" and "exceeded the expected pages" in caplog.text


class TestPoisonOffset:
    def test_a_bare_400_is_isolated_recorded_as_an_offset_gap_and_stepped_over(
        self, db, client, flex_on, caplog
    ) -> None:
        ml = _FlexMl(poison=[1])
        state = _run(db, client, _flex_cn_state(db), ml)
        assert "poison offset 2026-09-01 CREDIT_NOTE [1, 1]" in caplog.text
        assert state["last_lap"]["failed"] == [] and db.query(MlBillingCharge).count() == 2
        [gap] = open_gaps(db, "2026-09-01", "CREDIT_NOTE")
        assert (gap.position, gap.paging, gap.billing_source, gap.window) == ("1", "offset", "flex", "[1, 1]")
        assert gap.lap_id is not None

    def test_the_probe_survives_a_restart_between_any_two_ticks(self, db, client, flex_on) -> None:
        client.flex.side_effect = _FlexMl(poison=[1])
        state = tick(db, _flex_cn_state(db), at(15))  # `tick` round-trips the state through JSON
        unit = state["lap"]["units"][0]
        assert unit["state"] == "pending" and unit["probe"]["offset"] == 0 and unit["probe"]["retried"] is True

    def test_a_later_clean_pass_resolves_the_gap(self, db, client, flex_on) -> None:
        _run(db, client, _flex_cn_state(db), _FlexMl(poison=[1]))
        assert len(open_gaps(db, "2026-09-01", "CREDIT_NOTE")) == 1
        _run(db, client, _flex_cn_state(db), _FlexMl(), start=100_000)  # ML recovered
        assert open_gaps(db, "2026-09-01", "CREDIT_NOTE") == [] and db.query(MlBillingCharge).count() == 3

    def test_pages_narrowed_by_the_probe_never_count_towards_the_page_cap(self, db, client, flex_on) -> None:
        state = _flex_cn_state(db)
        state["lap"]["units"][0].update(total=len(ROWS), pages=11)  # one page short of the cap (2 + 10)
        client.flex.side_effect = _FlexMl(poison=[1])
        for n in range(3):  # bare 400, retry, then the limit-1 read at offset 0 succeeds
            state = tick(db, state, at(15 + 15 * n))
        unit = state["lap"]["units"][0]
        assert unit["offset"] == 1 and unit["pages"] == 11 and unit["state"] == "pending"

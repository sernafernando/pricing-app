"""pubml-promo-mejor S2/S3/S4 on Postgres: only candidates applicable now set the "hay mejores" flag, and the worker
handler `ml_promotions.hay_mejores_boundaries` re-runs it when a start or finish date passes (no sync event comes).

The pricing comparison is replaced by "every candidate it receives is better", so each test reads only the rule
under test: which candidates reach the comparison, and when.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.ml_publications import MlItemSalePrice, MlItemSellerPromotions
from app.models.worker_job_state import WorkerJobState
from app.services import ml_promotions_hay_mejores as hay_mejores
from app.workers.context import WorkerContext
from app.workers.handlers import ml_hay_mejores as module

pytestmark = pytest.mark.postgres

T0 = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db(mlpub_pg, monkeypatch):
    from tests.conftest import _restore_pristine_pg_types

    _restore_pristine_pg_types([WorkerJobState.__table__])
    WorkerJobState.__table__.create(bind=mlpub_pg)
    monkeypatch.setattr(
        hay_mejores,
        "listar_mejores_candidatas",
        lambda _db, _mla, candidates, _baseline, **_k: [(c["id"], float(c["price"])) for c in candidates],
    )
    monkeypatch.setattr(hay_mejores, "_enqueue_catalog_competition_refresh", lambda *_a, **_k: None)
    monkeypatch.setattr(module, "resolver_sell_in_out_para_mlas", lambda _db, _ids: None)
    factory = sessionmaker(bind=mlpub_pg)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _add(db, item_id: str, candidates: List[dict], *, flag: bool = False, descartado: str | None = None) -> None:
    db.add(
        MlItemSellerPromotions(
            item_id=item_id,
            candidate_count=len(candidates),
            started_promotion_keys=[],
            raw=[{"status": "candidate", "price": 900, **c} for c in candidates],
            hay_mejores_ofertas=flag,
            hay_mejores_descartado_fingerprint=descartado,
        )
    )
    db.add(MlItemSalePrice(item_id=item_id, amount=Decimal("1000.00"), raw={"amount": 1000}))
    db.commit()


def _flag(db, item_id: str) -> bool:
    db.expire_all()
    return bool(db.get(MlItemSellerPromotions, item_id).hay_mejores_ofertas)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _handler(clock: _Clock) -> module.HayMejoresBoundariesHandler:
    return module.HayMejoresBoundariesHandler(now=clock)


def _ctx(clock: _Clock) -> WorkerContext:
    return WorkerContext(deadline=clock.now + timedelta(seconds=module.boundaries.deadline_seconds))


def _iso(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%S")  # naive, as ML sends it: UTC


class TestApplicableNow:
    def test_a_future_start_candidate_does_not_set_the_flag(self, db) -> None:
        _add(db, "MLA1", [{"id": "C-1", "type": "SMART", "start_date": _iso(T0 + timedelta(days=10))}])
        decision = hay_mejores.actualizar_hay_mejores_ofertas(db, "MLA1", now=T0)
        db.commit()
        assert decision is not None and decision.hay_mejores is False
        assert _flag(db, "MLA1") is False

    def test_a_non_writable_type_does_not_count(self, db) -> None:
        _add(db, "MLA1", [{"id": "C-1", "type": "DOD"}, {"id": "C-2", "type": "PRICE_MATCHING_MELI_ALL"}])
        hay_mejores.actualizar_hay_mejores_ofertas(db, "MLA1", now=T0)
        db.commit()
        assert _flag(db, "MLA1") is False

    def test_a_seller_campaign_counts_only_as_the_premium_of_the_month(self, db) -> None:
        _add(db, "MLA1", [{"id": "C-1", "type": "SELLER_CAMPAIGN", "name": "PREMIUM OCTUBRE"}])
        _add(db, "MLA2", [{"id": "C-2", "type": "SELLER_CAMPAIGN", "name": "PREMIUM NOVIEMBRE"}])
        for item_id in ("MLA1", "MLA2"):
            hay_mejores.actualizar_hay_mejores_ofertas(db, item_id, now=T0)
        db.commit()
        assert (_flag(db, "MLA1"), _flag(db, "MLA2")) == (False, True)

    def test_an_applicable_candidate_still_sets_it(self, db) -> None:
        _add(db, "MLA1", [{"id": "C-1", "type": "DEAL", "start_date": _iso(T0 - timedelta(days=1))}])
        hay_mejores.actualizar_hay_mejores_ofertas(db, "MLA1", now=T0)
        db.commit()
        assert _flag(db, "MLA1") is True


class TestBoundariesHandler:
    def _settle(self, db, clock: _Clock) -> None:
        """First run: the catch-up (nothing flagged here) records `checked_until`."""
        result = _handler(clock).run(_ctx(clock))
        assert result.success and result.detail["catchup"] is True

    def test_the_flag_is_set_once_the_start_passes(self, db) -> None:
        start = T0 + timedelta(hours=1)
        _add(db, "MLA1", [{"id": "C-1", "type": "SMART", "start_date": _iso(start)}])
        _add(db, "MLA2", [{"id": "C-2", "type": "SMART", "start_date": _iso(T0 + timedelta(days=10))}])
        hay_mejores.actualizar_hay_mejores_ofertas(db, "MLA1", now=T0)
        db.commit()
        clock = _Clock(T0)
        self._settle(db, clock)
        assert _flag(db, "MLA1") is False

        clock.now = start + timedelta(minutes=5)
        result = _handler(clock).run(_ctx(clock))
        assert result.success and result.detail == {"recomputed": 1, "changed": 1, "catchup": False}
        assert _flag(db, "MLA1") is True and _flag(db, "MLA2") is False

        # The window is done: the next run recomputes nothing.
        clock.now += timedelta(minutes=5)
        assert _handler(clock).run(_ctx(clock)).detail["recomputed"] == 0

    def test_an_expired_candidate_clears_the_flag(self, db) -> None:
        finish = T0 + timedelta(hours=1)
        _add(db, "MLA1", [{"id": "C-1", "type": "DEAL", "finish_date": _iso(finish)}])
        hay_mejores.actualizar_hay_mejores_ofertas(db, "MLA1", now=T0)
        db.commit()
        assert _flag(db, "MLA1") is True
        clock = _Clock(T0 - timedelta(minutes=1))
        _handler(clock).run(_ctx(clock))  # catch-up recomputes it at T0-1m: still applicable
        assert _flag(db, "MLA1") is True

        clock.now = finish + timedelta(minutes=1)
        result = _handler(clock).run(_ctx(clock))
        assert result.detail == {"recomputed": 1, "changed": 1, "catchup": False}
        assert _flag(db, "MLA1") is False

    def test_the_catch_up_recomputes_the_stale_flags_once(self, db) -> None:
        # Flagged under the old rule (every candidate counted): a future candidate and a non-writable one.
        _add(db, "MLA1", [{"id": "C-1", "type": "SMART", "start_date": _iso(T0 + timedelta(days=10))}], flag=True)
        _add(db, "MLA2", [{"id": "C-2", "type": "DOD"}], flag=True)
        _add(db, "MLA3", [{"id": "C-3", "type": "SMART"}], flag=True)
        _add(db, "MLA4", [{"id": "C-4", "type": "SMART", "start_date": _iso(T0 + timedelta(days=10))}])
        clock = _Clock(T0)
        result = _handler(clock).run(_ctx(clock))
        assert result.detail == {"recomputed": 3, "changed": 2, "catchup": True}
        assert [_flag(db, i) for i in ("MLA1", "MLA2", "MLA3", "MLA4")] == [False, False, True, False]
        state = db.get(WorkerJobState, module.HANDLER_NAME).detail
        assert state["rules_version"] == module.RULES_VERSION and state["checked_until"] == T0.isoformat()

        clock.now += timedelta(minutes=5)
        assert _handler(clock).run(_ctx(clock)).detail == {"recomputed": 0, "changed": 0, "catchup": False}

    def test_a_run_stopped_by_its_deadline_resumes_after_its_cursor(self, db, monkeypatch) -> None:
        monkeypatch.setattr(module, "BATCH", 1)
        for item_id in ("MLA1", "MLA2", "MLA3"):
            _add(db, item_id, [{"id": f"C-{item_id}", "type": "DOD"}], flag=True)
        clock = _Clock(T0)
        calls = {"n": 0}

        def stop_after_first() -> bool:
            calls["n"] += 1
            return calls["n"] > 1

        ctx = WorkerContext(deadline=T0 + timedelta(minutes=2), stop_requested=stop_after_first)
        first = _handler(clock).run(ctx)
        assert first.detail["complete"] is False and first.detail["cursor"] == "MLA1"
        assert [_flag(db, i) for i in ("MLA1", "MLA2", "MLA3")] == [False, True, True]

        second = _handler(clock).run(_ctx(clock))
        assert second.detail == {"recomputed": 2, "changed": 2, "catchup": True}
        assert [_flag(db, i) for i in ("MLA1", "MLA2", "MLA3")] == [False, False, False]

    def test_a_failure_is_reported_not_raised(self, db, monkeypatch) -> None:
        def boom(*_a, **_k):
            raise RuntimeError("db down")

        monkeypatch.setattr(module, "_read_state", boom)
        clock = _Clock(T0)
        result = _handler(clock).run(_ctx(clock))
        assert result.success is False and "db down" in result.error


class TestCrossingSelection:
    def test_only_items_whose_candidate_dates_fall_in_the_window(self, db) -> None:
        since, until = T0, T0 + timedelta(minutes=5)
        _add(db, "MLA1", [{"id": "a", "type": "SMART", "start_date": _iso(T0 + timedelta(minutes=2))}])
        _add(db, "MLA2", [{"id": "b", "type": "DEAL", "finish_date": "2026-11-13T12:03:00-03:00"}])
        _add(db, "MLA3", [{"id": "c", "type": "SMART", "start_date": _iso(T0)}])  # exactly `since`: last window
        _add(db, "MLA4", [{"id": "d", "type": "SMART", "start_date": _iso(T0 + timedelta(minutes=6))}])
        _add(db, "MLA5", [{"id": "e", "type": "SMART", "start_date": "not a date"}])
        assert hay_mejores.items_con_candidatas_que_cruzan(db, since, until) == ["MLA1", "MLA2"]

    def test_a_date_only_finish_crosses_at_the_end_of_its_day(self, db) -> None:
        _add(db, "MLA1", [{"id": "a", "type": "DEAL", "finish_date": "2026-11-13"}])
        midnight = datetime(2026, 11, 14, tzinfo=timezone.utc)
        assert hay_mejores.items_con_candidatas_que_cruzan(db, midnight - timedelta(minutes=5), midnight) == ["MLA1"]
        assert hay_mejores.items_con_candidatas_que_cruzan(db, T0, T0 + timedelta(minutes=5)) == []

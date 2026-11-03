"""Postgres: envio/sku repair loops persist runs+events through short background sessions."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.publicacion_repair import (
    ACTION_CHANGED,
    PublicacionRepairEvent,
    PublicacionRepairRun,
)
from app.services.ml_api_client import ShippingWriteResult
from app.services.publicacion_repair import audit as repair_audit
from app.services.publicacion_repair import envio as envio_mod
from app.services.publicacion_repair import sku as sku_mod
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable


def _fresh() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture()
def repair_pg(monkeypatch: pytest.MonkeyPatch):
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")

    eng = create_engine(POSTGRES_TEST_URL)
    PublicacionRepairRun.__table__.create(bind=eng, checkfirst=True)
    PublicacionRepairEvent.__table__.create(bind=eng, checkfirst=True)
    Session = sessionmaker(bind=eng)

    @contextmanager
    def _bg():
        db = Session()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(repair_audit, "get_background_db", _bg)
    monkeypatch.setattr(envio_mod, "get_background_db", _bg)
    monkeypatch.setattr(sku_mod, "get_background_db", _bg)
    monkeypatch.setattr(envio_mod.settings, "ML_PUB_KILL_SWITCH", False)
    monkeypatch.setattr(envio_mod.settings, "ML_ITEM_DATA_WRITE_ENABLED", True)
    monkeypatch.setattr(sku_mod.settings, "ML_PUB_KILL_SWITCH", False)
    monkeypatch.setattr(sku_mod.settings, "ML_ITEM_DATA_WRITE_ENABLED", True)
    monkeypatch.setattr(envio_mod.repair_audit, "after_shipping_changed", lambda *a, **k: None)
    monkeypatch.setattr(envio_mod.repair_audit, "after_flex_enabled", lambda *a, **k: None)
    monkeypatch.setattr(sku_mod.repair_audit, "record_ml_write_log", lambda *a, **k: None)
    monkeypatch.setattr(sku_mod.repair_audit, "enqueue_item_refresh_safely", lambda *a, **k: None)
    yield Session
    PublicacionRepairEvent.__table__.drop(bind=eng, checkfirst=True)
    PublicacionRepairRun.__table__.drop(bind=eng, checkfirst=True)
    eng.dispose()


@pytest.mark.postgres
def test_envio_loop_persists_flex_refusal_and_skips_on_rerun(
    repair_pg, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = {
        "mode": "me2",
        "logistic_type": "cross_docking",
        "local_pick_up": True,
        "free_shipping": False,
        "store_pick_up": False,
        "tags": [],
        "status": "active",
        "fetched_at": _fresh(),
    }
    monkeypatch.setattr(envio_mod, "_load_work_items", lambda db: [("MLA_FLEX", 42, current)])

    class RefuseFlex:
        async def put_item_shipping(self, *a, **k):
            raise AssertionError("no shipping put")

        async def enable_item_flex(self, mla: str):
            return ShippingWriteResult(ok=False, status_code=400, not_allowed=True, detail="flex blocked")

    stats1 = asyncio.run(envio_mod.run_envio_repair(client=RefuseFlex(), pacing_seconds=0))
    assert stats1["skipped"] == 1

    Session = repair_pg
    with Session() as db:
        events = db.query(PublicacionRepairEvent).filter_by(mla_id="MLA_FLEX").all()
        assert len(events) == 1
        assert events[0].detail == envio_mod.DETAIL_FLEX_REFUSED
        assert events[0].after["fingerprint"] == envio_mod.ml_item_shipping_fingerprint(current)

    class Boom:
        async def put_item_shipping(self, *a, **k):
            raise AssertionError("must not write on cached refusal")

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("must not re-POST Flex")

    stats2 = asyncio.run(envio_mod.run_envio_repair(client=Boom(), pacing_seconds=0))
    assert stats2["skipped"] == 1

    with Session() as db:
        details = [e.detail for e in db.query(PublicacionRepairEvent).filter_by(mla_id="MLA_FLEX").all()]
        assert envio_mod.DETAIL_FLEX_REFUSED in details
        assert envio_mod.DETAIL_FLEX_REFUSED_UNCHANGED in details
        runs = db.query(PublicacionRepairRun).all()
        assert len(runs) == 2


@pytest.mark.postgres
def test_sku_loop_persists_changed_event(repair_pg, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sku_mod,
        "_load_work_items",
        lambda db: [("MLA_DRIFT", 7, "OLD", "NEWCODE", "active", _fresh())],
    )

    class Fake:
        async def put_item_data(self, mla: str, body: dict):
            return {"ok": True, "status_code": 200, "ambiguous": False, "body": {}}

    stats = asyncio.run(sku_mod.run_sku_repair(client=Fake(), pacing_seconds=0))
    assert stats["changed"] == 1

    Session = repair_pg
    with Session() as db:
        run = db.query(PublicacionRepairRun).one()
        assert run.job_type == "sku"
        assert run.changed == 1
        event = db.query(PublicacionRepairEvent).one()
        assert event.action == ACTION_CHANGED
        assert event.mla_id == "MLA_DRIFT"

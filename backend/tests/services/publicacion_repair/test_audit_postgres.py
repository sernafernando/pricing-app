"""Postgres: repair audit must survive get_background_db commit (no DetachedInstance)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.publicacion_repair import (
    JOB_ENVIO,
    TRIGGER_TICK,
    PublicacionRepairEvent,
    PublicacionRepairRun,
)
from app.services.publicacion_repair import audit as repair_audit
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable


@pytest.fixture()
def repair_pg(monkeypatch: pytest.MonkeyPatch):
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")

    eng = create_engine(POSTGRES_TEST_URL)
    PublicacionRepairRun.__table__.create(bind=eng, checkfirst=True)
    PublicacionRepairEvent.__table__.create(bind=eng, checkfirst=True)
    Session = sessionmaker(bind=eng)

    from contextlib import contextmanager

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
    yield Session
    PublicacionRepairEvent.__table__.drop(bind=eng, checkfirst=True)
    PublicacionRepairRun.__table__.drop(bind=eng, checkfirst=True)
    eng.dispose()


@pytest.mark.postgres
def test_start_run_bg_returns_int_usable_after_commit(repair_pg) -> None:
    run_id = repair_audit.start_run_bg(job_type=JOB_ENVIO, trigger=TRIGGER_TICK)
    assert isinstance(run_id, int)

    # Must not raise DetachedInstanceError — callers only hold the int.
    repair_audit.record_event_bg(
        run_id=run_id,
        mla_id="MLA_TEST",
        item_id=1,
        action="skipped",
        detail="unit",
    )
    repair_audit.finish_run_bg(
        run_id,
        scanned=1,
        changed=0,
        skipped=1,
        errors=0,
        error_message=None,
    )

    Session = repair_pg
    with Session() as db:
        run = db.get(PublicacionRepairRun, run_id)
        assert run is not None
        assert run.status in {"success", "partial", "failed"}
        assert run.scanned == 1
        events = db.query(PublicacionRepairEvent).filter_by(run_id=run_id).all()
        assert len(events) == 1

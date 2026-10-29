"""PARA GANAR consultation jobs: enqueue, fairness claim, process settle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.models.para_ganar_consulta_job import (
    ITEM_DONE,
    ITEM_FAILED,
    ITEM_PENDING,
    ITEM_PROCESSING,
    ITEM_SKIPPED,
    JOB_COMPLETED,
    JOB_PENDING,
    JOB_RUNNING,
    SOURCE_MANUAL,
    SOURCE_PERIODIC,
    ParaGanarConsultaJob,
    ParaGanarConsultaJobItem,
)
from app.services import para_ganar_consulta as consulta
from app.workers.handlers.para_ganar_consulta import para_ganar_consulta
from app.workers.handlers.para_ganar_consulta_periodic import para_ganar_consulta_periodic


def test_enqueue_dedupes_and_sets_pending(db) -> None:
    job = consulta.enqueue_consulta(
        db,
        ["mla1", "MLA1", " MLA2 ", ""],
        created_by_id=None,
        source=SOURCE_MANUAL,
    )
    db.flush()
    assert job.id is not None
    assert job.status == JOB_PENDING
    assert job.total_count == 2
    assert job.created_by_id is None
    items = db.query(ParaGanarConsultaJobItem).filter_by(job_id=job.id).order_by(ParaGanarConsultaJobItem.mla).all()
    assert [i.mla for i in items] == ["MLA1", "MLA2"]
    assert all(i.status == ITEM_PENDING for i in items)


def test_enqueue_rejects_empty(db) -> None:
    try:
        consulta.enqueue_consulta(db, ["", "  "], created_by_id=None, source=SOURCE_MANUAL)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "vacío" in str(exc)


def test_claim_fairness_prefers_stale_job(db) -> None:
    older = consulta.enqueue_consulta(db, ["MLA_A"], created_by_id=None, source=SOURCE_MANUAL)
    newer = consulta.enqueue_consulta(db, ["MLA_B"], created_by_id=None, source=SOURCE_MANUAL)
    db.flush()
    # Simulate newer job already progressed once.
    newer.last_progress_at = datetime.now(UTC)
    db.flush()

    first = consulta.claim_one(db)
    assert first is not None
    assert first.job_id == older.id
    assert first.mla == "MLA_A"
    item = db.get(ParaGanarConsultaJobItem, first.item_id)
    assert item is not None
    assert item.status == ITEM_PROCESSING
    assert item.attempts == 1
    job = db.get(ParaGanarConsultaJob, older.id)
    assert job is not None
    assert job.status == JOB_RUNNING


def test_process_claim_done_completes_job(db, monkeypatch) -> None:
    job = consulta.enqueue_consulta(db, ["MLA100"], created_by_id=None, source=SOURCE_MANUAL)
    db.flush()
    claim = consulta.claim_one(db)
    assert claim is not None

    monkeypatch.setattr(
        consulta,
        "refrescar_competencia_catalogo",
        lambda _db, _mlas: [SimpleNamespace(fetch_status="ok", error_detail=None)],
    )
    monkeypatch.setattr(consulta, "evaluar_mla", lambda _db, _mla, updated_by_id=None: "pendiente")
    monkeypatch.setattr(consulta, "resolve_maybe_async", lambda value: value)

    outcome = consulta.process_claim(db, claim)
    assert outcome == ITEM_DONE
    item = db.get(ParaGanarConsultaJobItem, claim.item_id)
    assert item is not None
    assert item.status == ITEM_DONE
    assert item.revision_estado == "pendiente"
    refreshed = db.get(ParaGanarConsultaJob, job.id)
    assert refreshed is not None
    assert refreshed.status == JOB_COMPLETED
    assert refreshed.done_count == 1
    assert refreshed.pendiente_count == 1


def test_process_claim_skips_failed_refresh(db, monkeypatch) -> None:
    job = consulta.enqueue_consulta(db, ["MLA_BAD"], created_by_id=None, source=SOURCE_MANUAL)
    db.flush()
    claim = consulta.claim_one(db)
    assert claim is not None

    monkeypatch.setattr(
        consulta,
        "refrescar_competencia_catalogo",
        lambda _db, _mlas: [SimpleNamespace(fetch_status="error", error_detail="boom")],
    )
    monkeypatch.setattr(consulta, "resolve_maybe_async", lambda value: value)

    outcome = consulta.process_claim(db, claim)
    assert outcome == ITEM_SKIPPED
    item = db.get(ParaGanarConsultaJobItem, claim.item_id)
    assert item is not None
    assert item.status == ITEM_SKIPPED
    refreshed = db.get(ParaGanarConsultaJob, job.id)
    assert refreshed is not None
    assert refreshed.status == JOB_COMPLETED
    assert refreshed.skipped_count == 1


def test_settle_failure_retries_then_fails(db) -> None:
    job = consulta.enqueue_consulta(db, ["MLA_X"], created_by_id=None, source=SOURCE_MANUAL)
    db.flush()
    for attempt in range(1, consulta.MAX_ATTEMPTS + 1):
        claim = consulta.claim_one(db)
        assert claim is not None
        assert claim.attempts == attempt
        consulta.settle_failure(db, claim, "boom")
        item = db.get(ParaGanarConsultaJobItem, claim.item_id)
        assert item is not None
        if attempt < consulta.MAX_ATTEMPTS:
            assert item.status == ITEM_PENDING
        else:
            assert item.status == ITEM_FAILED
    refreshed = db.get(ParaGanarConsultaJob, job.id)
    assert refreshed is not None
    assert refreshed.failed_count == 1
    assert refreshed.status == JOB_COMPLETED or refreshed.status == "failed"


def test_reclaim_stale_processing(db) -> None:
    job = consulta.enqueue_consulta(db, ["MLA_STALE"], created_by_id=None, source=SOURCE_MANUAL)
    db.flush()
    claim = consulta.claim_one(db)
    assert claim is not None
    job_row = db.get(ParaGanarConsultaJob, job.id)
    assert job_row is not None
    job_row.last_progress_at = datetime.now(UTC) - consulta.PROCESSING_LEASE - timedelta(seconds=1)
    db.flush()

    n = consulta.reclaim_stale_processing(db)
    assert n == 1
    item = db.get(ParaGanarConsultaJobItem, claim.item_id)
    assert item is not None
    assert item.status == ITEM_PENDING


def test_handler_contract() -> None:
    assert para_ganar_consulta.name == "para_ganar.consulta"
    assert para_ganar_consulta.channels == (consulta.CHANNEL,)
    assert para_ganar_consulta.interval == timedelta(seconds=30)


def test_periodic_handler_is_every_two_hours() -> None:
    assert para_ganar_consulta_periodic.name == "para_ganar.consulta_periodic"
    assert para_ganar_consulta_periodic.channels == ()
    assert para_ganar_consulta_periodic.interval == timedelta(hours=2)
    assert consulta.PERIODIC_INTERVAL == timedelta(hours=2)


def test_enqueue_periodic_skips_when_open_or_empty(db, monkeypatch) -> None:
    monkeypatch.setattr(consulta, "list_mlas_periodicidad_enabled", lambda _db: [])
    assert consulta.enqueue_periodic_consulta(db) is None

    monkeypatch.setattr(consulta, "list_mlas_periodicidad_enabled", lambda _db: ["MLA_P1", "MLA_P2"])
    job = consulta.enqueue_periodic_consulta(db)
    db.flush()
    assert job is not None
    assert job.source == SOURCE_PERIODIC
    assert job.created_by_id is None
    assert job.total_count == 2

    again = consulta.enqueue_periodic_consulta(db)
    assert again is None

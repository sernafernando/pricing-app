"""Unit tests for OC-match enqueue reuse, claim, retry, and 15-min reclaim."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.compra_adjunto import CompraAdjunto
from app.models.empresa import Empresa
from app.models.oc_match_job import OcMatchJob
from app.models.proveedor import Proveedor
from app.services import pedidos_service
from app.services.oc_match.enqueue import (
    SKIP_MESSAGE,
    STALE_MESSAGE,
    claim_queued_job,
    delete_jobs_for_attachment,
    enqueue_oc_match,
    process_oc_match_job,
    queue_retry,
    reclaim_stale_running,
)

_ENQUEUE = Path(__file__).resolve().parents[2] / "app" / "services" / "oc_match" / "enqueue.py"

_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
_XLSX = b"PK\x03\x04" + b"\x00" * 20


def _empresa_proveedor(db) -> tuple[Empresa, Proveedor]:
    empresa = Empresa(nombre="OcMatchReclaimEmp", activo=True, orden=1)
    proveedor = Proveedor(nombre="OcMatchReclaimProv", activo=True, origen="manual")
    db.add_all([empresa, proveedor])
    db.flush()
    return empresa, proveedor


def _pedido_y_adjunto(db, active_user, *, nombre: str = "proforma.pdf"):
    empresa, proveedor = _empresa_proveedor(db)
    pedido = pedidos_service.crear_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000"),
        creado_por_id=active_user.id,
    )
    adj = CompraAdjunto(
        entidad_tipo=CompraAdjunto.ENTIDAD_TIPO_PEDIDO,
        entidad_id=pedido.id,
        nombre_archivo=nombre,
        path_archivo=f"pedido_compra/{pedido.id}/{nombre}",
        mime_type="application/pdf",
    )
    db.add(adj)
    db.flush()
    return pedido, adj


class TestEnqueueReuse:
    def test_same_pair_reuses_and_does_not_reschedule(self, db, active_user) -> None:
        pedido, adj = _pedido_y_adjunto(db, active_user)
        first = enqueue_oc_match(
            db,
            pedido_id=pedido.id,
            attachment_id=adj.id,
            filename=adj.nombre_archivo,
            content=_PDF,
        )
        second = enqueue_oc_match(
            db,
            pedido_id=pedido.id,
            attachment_id=adj.id,
            filename=adj.nombre_archivo,
            content=_PDF,
        )
        assert first.created is True
        assert first.scheduled is True
        assert first.job.status == OcMatchJob.STATUS_QUEUED
        assert second.created is False
        assert second.scheduled is False
        assert second.job.id == first.job.id

    def test_xlsx_is_skipped_without_schedule(self, db, active_user) -> None:
        pedido, adj = _pedido_y_adjunto(db, active_user, nombre="carga.xlsx")
        result = enqueue_oc_match(
            db,
            pedido_id=pedido.id,
            attachment_id=adj.id,
            filename="carga.xlsx",
            content=_XLSX,
        )
        assert result.created is True
        assert result.scheduled is False
        assert result.job.status == OcMatchJob.STATUS_SKIPPED
        assert result.job.error_message == SKIP_MESSAGE


class TestClaimAndRetry:
    def test_claim_queued_is_cas(self, db, active_user) -> None:
        pedido, adj = _pedido_y_adjunto(db, active_user)
        result = enqueue_oc_match(
            db,
            pedido_id=pedido.id,
            attachment_id=adj.id,
            filename=adj.nombre_archivo,
            content=_PDF,
        )
        claimed = claim_queued_job(db, result.job.id)
        assert claimed is not None
        assert claimed.status == OcMatchJob.STATUS_RUNNING
        assert claim_queued_job(db, result.job.id) is None

    def test_queue_retry_only_from_error(self, db, active_user) -> None:
        pedido, adj = _pedido_y_adjunto(db, active_user)
        result = enqueue_oc_match(
            db,
            pedido_id=pedido.id,
            attachment_id=adj.id,
            filename=adj.nombre_archivo,
            content=_PDF,
        )
        with pytest.raises(ValueError, match="not retryable"):
            queue_retry(db, result.job)
        result.job.status = OcMatchJob.STATUS_ERROR
        retried = queue_retry(db, result.job)
        assert retried.status == OcMatchJob.STATUS_QUEUED
        assert retried.error_message is None


class TestReclaimStaleRunning:
    def test_running_over_15_minutes_becomes_retryable_error(self, db, active_user) -> None:
        pedido, adj = _pedido_y_adjunto(db, active_user)
        now = datetime.now(UTC)
        job = OcMatchJob(
            pedido_id=pedido.id,
            attachment_id=adj.id,
            status=OcMatchJob.STATUS_RUNNING,
            started_at=now - timedelta(minutes=16),
        )
        db.add(job)
        db.flush()
        marked = reclaim_stale_running(db, now=now)
        db.refresh(job)
        assert marked == 1
        assert job.status == OcMatchJob.STATUS_ERROR
        assert job.error_message == STALE_MESSAGE

    def test_fresh_running_is_left_alone(self, db, active_user) -> None:
        pedido, adj = _pedido_y_adjunto(db, active_user)
        now = datetime.now(UTC)
        job = OcMatchJob(
            pedido_id=pedido.id,
            attachment_id=adj.id,
            status=OcMatchJob.STATUS_RUNNING,
            started_at=now - timedelta(minutes=5),
        )
        db.add(job)
        db.flush()
        assert reclaim_stale_running(db, now=now) == 0
        db.refresh(job)
        assert job.status == OcMatchJob.STATUS_RUNNING


class TestStubWorkerAndNoMail:
    def test_process_stub_leaves_queued_job(self, db, active_user) -> None:
        pedido, adj = _pedido_y_adjunto(db, active_user)
        result = enqueue_oc_match(
            db,
            pedido_id=pedido.id,
            attachment_id=adj.id,
            filename=adj.nombre_archivo,
            content=_PDF,
        )
        process_oc_match_job(result.job.id)
        db.refresh(result.job)
        assert result.job.status == OcMatchJob.STATUS_QUEUED

    def test_enqueue_source_has_no_gemini_or_mail(self) -> None:
        source = _ENQUEUE.read_text(encoding="utf-8")
        assert "google.genai" not in source
        assert "GEMINI_API_KEY" not in source
        assert "smtp" not in source.lower()
        assert "enviar_mail" not in source
        assert "notificacion_service" not in source


class TestDeleteJobsForAttachment:
    def test_deletes_job_so_adjunto_fk_can_clear(self, db, active_user) -> None:
        pedido, adj = _pedido_y_adjunto(db, active_user)
        result = enqueue_oc_match(
            db,
            pedido_id=pedido.id,
            attachment_id=adj.id,
            filename=adj.nombre_archivo,
            content=_PDF,
        )
        job_id = result.job.id
        assert delete_jobs_for_attachment(db, adj.id) == 1
        assert db.get(OcMatchJob, job_id) is None
        assert delete_jobs_for_attachment(db, adj.id) == 0

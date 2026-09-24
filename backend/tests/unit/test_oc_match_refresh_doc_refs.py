"""Unit tests for extract-only OC-match refresh-doc-refs persist."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.services.oc_match import refresh_doc_refs as mod
from app.services.oc_match.refresh_doc_refs import refresh_doc_refs_job

STAMP = datetime(2026, 9, 1, tzinfo=UTC)
EXTRACTED = {
    "tipo_documento": "factura",
    "nro_documento": "0001-99",
    "nro_pedido": "PED-1",
}


def _job(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "id": 1,
        "status": "done",
        "doc_refs_aplicado_at": STAMP,
        "attachment_id": 9,
        "pedido_id": 3,
        "acta": "KEEP-ACTA",
        "excel_rel_path": "keep.xlsx",
        "progress_phase": None,
        "renglones": ["keep"],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _adjunto() -> SimpleNamespace:
    return SimpleNamespace(path_archivo="a.pdf", nombre_archivo="a.pdf")


def _pedido() -> SimpleNamespace:
    return SimpleNamespace(
        facturas_documento="KEEP-FA",
        pedidos_documento=None,
        numero_factura="ERP-KEEP",
    )


def _session_get(job: SimpleNamespace, adj: SimpleNamespace) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = [job, adj]
    return session


def _session_persist(job: SimpleNamespace, pedido: SimpleNamespace) -> MagicMock:
    session = MagicMock()
    calls = {"n": 0}

    def _execute(_stmt: object) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.one_or_none.return_value = job if calls["n"] == 0 else pedido
        calls["n"] += 1
        return result

    session.execute.side_effect = _execute
    return session


def _patch_bg(monkeypatch: pytest.MonkeyPatch, sessions: list[MagicMock]) -> None:
    leftover = list(sessions)

    @contextmanager
    def _cm():
        yield leftover.pop(0)

    monkeypatch.setattr(mod, "get_background_db", _cm)


@pytest.fixture
def pdf_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    uploads = tmp_path / "compras"
    uploads.mkdir()
    (uploads / "a.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(settings, "COMPRAS_UPLOADS_DIR", str(uploads))
    return uploads


@contextmanager
def _assert_no_rematch_side_effects() -> Iterator[tuple[MagicMock, MagicMock, MagicMock, MagicMock]]:
    with (
        patch("app.services.oc_match.match.match_renglones") as match,
        patch("app.services.oc_match.excel.generar") as excel,
        patch("app.services.oc_match.enqueue.queue_retry") as retry,
        patch("app.services.notificacion_service.crear_notificaciones_para_permisos") as mail,
    ):
        yield match, excel, retry, mail


class TestRefreshDocRefsPersist:
    def test_failed_extract_keeps_stamp(self, pdf_dir, monkeypatch: pytest.MonkeyPatch) -> None:
        job = _job()
        _patch_bg(monkeypatch, [_session_get(job, _adjunto())])
        monkeypatch.setattr(mod, "load_pool", lambda: object())
        monkeypatch.setattr(mod, "extract_one", MagicMock(side_effect=RuntimeError("gemini 503")))
        writeback = MagicMock()
        monkeypatch.setattr(mod, "apply_writeback", writeback)

        with _assert_no_rematch_side_effects() as (match, excel, retry, mail):
            refresh_doc_refs_job(1)
            match.assert_not_called()
            excel.assert_not_called()
            retry.assert_not_called()
            mail.assert_not_called()

        assert job.doc_refs_aplicado_at == STAMP
        assert job.status == "done"
        assert job.acta == "KEEP-ACTA"
        assert job.excel_rel_path == "keep.xlsx"
        assert job.progress_phase is None
        assert job.renglones == ["keep"]
        writeback.assert_not_called()

    def test_skip_if_status_left(self, pdf_dir, monkeypatch: pytest.MonkeyPatch) -> None:
        job = _job()
        pedido = _pedido()
        _patch_bg(monkeypatch, [_session_get(job, _adjunto()), _session_persist(job, pedido)])

        def _extract(*_args: object, **_kwargs: object) -> dict:
            job.status = "queued"
            return EXTRACTED

        monkeypatch.setattr(mod, "load_pool", lambda: object())
        monkeypatch.setattr(mod, "extract_one", _extract)
        writeback = MagicMock()
        monkeypatch.setattr(mod, "apply_writeback", writeback)

        refresh_doc_refs_job(1)

        assert job.status == "queued"
        assert job.doc_refs_aplicado_at == STAMP
        assert job.acta == "KEEP-ACTA"
        assert job.renglones == ["keep"]
        writeback.assert_not_called()
        assert pedido.numero_factura == "ERP-KEEP"

    def test_success_clears_then_writeback_and_restamp(self, pdf_dir, monkeypatch: pytest.MonkeyPatch) -> None:
        job = _job()
        pedido = _pedido()
        _patch_bg(monkeypatch, [_session_get(job, _adjunto()), _session_persist(job, pedido)])
        seen: dict[str, object] = {}

        def _writeback(locked: SimpleNamespace, extracted: dict) -> bool:
            seen["stamp_at_wb"] = job.doc_refs_aplicado_at
            locked.facturas_documento = extracted["nro_documento"]
            return True

        monkeypatch.setattr(mod, "load_pool", lambda: object())
        monkeypatch.setattr(mod, "extract_one", MagicMock(return_value=EXTRACTED))
        monkeypatch.setattr(mod, "apply_writeback", _writeback)

        with _assert_no_rematch_side_effects() as (match, excel, retry, mail):
            refresh_doc_refs_job(1)
            match.assert_not_called()
            excel.assert_not_called()
            retry.assert_not_called()
            mail.assert_not_called()

        assert seen["stamp_at_wb"] is None
        assert job.doc_refs_aplicado_at is not None
        assert job.doc_refs_aplicado_at.tzinfo is UTC
        assert job.doc_refs_aplicado_at != STAMP
        assert pedido.facturas_documento == "0001-99"
        assert pedido.numero_factura == "ERP-KEEP"
        assert job.status == "done"
        assert job.acta == "KEEP-ACTA"
        assert job.excel_rel_path == "keep.xlsx"
        assert job.progress_phase is None
        assert job.renglones == ["keep"]

    def test_error_job_stays_error(self, pdf_dir, monkeypatch: pytest.MonkeyPatch) -> None:
        job = _job(status="error")
        pedido = _pedido()
        _patch_bg(monkeypatch, [_session_get(job, _adjunto()), _session_persist(job, pedido)])
        monkeypatch.setattr(mod, "load_pool", lambda: object())
        monkeypatch.setattr(mod, "extract_one", MagicMock(return_value=EXTRACTED))
        monkeypatch.setattr(mod, "apply_writeback", lambda *_a, **_k: True)

        refresh_doc_refs_job(1)

        assert job.status == "error"
        assert job.doc_refs_aplicado_at is not None
        assert pedido.numero_factura == "ERP-KEEP"

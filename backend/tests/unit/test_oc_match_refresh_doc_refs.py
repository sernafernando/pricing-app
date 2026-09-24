"""Unit tests for extract-only OC-match refresh-doc-refs persist."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.models.compra_adjunto import CompraAdjunto
from app.models.empresa import Empresa
from app.models.oc_match_job import OcMatchJob
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_factura_documento import PedidoFacturaDocumento
from app.models.proveedor import Proveedor
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
        id=3,
        facturas_documento="KEEP-FA",
        pedidos_documento=None,
        numero_factura="ERP-KEEP",
        creado_por_id=7,
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
        monkeypatch.setattr(mod.pedidos_service, "persist_factura_documento", MagicMock())

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
        monkeypatch.setattr(mod.pedidos_service, "persist_factura_documento", MagicMock())

        refresh_doc_refs_job(1)

        assert job.status == "error"
        assert job.doc_refs_aplicado_at is not None
        assert pedido.numero_factura == "ERP-KEEP"


def _seed_refresh_pedido(
    db,
    active_user,
    *,
    numero: str = "P-RF-2026-00001",
    facturas_documento: str | None = None,
    numero_factura: str | None = "ERP-KEEP",
) -> tuple[OcMatchJob, PedidoCompra]:
    empresa = Empresa(nombre="EmpRefreshFactura", activo=True, orden=1)
    db.add(empresa)
    db.flush()
    proveedor = Proveedor(nombre="ProvRefreshFactura", activo=True, origen="manual")
    db.add(proveedor)
    db.flush()
    pedido = PedidoCompra(
        numero=numero,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000.00"),
        estado="borrador",
        creado_por_id=active_user.id,
        facturas_documento=facturas_documento,
        numero_factura=numero_factura,
    )
    db.add(pedido)
    db.flush()
    adj = CompraAdjunto(
        entidad_tipo=CompraAdjunto.ENTIDAD_TIPO_PEDIDO,
        entidad_id=pedido.id,
        nombre_archivo="a.pdf",
        path_archivo="a.pdf",
    )
    db.add(adj)
    db.flush()
    job = OcMatchJob(
        pedido_id=pedido.id,
        attachment_id=adj.id,
        status=OcMatchJob.STATUS_DONE,
        acta="KEEP-ACTA",
        excel_rel_path="keep.xlsx",
        doc_refs_aplicado_at=STAMP,
    )
    db.add(job)
    db.flush()
    return job, pedido


def _factura_rows(db, pedido_id: int) -> list[PedidoFacturaDocumento]:
    return (
        db.query(PedidoFacturaDocumento)
        .filter(PedidoFacturaDocumento.pedido_id == pedido_id)
        .order_by(PedidoFacturaDocumento.id)
        .all()
    )


class TestRefreshDocRefsFacturaRow:
    """Real apply_writeback → pedido_factura_documentos. Do not mock writeback."""

    def test_factura_inserts_normalized_row(self, pdf_dir, db, active_user, monkeypatch: pytest.MonkeyPatch) -> None:
        job, pedido = _seed_refresh_pedido(db, active_user)
        _patch_bg(monkeypatch, [db, db])
        monkeypatch.setattr(mod, "load_pool", lambda: object())
        monkeypatch.setattr(mod, "extract_one", MagicMock(return_value=EXTRACTED))

        refresh_doc_refs_job(job.id)

        db.refresh(pedido)
        db.refresh(job)
        rows = _factura_rows(db, pedido.id)
        assert [row.numero for row in rows] == ["0001-99"]
        assert rows[0].created_by_id == pedido.creado_por_id == active_user.id
        assert rows[0].cargada is False
        assert pedido.facturas_documento == "0001-99"
        assert pedido.numero_factura == "ERP-KEEP"
        assert job.doc_refs_aplicado_at is not None
        assert job.doc_refs_aplicado_at != STAMP

    def test_reextract_restores_deleted_row(self, pdf_dir, db, active_user, monkeypatch: pytest.MonkeyPatch) -> None:
        job, pedido = _seed_refresh_pedido(db, active_user, facturas_documento="0001-99")
        _patch_bg(monkeypatch, [db, db])
        monkeypatch.setattr(mod, "load_pool", lambda: object())
        monkeypatch.setattr(mod, "extract_one", MagicMock(return_value=EXTRACTED))

        refresh_doc_refs_job(job.id)

        db.refresh(pedido)
        rows = _factura_rows(db, pedido.id)
        assert [row.numero for row in rows] == ["0001-99"]
        assert rows[0].created_by_id == pedido.creado_por_id
        assert pedido.facturas_documento == "0001-99"

    def test_non_factura_skips_row(self, pdf_dir, db, active_user, monkeypatch: pytest.MonkeyPatch) -> None:
        job, pedido = _seed_refresh_pedido(db, active_user)
        extracted = {**EXTRACTED, "tipo_documento": "pedido"}
        _patch_bg(monkeypatch, [db, db])
        monkeypatch.setattr(mod, "load_pool", lambda: object())
        monkeypatch.setattr(mod, "extract_one", MagicMock(return_value=extracted))

        refresh_doc_refs_job(job.id)

        db.refresh(pedido)
        db.refresh(job)
        assert _factura_rows(db, pedido.id) == []
        assert pedido.numero_factura == "ERP-KEEP"
        assert job.doc_refs_aplicado_at is not None

    def test_empty_nro_documento_skips_row(self, pdf_dir, db, active_user, monkeypatch: pytest.MonkeyPatch) -> None:
        job, pedido = _seed_refresh_pedido(db, active_user)
        extracted = {**EXTRACTED, "nro_documento": "  "}
        _patch_bg(monkeypatch, [db, db])
        monkeypatch.setattr(mod, "load_pool", lambda: object())
        monkeypatch.setattr(mod, "extract_one", MagicMock(return_value=extracted))

        refresh_doc_refs_job(job.id)

        db.refresh(pedido)
        db.refresh(job)
        assert _factura_rows(db, pedido.id) == []
        assert pedido.numero_factura == "ERP-KEEP"
        assert job.doc_refs_aplicado_at is not None

    def test_writeback_false_skips_row_and_does_not_restamp(
        self, pdf_dir, db, active_user, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job, pedido = _seed_refresh_pedido(db, active_user)
        extracted = {**EXTRACTED, "tipo_documento": "comprobante_pago"}
        _patch_bg(monkeypatch, [db, db])
        monkeypatch.setattr(mod, "load_pool", lambda: object())
        monkeypatch.setattr(mod, "extract_one", MagicMock(return_value=extracted))

        refresh_doc_refs_job(job.id)

        db.refresh(pedido)
        db.refresh(job)
        assert _factura_rows(db, pedido.id) == []
        assert pedido.facturas_documento is None
        assert pedido.numero_factura == "ERP-KEEP"
        assert job.doc_refs_aplicado_at is None

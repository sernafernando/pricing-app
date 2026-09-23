"""Integration tests for the two-session OC-match worker (mocked Gemini pool)."""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.compra_adjunto import CompraAdjunto
from app.models.empresa import Empresa
from app.models.oc_match_job import OcMatchJob, OcMatchRenglon
from app.models.notificacion import Notificacion
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_factura_documento import PedidoFacturaDocumento
from app.models.proveedor import Proveedor
from app.models.tb_brand import TBBrand
from app.models.tb_category import TBCategory
from app.models.tb_item import TBItem
from app.models.tb_subcategory import TBSubCategory
from app.services import pedidos_service
from app.services.oc_match import worker as worker_mod
from app.services.oc_match.doc_refs import apply_writeback
from app.services.oc_match.enqueue import enqueue_oc_match, queue_retry
from app.services.oc_match.worker import process_oc_match_job

BASE = "/api/administracion/compras"
PDF_HEADER = b"%PDF-1.4\n" + b"0" * 200
_SERVICES = Path(__file__).resolve().parents[2] / "app" / "services" / "oc_match"

GOLDEN_EXTRACT: dict[str, Any] = {
    "proveedor_razon_social": "Distecna SA",
    "proveedor_cuit": "30714636827",
    "nro_documento": "0001-99",
    "nro_pedido": "PED-184465",
    "tipo_documento": "factura",
    "fecha": "2026-09-01",
    "moneda": "ARS",
    "tipo_cambio": None,
    "descuento_pct": None,
    "renglones": [
        {
            "descripcion": "Mouse Logitech M196 Negro",
            "cantidad": 2,
            "precio_unitario": 10.5,
            "moneda": "ARS",
            "codigo_proveedor": None,
            "codigo_fabricante": "M196",
            "ean": "7790123456789",
            "ean_ultimos4": "6789",
            "omitir": False,
            "motivo_omitir": None,
        },
        {
            "descripcion": "Cable HDMI 3 pack especial",
            "cantidad": 1,
            "precio_unitario": 3,
            "moneda": "ARS",
            "codigo_proveedor": None,
            "codigo_fabricante": None,
            "ean": None,
            "ean_ultimos4": None,
            "omitir": False,
            "motivo_omitir": None,
        },
    ],
}

GOLDEN_MATCH: dict[str, Any] = {
    "decisiones": [
        {
            "indice": 0,
            "item_id": "101",
            "ean": "7790123456789",
            "confianza": "alta",
            "motivo": "ean+desc",
        },
        {
            "indice": 1,
            "item_id": None,
            "ean": None,
            "confianza": "baja",
            "motivo": "pack 3 no coincide",
        },
    ]
}

GOLDEN_EXTRACT_USD = {
    **GOLDEN_EXTRACT,
    "moneda": "USD",
    "tipo_cambio": None,
    "renglones": [
        {
            **GOLDEN_EXTRACT["renglones"][0],
            "moneda": "USD",
        }
    ],
}

GOLDEN_MATCH_USD: dict[str, Any] = {
    "decisiones": [
        {
            "indice": 0,
            "item_id": "101",
            "ean": "7790123456789",
            "confianza": "alta",
            "motivo": "ean+desc",
        }
    ]
}


@pytest.fixture(autouse=True)
def _dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    uploads = tmp_path / "compras"
    oc_dir = tmp_path / "compras_oc"
    uploads.mkdir()
    oc_dir.mkdir()
    monkeypatch.setattr(settings, "COMPRAS_UPLOADS_DIR", str(uploads))
    monkeypatch.setattr(settings, "COMPRAS_OC_MATCH_DIR", str(oc_dir))
    monkeypatch.setattr(settings, "COMPRAS_OC_MATCH_ENABLED", True)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-1")
    monkeypatch.setattr(settings, "GEMINI_API_KEY_2", None)
    monkeypatch.setattr(settings, "GEMINI_API_KEY_3", None)
    return oc_dir


@pytest.fixture
def con_todos_los_permisos() -> Iterator[None]:
    from unittest.mock import patch

    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.tiene_algun_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


def _patch_bg_db(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    @contextmanager
    def _cm() -> Iterator[Session]:
        yield db

    monkeypatch.setattr(worker_mod, "get_background_db", _cm)


def _seed_maestro(db: Session) -> None:
    db.add_all(
        [
            TBBrand(comp_id=1, brand_id=7, brand_desc="Logitech"),
            TBCategory(comp_id=1, cat_id=3, cat_desc="Perifericos"),
            TBSubCategory(comp_id=1, cat_id=3, subcat_id=4, subcat_desc="Mouse"),
            TBItem(
                comp_id=1,
                item_id=101,
                item_code="7790123456789",
                item_desc="Mouse Logitech M196 Negro",
                cat_id=3,
                subcat_id=4,
                brand_id=7,
            ),
            TBItem(
                comp_id=1,
                item_id=102,
                item_code="7790123456789-16",
                item_desc="Notebook combo interno",
                cat_id=3,
                subcat_id=4,
                brand_id=7,
            ),
        ]
    )
    db.flush()


def _empresa(db: Session, *, empresa_id: int, nombre: str) -> Empresa:
    e = Empresa(id=empresa_id, nombre=nombre, activo=True, orden=empresa_id)
    db.add(e)
    db.flush()
    return e


def _proveedor(db: Session) -> Proveedor:
    p = Proveedor(nombre="ProvOcMatchPipe", activo=True, origen="manual")
    db.add(p)
    db.flush()
    return p


def _pedido_adjunto_job(
    db: Session,
    active_user: Any,
    tmp_path: Path,
    *,
    empresa_id: int = 1,
    empresa_nombre: str = "Pastoriza",
) -> tuple[OcMatchJob, Path]:
    empresa = db.get(Empresa, empresa_id) or _empresa(db, empresa_id=empresa_id, nombre=empresa_nombre)
    proveedor = _proveedor(db)
    pedido = pedidos_service.crear_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000"),
        creado_por_id=active_user.id,
    )
    rel = f"pedido_compra/{pedido.id}/proforma.pdf"
    dest = Path(settings.COMPRAS_UPLOADS_DIR) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(PDF_HEADER)
    adj = CompraAdjunto(
        entidad_tipo=CompraAdjunto.ENTIDAD_TIPO_PEDIDO,
        entidad_id=pedido.id,
        nombre_archivo="proforma.pdf",
        path_archivo=rel,
        mime_type="application/pdf",
    )
    db.add(adj)
    db.flush()
    result = enqueue_oc_match(
        db,
        pedido_id=pedido.id,
        attachment_id=adj.id,
        filename="proforma.pdf",
        content=PDF_HEADER,
    )
    return result.job, dest


def _mock_pool(monkeypatch: pytest.MonkeyPatch, extract: dict[str, Any], match: dict[str, Any]) -> MagicMock:
    pool = MagicMock()
    pool.generate_json.side_effect = [extract, match]
    monkeypatch.setattr(worker_mod, "load_pool", lambda: pool)
    return pool


class TestGoldenWorkerSoT:
    def test_mocked_pool_persists_renglones_acta_xlsx(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)
        pool = _mock_pool(monkeypatch, GOLDEN_EXTRACT, GOLDEN_MATCH)
        fab_spy = MagicMock(side_effect=AssertionError("match_fabricante_exacto must not run"))
        monkeypatch.setattr("app.services.oc_match.candidatos.match_fabricante_exacto", fab_spy)
        _patch_bg_db(monkeypatch, db)

        process_oc_match_job(job.id)
        fab_spy.assert_not_called()
        db.refresh(job)

        assert job.status == OcMatchJob.STATUS_DONE
        assert job.error_message is None
        assert job.acta is not None
        assert "Mouse Logitech M196 Negro" in job.acta
        assert "Cable HDMI 3 pack especial" in job.acta
        assert "NO HALLADOS" in job.acta
        assert job.excel_rel_path
        excel = Path(settings.COMPRAS_OC_MATCH_DIR) / job.excel_rel_path
        assert excel.is_file()
        assert excel.stat().st_size > 0

        renglones = (
            db.query(OcMatchRenglon).filter(OcMatchRenglon.job_id == job.id).order_by(OcMatchRenglon.indice).all()
        )
        assert len(renglones) == 2
        assert renglones[0].match_estado == OcMatchRenglon.MATCH_OK
        assert renglones[0].item_id == "101"
        assert renglones[0].ean == "7790123456789"
        assert renglones[1].match_estado == OcMatchRenglon.MATCH_NO_HALLADO
        assert pool.generate_json.call_count == 2

        pedido = db.get(PedidoCompra, job.pedido_id)
        assert pedido is not None
        assert pedido.facturas_documento == "0001-99"
        assert pedido.pedidos_documento == "PED-184465"
        assert pedido.numero_factura is None
        assert job.doc_refs_aplicado_at is not None
        apply_writeback(pedido, GOLDEN_EXTRACT)
        assert pedido.facturas_documento == "0001-99"
        assert pedido.pedidos_documento == "PED-184465"

    def test_factura_fa10_persists_row_chip_off_no_notif(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        extract = {**GOLDEN_EXTRACT, "nro_documento": "FA-10"}
        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)
        _mock_pool(monkeypatch, extract, GOLDEN_MATCH)
        _patch_bg_db(monkeypatch, db)

        process_oc_match_job(job.id)
        db.refresh(job)
        pedido = db.get(PedidoCompra, job.pedido_id)
        assert pedido is not None
        rows = (
            db.query(PedidoFacturaDocumento)
            .filter(PedidoFacturaDocumento.pedido_id == pedido.id)
            .order_by(PedidoFacturaDocumento.id)
            .all()
        )
        assert [row.numero for row in rows] == ["FA-10"]
        assert rows[0].created_by_id == pedido.creado_por_id == active_user.id
        assert rows[0].cargada is False
        assert pedidos_service.es_factura_cargada(db, pedido.id) is False
        assert pedidos_service.tiene_numero_factura(db, pedido.id) is True
        chips = pedidos_service.chips_visibilidad_batch(db, [pedido.id])
        assert chips[pedido.id]["factura_cargada"] is False
        assert chips[pedido.id]["tiene_numero_factura"] is True
        assert db.query(Notificacion).filter(Notificacion.tipo == "compras.factura_cargada").count() == 0
        apply_writeback(pedido, extract)
        assert pedido.facturas_documento == "FA-10"
        assert db.query(PedidoFacturaDocumento).filter(PedidoFacturaDocumento.pedido_id == pedido.id).count() == 1

    def test_factura_casefold_duplicate_skips_second_row(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        extract = {**GOLDEN_EXTRACT, "nro_documento": "fa-10"}
        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)
        pedido = db.get(PedidoCompra, job.pedido_id)
        assert pedido is not None
        pedidos_service.persist_factura_documento(
            db,
            pedido=pedido,
            numero="FA-10",
            created_by_id=active_user.id,
        )
        db.flush()
        _mock_pool(monkeypatch, extract, GOLDEN_MATCH)
        _patch_bg_db(monkeypatch, db)

        process_oc_match_job(job.id)
        db.refresh(pedido)
        rows = db.query(PedidoFacturaDocumento).filter(PedidoFacturaDocumento.pedido_id == pedido.id).all()
        assert [row.numero for row in rows] == ["FA-10"]

    def test_factura_overflow_token_skips_row(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        overflow = "Z" * 101
        extract = {**GOLDEN_EXTRACT, "nro_documento": overflow}
        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)
        _mock_pool(monkeypatch, extract, GOLDEN_MATCH)
        _patch_bg_db(monkeypatch, db)

        process_oc_match_job(job.id)
        pedido = db.get(PedidoCompra, job.pedido_id)
        assert pedido is not None
        assert pedido.facturas_documento == overflow
        assert db.query(PedidoFacturaDocumento).filter(PedidoFacturaDocumento.pedido_id == pedido.id).count() == 0
        assert pedidos_service.es_factura_cargada(db, pedido.id) is False

    def test_excel_get_returns_file(
        self,
        client: Any,
        auth_headers: dict[str, str],
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        con_todos_los_permisos: None,
    ) -> None:
        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)
        _mock_pool(monkeypatch, GOLDEN_EXTRACT, GOLDEN_MATCH)
        _patch_bg_db(monkeypatch, db)
        process_oc_match_job(job.id)
        db.refresh(job)

        r = client.get(f"{BASE}/oc-match/jobs/{job.id}/excel", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert "spreadsheetml" in (r.headers.get("content-type") or "")
        assert r.content[:2] == b"PK"


class TestWorkerErrorPaths:
    def test_usd_sin_tc_is_error_without_xlsx_success(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)
        _mock_pool(monkeypatch, GOLDEN_EXTRACT_USD, GOLDEN_MATCH_USD)
        _patch_bg_db(monkeypatch, db)

        process_oc_match_job(job.id)
        db.refresh(job)

        assert job.status == OcMatchJob.STATUS_ERROR
        assert job.excel_rel_path is None
        assert job.acta is not None
        assert "ERROR" in job.acta
        assert "tipo de cambio" in (job.error_message or "")
        leftover = list(Path(settings.COMPRAS_OC_MATCH_DIR).glob("*.xlsx"))
        assert leftover == []
        renglones = db.query(OcMatchRenglon).filter(OcMatchRenglon.job_id == job.id).all()
        assert renglones
        assert renglones[0].match_estado == OcMatchRenglon.MATCH_OK
        pedido = db.get(PedidoCompra, job.pedido_id)
        assert pedido is not None
        assert pedido.facturas_documento == "0001-99"
        assert pedido.pedidos_documento == "PED-184465"
        assert job.doc_refs_aplicado_at is not None

    def test_unmapped_empresa_errors_without_gemini(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(
            db,
            active_user,
            tmp_path,
            empresa_id=99,
            empresa_nombre="Otra SA",
        )
        pool = _mock_pool(monkeypatch, GOLDEN_EXTRACT, GOLDEN_MATCH)
        _patch_bg_db(monkeypatch, db)

        process_oc_match_job(job.id)
        db.refresh(job)

        assert job.status == OcMatchJob.STATUS_ERROR
        assert "no está mapeada" in (job.error_message or "")
        assert job.acta is not None
        assert "ERROR" in job.acta
        pool.generate_json.assert_not_called()
        pedido = db.get(PedidoCompra, job.pedido_id)
        assert pedido is not None
        assert pedido.facturas_documento is None
        assert pedido.pedidos_documento is None
        assert job.doc_refs_aplicado_at is None

    def test_missing_gemini_keys_error_plus_acta(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)
        monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
        monkeypatch.setattr(settings, "GEMINI_API_KEY_2", None)
        monkeypatch.setattr(settings, "GEMINI_API_KEY_3", None)
        _patch_bg_db(monkeypatch, db)

        process_oc_match_job(job.id)
        db.refresh(job)

        assert job.status == OcMatchJob.STATUS_ERROR
        assert "GEMINI_API_KEY" in (job.error_message or "")
        assert job.acta is not None
        assert "ERROR" in job.acta


class TestProgressPhase:
    def test_phase_sequence_then_persist_null(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)
        _mock_pool(monkeypatch, GOLDEN_EXTRACT, GOLDEN_MATCH)
        _patch_bg_db(monkeypatch, db)
        phases: list[str] = []
        orig = worker_mod._write_progress_phase

        def spy(job_id: int, phase: str, claimed_started_at: Any) -> None:
            orig(job_id, phase, claimed_started_at)
            db.refresh(job)
            assert job.status == OcMatchJob.STATUS_RUNNING
            phases.append(phase)

        monkeypatch.setattr(worker_mod, "_write_progress_phase", spy)
        process_oc_match_job(job.id)
        db.refresh(job)
        assert phases == ["extracting", "matching", "excel"]
        assert job.progress_phase is None
        assert job.status == OcMatchJob.STATUS_DONE

    def test_phase_helper_fail_soft_does_not_raise(
        self,
        db: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from datetime import UTC, datetime

        @contextmanager
        def boom_db() -> Iterator[Any]:
            raise RuntimeError("db down for phase write")
            yield  # pragma: no cover

        monkeypatch.setattr(worker_mod, "get_background_db", boom_db)
        worker_mod._write_progress_phase(1, "extracting", datetime.now(UTC))


class TestClaimFence:
    def test_stale_claim_persist_does_not_overwrite(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from datetime import timedelta

        from app.services.oc_match.enqueue import (
            claim_queued_job,
            queue_retry,
            reclaim_stale_running,
        )

        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)
        _patch_bg_db(monkeypatch, db)

        first = claim_queued_job(db, job.id)
        assert first is not None and first.started_at is not None
        stale_started = first.started_at
        first.started_at = stale_started - timedelta(minutes=50)
        db.flush()
        assert reclaim_stale_running(db) == 1
        db.refresh(job)
        assert job.status == OcMatchJob.STATUS_ERROR

        queue_retry(db, job)
        db.flush()
        second = claim_queued_job(db, job.id)
        assert second is not None and second.started_at is not None
        assert second.started_at != stale_started
        db.refresh(job)
        owner_started = job.started_at

        worker_mod._persist(
            job.id,
            {"renglones": [{"descripcion": "stale", "match": {"estado": "ok"}}]},
            "acta stale",
            None,
            None,
            claimed_started_at=stale_started,
        )
        db.refresh(job)
        assert job.status == OcMatchJob.STATUS_RUNNING
        assert job.started_at == owner_started
        assert job.acta is None
        assert list(job.renglones) == []

        worker_mod._write_progress_phase(job.id, "matching", stale_started)
        db.refresh(job)
        assert job.progress_phase is None

        worker_mod._persist(
            job.id,
            {
                "renglones": [
                    {
                        "descripcion": "owner",
                        "match": {"estado": "ok", "item_id": "1", "confianza": "alta"},
                    }
                ]
            },
            "acta owner",
            "owner.xlsx",
            None,
            claimed_started_at=owner_started,
        )
        db.refresh(job)
        assert job.status == OcMatchJob.STATUS_DONE
        assert job.acta == "acta owner"
        assert len(job.renglones) == 1
        assert job.renglones[0].descripcion == "owner"

    def test_two_claims_get_distinct_excel_paths(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from datetime import timedelta

        from app.services.oc_match.enqueue import claim_queued_job

        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)
        monkeypatch.setenv("COMPRAS_OC_MATCH_DIR", str(tmp_path / "oc"))
        monkeypatch.setattr(settings, "COMPRAS_OC_MATCH_DIR", str(tmp_path / "oc"))

        first = claim_queued_job(db, job.id)
        assert first is not None and first.started_at is not None
        path_a = worker_mod._excel_dest(job.id, first.started_at, GOLDEN_MATCH)
        path_b = worker_mod._excel_dest(
            job.id,
            first.started_at + timedelta(seconds=2),
            GOLDEN_MATCH,
        )
        assert path_a != path_b
        assert str(job.id) in path_a.name
        assert str(job.id) in path_b.name

    def test_stale_rechazo_unlink_does_not_delete_owner_excel(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from datetime import timedelta

        from app.services.oc_match.enqueue import (
            claim_queued_job,
            queue_retry,
            reclaim_stale_running,
        )

        oc_dir = tmp_path / "oc"
        oc_dir.mkdir()
        monkeypatch.setattr(settings, "COMPRAS_OC_MATCH_DIR", str(oc_dir))
        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)

        first = claim_queued_job(db, job.id)
        assert first is not None and first.started_at is not None
        stale_started = first.started_at
        owner_started = stale_started + timedelta(seconds=5)
        owner_path = worker_mod._excel_dest(job.id, owner_started, GOLDEN_MATCH)
        owner_path.write_bytes(b"PK owner")
        stale_path = worker_mod._excel_dest(job.id, stale_started, GOLDEN_MATCH)
        stale_path.write_bytes(b"PK stale")

        worker_mod._unlink_xlsx(stale_path)
        assert not stale_path.exists()
        assert owner_path.exists()

        first.started_at = stale_started - timedelta(minutes=50)
        db.flush()
        reclaim_stale_running(db)
        queue_retry(db, job)
        db.flush()
        claim_queued_job(db, job.id)
        db.refresh(job)
        # Simulate stale RechazoExcel unlink — must not glob-wipe owner
        worker_mod._unlink_xlsx(stale_path)
        assert owner_path.exists()

    def test_discarded_persist_removes_claim_xlsx(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from datetime import timedelta

        from app.services.oc_match.enqueue import (
            claim_queued_job,
            queue_retry,
            reclaim_stale_running,
        )

        oc_dir = tmp_path / "oc"
        oc_dir.mkdir()
        monkeypatch.setattr(settings, "COMPRAS_OC_MATCH_DIR", str(oc_dir))
        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)
        _patch_bg_db(monkeypatch, db)

        first = claim_queued_job(db, job.id)
        assert first is not None and first.started_at is not None
        stale_started = first.started_at
        stale_path = worker_mod._excel_dest(job.id, stale_started, GOLDEN_MATCH)
        stale_path.write_bytes(b"PK stale")

        first.started_at = stale_started - timedelta(minutes=50)
        db.flush()
        reclaim_stale_running(db)
        queue_retry(db, job)
        db.flush()
        second = claim_queued_job(db, job.id)
        assert second is not None

        worker_mod._persist(
            job.id,
            {"renglones": []},
            "acta stale",
            stale_path.name,
            None,
            claimed_started_at=stale_started,
        )
        assert not stale_path.exists()


class TestDocRefsWriteOnce:
    def test_stamped_persist_skips_writeback(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)
        _mock_pool(monkeypatch, GOLDEN_EXTRACT, GOLDEN_MATCH)
        _patch_bg_db(monkeypatch, db)
        process_oc_match_job(job.id)
        db.refresh(job)
        pedido = db.get(PedidoCompra, job.pedido_id)
        assert pedido is not None
        assert job.doc_refs_aplicado_at is not None
        stamped = job.doc_refs_aplicado_at
        pedido.facturas_documento = "KEEP-FA"
        pedido.pedidos_documento = "KEEP-PED"
        job.status = OcMatchJob.STATUS_ERROR
        job.error_message = "retry"
        db.flush()
        queue_retry(db, job)
        assert job.doc_refs_aplicado_at == stamped
        _mock_pool(monkeypatch, GOLDEN_EXTRACT, GOLDEN_MATCH)
        process_oc_match_job(job.id)
        db.refresh(job)
        db.refresh(pedido)
        assert pedido.facturas_documento == "KEEP-FA"
        assert pedido.pedidos_documento == "KEEP-PED"
        assert job.doc_refs_aplicado_at == stamped
        assert job.renglones

    def test_refresh_append_does_not_wipe(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)
        _mock_pool(monkeypatch, GOLDEN_EXTRACT, GOLDEN_MATCH)
        _patch_bg_db(monkeypatch, db)
        process_oc_match_job(job.id)
        db.refresh(job)
        pedido = db.get(PedidoCompra, job.pedido_id)
        assert pedido is not None
        pedido.facturas_documento = "KEEP-FA"
        pedido.pedidos_documento = "KEEP-PED"
        job.status = OcMatchJob.STATUS_ERROR
        job.error_message = "retry"
        db.flush()
        queue_retry(db, job, refrescar_doc_refs=True)
        assert job.doc_refs_aplicado_at is None
        _mock_pool(monkeypatch, GOLDEN_EXTRACT, GOLDEN_MATCH)
        process_oc_match_job(job.id)
        db.refresh(job)
        db.refresh(pedido)
        assert pedido.facturas_documento == "KEEP-FA; 0001-99"
        assert pedido.pedidos_documento == "KEEP-PED; PED-184465"
        assert job.doc_refs_aplicado_at is not None

    def test_skip_tipo_does_not_stamp(
        self,
        db: Session,
        active_user: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        extract = {**GOLDEN_EXTRACT, "tipo_documento": "comprobante_pago"}
        _seed_maestro(db)
        job, _adj = _pedido_adjunto_job(db, active_user, tmp_path)
        _mock_pool(monkeypatch, extract, GOLDEN_MATCH)
        _patch_bg_db(monkeypatch, db)
        process_oc_match_job(job.id)
        db.refresh(job)
        pedido = db.get(PedidoCompra, job.pedido_id)
        assert pedido is not None
        assert pedido.facturas_documento is None
        assert pedido.pedidos_documento is None
        assert job.doc_refs_aplicado_at is None
        assert job.status == OcMatchJob.STATUS_DONE


class TestWorkerNoMailAndSkipFab:
    def test_worker_source_has_no_mail_and_skips_fab(self) -> None:
        worker_src = (_SERVICES / "worker.py").read_text(encoding="utf-8")
        match_src = (_SERVICES / "match.py").read_text(encoding="utf-8")
        assert "smtp" not in worker_src.lower()
        assert "notificacion" not in worker_src.lower()
        assert "match_fabricante_exacto" not in worker_src
        assert "editar_pedido" not in worker_src
        assert "match_fabricante_exacto(" not in match_src
        assert "from app.models.producto" not in (_SERVICES / "maestro.py").read_text(encoding="utf-8")

"""Integration tests for OC-match Phase 2 trigger: hook, list, retry, permisos."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import BackgroundTasks

from app.core.config import settings
from app.models.empresa import Empresa
from app.models.oc_match_job import OcMatchJob
from app.models.orden_pago import OrdenPago
from app.models.proveedor import Proveedor
from app.services import ncs_locales_service, pedidos_service
from app.services.oc_match.enqueue import process_oc_match_job

BASE = "/api/administracion/compras"
PDF_HEADER = b"%PDF-1.4\n" + b"0" * 200
XLSX_HEADER = b"PK\x03\x04" + b"\x00" * 32


@pytest.fixture(autouse=True)
def _uploads_tmpdir(tmp_path: Path, monkeypatch):
    tmp = tmp_path / "compras"
    tmp.mkdir()
    monkeypatch.setattr(settings, "COMPRAS_UPLOADS_DIR", str(tmp))
    monkeypatch.setattr(settings, "COMPRAS_OC_MATCH_ENABLED", True)
    yield tmp


@pytest.fixture
def con_todos_los_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.tiene_algun_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


@pytest.fixture
def sin_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=False),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


@pytest.fixture
def solo_ver():
    def _tiene(*args, **kwargs) -> bool:
        codigo = kwargs.get("permiso_codigo", kwargs.get("codigo", args[-1] if args else ""))
        return codigo == "administracion.ver_ordenes_compra"

    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", side_effect=_tiene),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


@pytest.fixture
def add_task_espia():
    queued: list[tuple] = []

    def _spy(self, func, *args, **kwargs) -> None:
        queued.append((func, args, kwargs))

    with patch.object(BackgroundTasks, "add_task", _spy):
        yield queued


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(nombre="EmpresaOcMatch", activo=True, orden=1)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(nombre="ProvOcMatch", activo=True, origen="manual")
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido_borrador(db, empresa, proveedor, active_user):
    return pedidos_service.crear_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000"),
        creado_por_id=active_user.id,
    )


def _jobs(client, auth_headers, **params):
    return client.get(f"{BASE}/oc-match/jobs", headers=auth_headers, params=params)


class TestCreateAndForeignAdjuntosDoNotEnqueue:
    def test_crear_pedido_no_crea_job(self, client, auth_headers, empresa, proveedor, con_todos_los_permisos):
        r = client.post(
            f"{BASE}/pedidos",
            headers=auth_headers,
            json={
                "empresa_id": empresa.id,
                "proveedor_id": proveedor.id,
                "moneda": "ARS",
                "monto": "1500.00",
                "requiere_envio": False,
            },
        )
        assert r.status_code == 201, r.text
        listed = _jobs(client, auth_headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 0

    def test_op_adjunto_no_crea_job(
        self,
        client,
        auth_headers,
        db,
        empresa,
        proveedor,
        active_user,
        con_todos_los_permisos,
        add_task_espia,
    ):
        op = OrdenPago(
            numero="OP-OCMATCH-1",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto_total=Decimal("1000"),
            modo_imputacion="a_cuenta",
            estado="pendiente",
            creado_por_id=active_user.id,
        )
        db.add(op)
        db.flush()
        r = client.post(
            f"{BASE}/ordenes-pago/{op.id}/adjuntos",
            headers=auth_headers,
            files={"file": ("op.pdf", PDF_HEADER, "application/pdf")},
        )
        assert r.status_code == 201, r.text
        assert _jobs(client, auth_headers).json()["total"] == 0
        assert add_task_espia == []

    def test_nc_adjunto_no_crea_job(
        self,
        client,
        auth_headers,
        db,
        empresa,
        proveedor,
        active_user,
        con_todos_los_permisos,
        add_task_espia,
    ):
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("500"),
            fecha_emision=date.today(),
            motivo="OC-match NC no enqueue",
            creado_por_id=active_user.id,
        )
        db.commit()
        r = client.post(
            f"{BASE}/ncs-locales/{nc.id}/adjuntos",
            headers=auth_headers,
            files={"file": ("nc.pdf", PDF_HEADER, "application/pdf")},
        )
        assert r.status_code == 201, r.text
        assert _jobs(client, auth_headers).json()["total"] == 0
        assert add_task_espia == []


class TestPedidoAdjuntoEnqueue:
    def test_pdf_queues_and_schedules_stub(
        self,
        client,
        auth_headers,
        pedido_borrador,
        con_todos_los_permisos,
        add_task_espia,
    ):
        with patch("app.services.notificacion_service.crear_notificaciones_para_permisos") as mail:
            r = client.post(
                f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
                headers=auth_headers,
                files={"file": ("factura.pdf", PDF_HEADER, "application/pdf")},
            )
            assert r.status_code == 201, r.text
            mail.assert_not_called()
        listed = _jobs(client, auth_headers)
        assert listed.status_code == 200
        payload = listed.json()
        assert payload["total"] == 1
        job = payload["items"][0]
        assert job["pedido_id"] == pedido_borrador.id
        assert job["attachment_id"] == r.json()["id"]
        assert job["status"] == "queued"
        assert job["retryable"] is False
        assert add_task_espia == [(process_oc_match_job, (job["id"],), {})]

    def test_xlsx_skips_without_gemini_task(
        self,
        client,
        auth_headers,
        pedido_borrador,
        con_todos_los_permisos,
        add_task_espia,
    ):
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            headers=auth_headers,
            files={
                "file": (
                    "carga.xlsx",
                    XLSX_HEADER,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert r.status_code == 201, r.text
        payload = _jobs(client, auth_headers, status="skipped").json()
        assert payload["total"] == 1
        assert payload["items"][0]["status"] == "skipped"
        assert add_task_espia == []

    def test_new_adjunto_is_a_new_job(
        self, client, auth_headers, pedido_borrador, con_todos_los_permisos, add_task_espia
    ):
        first = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            headers=auth_headers,
            files={"file": ("a.pdf", PDF_HEADER, "application/pdf")},
        )
        second = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            headers=auth_headers,
            files={"file": ("b.pdf", PDF_HEADER, "application/pdf")},
        )
        assert first.status_code == 201
        assert second.status_code == 201
        payload = _jobs(client, auth_headers).json()
        ids = {item["attachment_id"] for item in payload["items"]}
        assert payload["total"] == 2
        assert ids == {first.json()["id"], second.json()["id"]}
        assert len(add_task_espia) == 2


class TestListRetryPermisos:
    def test_list_without_ver_403(self, client, auth_headers, sin_permisos):
        r = _jobs(client, auth_headers)
        assert r.status_code == 403

    def test_retry_view_only_403(self, client, auth_headers, db, pedido_borrador, solo_ver):
        from app.models.compra_adjunto import CompraAdjunto

        adj = CompraAdjunto(
            entidad_tipo=CompraAdjunto.ENTIDAD_TIPO_PEDIDO,
            entidad_id=pedido_borrador.id,
            nombre_archivo="stale.pdf",
            path_archivo="pedido_compra/x/stale.pdf",
        )
        db.add(adj)
        db.flush()
        job = OcMatchJob(
            pedido_id=pedido_borrador.id,
            attachment_id=adj.id,
            status=OcMatchJob.STATUS_ERROR,
            error_message="boom",
        )
        db.add(job)
        db.flush()
        r = client.post(f"{BASE}/oc-match/jobs/{job.id}/retry", headers=auth_headers)
        assert r.status_code == 403, r.text

    def test_stale_running_list_is_retryable_error(
        self, client, auth_headers, db, pedido_borrador, con_todos_los_permisos
    ):
        from app.models.compra_adjunto import CompraAdjunto

        adj = CompraAdjunto(
            entidad_tipo=CompraAdjunto.ENTIDAD_TIPO_PEDIDO,
            entidad_id=pedido_borrador.id,
            nombre_archivo="stale.pdf",
            path_archivo="pedido_compra/x/stale.pdf",
        )
        db.add(adj)
        db.flush()
        job = OcMatchJob(
            pedido_id=pedido_borrador.id,
            attachment_id=adj.id,
            status=OcMatchJob.STATUS_RUNNING,
            started_at=datetime.now(UTC) - timedelta(minutes=20),
        )
        db.add(job)
        db.flush()
        listed = _jobs(client, auth_headers)
        assert listed.status_code == 200
        item = listed.json()["items"][0]
        assert item["id"] == job.id
        assert item["status"] == "error"
        assert item["retryable"] is True
        detail = client.get(f"{BASE}/oc-match/jobs/{job.id}", headers=auth_headers)
        assert detail.status_code == 200
        assert detail.json()["status"] == "error"
        assert detail.json()["retryable"] is True

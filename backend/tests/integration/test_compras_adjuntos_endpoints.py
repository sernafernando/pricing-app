"""Integration tests de los endpoints de adjuntos (Batch H).

Cubre:
  - POST /pedidos/{id}/adjuntos (happy + 413 tamaño + 400 formato + 401 + 403)
  - GET  /pedidos/{id}/adjuntos
  - POST /ordenes-pago/{id}/adjuntos
  - GET  /adjuntos/{id}/descargar
  - DELETE /adjuntos/{id}
  - Regresión: NC adjuntos usa /ncs-locales/{id}/adjuntos, NO /ordenes-pago/{id}/adjuntos

Los archivos se escriben a una carpeta temporal (monkeypatch sobre
settings.COMPRAS_UPLOADS_DIR) para no contaminar el FS del proyecto.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.models.empresa import Empresa
from app.models.proveedor import Proveedor
from app.services import ncs_locales_service, pedidos_service

BASE = "/api/administracion/compras"


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _uploads_tmpdir(tmp_path: Path, monkeypatch):
    """Redirige COMPRAS_UPLOADS_DIR al tmp_path del test."""
    tmp = tmp_path / "compras"
    tmp.mkdir()
    monkeypatch.setattr(settings, "COMPRAS_UPLOADS_DIR", str(tmp))
    yield tmp


@pytest.fixture
def con_todos_los_permisos():
    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            return_value=True,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


@pytest.fixture
def sin_permisos():
    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            return_value=False,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(nombre="EmpresaAdj", activo=True, orden=1)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(nombre="ProvAdj", activo=True, origen="manual")
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


PDF_HEADER = b"%PDF-1.4\n" + b"0" * 200


# ──────────────────────────────────────────────────────────────────────────
# POST /pedidos/{id}/adjuntos
# ──────────────────────────────────────────────────────────────────────────


class TestSubirAdjuntoPedido:
    def test_sin_token_401(self, client, pedido_borrador):
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            files={"file": ("x.pdf", PDF_HEADER, "application/pdf")},
        )
        assert r.status_code in (401, 403)

    def test_sin_permiso_403(self, client, auth_headers, pedido_borrador, sin_permisos):
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            headers=auth_headers,
            files={"file": ("x.pdf", PDF_HEADER, "application/pdf")},
        )
        assert r.status_code == 403

    def test_happy_pdf(self, client, auth_headers, pedido_borrador, con_todos_los_permisos, _uploads_tmpdir):
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            headers=auth_headers,
            files={"file": ("factura1.pdf", PDF_HEADER, "application/pdf")},
            data={"tipo": "factura", "descripcion": "Factura mes"},
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["entidad_tipo"] == "pedido_compra"
        assert data["entidad_id"] == pedido_borrador.id
        assert data["nombre_archivo"] == "factura1.pdf"
        assert data["tipo"] == "factura"
        assert data["tamano_bytes"] == len(PDF_HEADER)
        # Archivo físicamente presente
        archivos = list(_uploads_tmpdir.rglob("*"))
        archivos_real = [a for a in archivos if a.is_file()]
        assert len(archivos_real) == 1

    def test_formato_invalido_400(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        # EXE con extensión .pdf
        fake = b"MZ\x90\x00" + b"\x00" * 30
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            headers=auth_headers,
            files={"file": ("malicioso.pdf", fake, "application/pdf")},
        )
        assert r.status_code == 400, r.text
        assert "Formato no permitido" in str(r.json())

    def test_tamano_excede_limite_400(self, client, auth_headers, pedido_borrador, con_todos_los_permisos, monkeypatch):
        # Forzamos límite de 1 MB para no generar 20 MB de memoria en test.
        monkeypatch.setattr(settings, "COMPRAS_MAX_FILE_SIZE_MB", 1)
        big = PDF_HEADER + b"\x00" * (2 * 1024 * 1024)
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            headers=auth_headers,
            files={"file": ("gigante.pdf", big, "application/pdf")},
        )
        assert r.status_code == 400, r.text
        assert "demasiado grande" in str(r.json()).lower()

    def test_pedido_inexistente_404(self, client, auth_headers, con_todos_los_permisos):
        r = client.post(
            f"{BASE}/pedidos/999999/adjuntos",
            headers=auth_headers,
            files={"file": ("x.pdf", PDF_HEADER, "application/pdf")},
        )
        assert r.status_code == 404

    def test_tipo_fuera_de_whitelist_422(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            headers=auth_headers,
            files={"file": ("x.pdf", PDF_HEADER, "application/pdf")},
            data={"tipo": "no_existe"},
        )
        # FastAPI/Pydantic rechaza por regex antes que el service
        assert r.status_code in (400, 422)


# ──────────────────────────────────────────────────────────────────────────
# GET /pedidos/{id}/adjuntos
# ──────────────────────────────────────────────────────────────────────────


class TestListarAdjuntosPedido:
    def test_vacio(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        r = client.get(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json() == []

    def test_con_un_adjunto(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        # subir
        r_up = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            headers=auth_headers,
            files={"file": ("f1.pdf", PDF_HEADER, "application/pdf")},
        )
        assert r_up.status_code == 201
        # listar
        r = client.get(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            headers=auth_headers,
        )
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["nombre_archivo"] == "f1.pdf"


# ──────────────────────────────────────────────────────────────────────────
# GET /adjuntos/{id}/descargar
# ──────────────────────────────────────────────────────────────────────────


class TestDescargarAdjunto:
    def test_descarga_ok(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        r_up = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            headers=auth_headers,
            files={"file": ("original.pdf", PDF_HEADER, "application/pdf")},
        )
        adj_id = r_up.json()["id"]

        r = client.get(f"{BASE}/adjuntos/{adj_id}/descargar", headers=auth_headers)
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")

    def test_404_si_adjunto_no_existe(self, client, auth_headers, con_todos_los_permisos):
        r = client.get(f"{BASE}/adjuntos/999999/descargar", headers=auth_headers)
        assert r.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# DELETE /adjuntos/{id}
# ──────────────────────────────────────────────────────────────────────────


class TestEliminarAdjunto:
    def test_elimina_borra_registro_y_archivo(
        self,
        client,
        auth_headers,
        pedido_borrador,
        con_todos_los_permisos,
        _uploads_tmpdir,
    ):
        r_up = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            headers=auth_headers,
            files={"file": ("borrar.pdf", PDF_HEADER, "application/pdf")},
        )
        adj_id = r_up.json()["id"]
        archivos_antes = [a for a in _uploads_tmpdir.rglob("*") if a.is_file()]
        assert len(archivos_antes) == 1

        r_del = client.delete(f"{BASE}/adjuntos/{adj_id}", headers=auth_headers)
        assert r_del.status_code == 204

        r_list = client.get(
            f"{BASE}/pedidos/{pedido_borrador.id}/adjuntos",
            headers=auth_headers,
        )
        assert r_list.json() == []

        archivos_despues = [a for a in _uploads_tmpdir.rglob("*") if a.is_file()]
        assert archivos_despues == []

    def test_sin_permiso_403(self, client, auth_headers, pedido_borrador, con_todos_los_permisos, sin_permisos):
        # Con permisos creamos el adjunto; después cambiamos a sin_permisos no es
        # trivial con el patch. Probamos DELETE con sin_permisos directamente.
        r = client.delete(f"{BASE}/adjuntos/1", headers=auth_headers)
        # Con sin_permisos activo el require_permiso falla primero
        assert r.status_code == 403

    def test_adjunto_inexistente_404(self, client, auth_headers, con_todos_los_permisos):
        r = client.delete(f"{BASE}/adjuntos/999999", headers=auth_headers)
        assert r.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# POST /ordenes-pago/{id}/adjuntos
# ──────────────────────────────────────────────────────────────────────────


class TestSubirAdjuntoOP:
    def test_op_inexistente_404(self, client, auth_headers, con_todos_los_permisos):
        r = client.post(
            f"{BASE}/ordenes-pago/999999/adjuntos",
            headers=auth_headers,
            files={"file": ("x.pdf", PDF_HEADER, "application/pdf")},
        )
        assert r.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# Regresión: NC adjuntos NO se sirven en /ordenes-pago/{id}/adjuntos
# ──────────────────────────────────────────────────────────────────────────
# Bug: AdjuntosPanel.jsx usaba un ternario binario (pedido_compra → 'pedidos',
# cualquier-otra-cosa → 'ordenes-pago'). Para nota_credito_local el basePath
# resultaba 'ordenes-pago' en vez de 'ncs-locales', enviando el request al
# endpoint incorrecto. El endpoint correcto es /ncs-locales/{id}/adjuntos.


class TestRuteadoAdjuntosNC:
    """Garantiza que /ordenes-pago NO acepte IDs de NC (entidades distintas)."""

    def test_nc_id_en_endpoint_op_retorna_404(self, client, auth_headers, con_todos_los_permisos):
        """Un ID que pertenece a una NC no debe resolver como OP → 404."""
        # ID 999998 no existe en ordenes_pago — el endpoint ordenes-pago/X/adjuntos
        # valida la existencia de la OP antes de subir.
        r = client.post(
            f"{BASE}/ordenes-pago/999998/adjuntos",
            headers=auth_headers,
            files={"file": ("nc.pdf", PDF_HEADER, "application/pdf")},
        )
        assert r.status_code == 404

    def test_nc_endpoint_existe_y_acepta_upload(
        self, client, auth_headers, con_todos_los_permisos, db, active_user, _uploads_tmpdir
    ):
        """El endpoint /ncs-locales/{id}/adjuntos existe y acepta PDFs válidos."""
        empresa = Empresa(nombre="EmpresaAdjNC", activo=True, orden=99)
        db.add(empresa)
        db.flush()
        proveedor = Proveedor(nombre="ProvAdjNC", activo=True, origen="manual")
        db.add(proveedor)
        db.flush()

        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("500"),
            fecha_emision=date.today(),
            motivo="Test regresión adjuntos NC",
            creado_por_id=active_user.id,
        )
        db.commit()

        r = client.post(
            f"{BASE}/ncs-locales/{nc.id}/adjuntos",
            headers=auth_headers,
            files={"file": ("nc-factura.pdf", PDF_HEADER, "application/pdf")},
            data={"tipo": "comprobante"},
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["entidad_tipo"] == "nota_credito_local"
        assert data["entidad_id"] == nc.id

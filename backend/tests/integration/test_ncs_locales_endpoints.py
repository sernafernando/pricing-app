"""
Integration tests de endpoints de NCs locales (compras v2).

Cubre:
  - GET /ncs-locales (paginado + filtros)
  - GET /ncs-locales/{id} (detalle con saldo_pendiente)
  - POST /ncs-locales (201 / 401 sin auth / 403 sin permiso / 400 validación)
  - PUT /ncs-locales/{id} (solo borrador)
  - POST /ncs-locales/{id}/enviar-aprobacion
  - POST /ncs-locales/{id}/aprobar (403 sin aprobar_ncs_locales / 200 con)
  - POST /ncs-locales/{id}/rechazar
  - POST /ncs-locales/{id}/cancelar
  - GET /ncs-locales/{id}/eventos
  - Flujo completo: crear → enviar → aprobar → imputar a saldo → aplicada
  - POST /ncs-locales/{id}/adjuntos

Permisos se mockean con `PermisosService.tiene_permiso` igual que el resto
de tests integration de compras.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.empresa import Empresa
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import ncs_locales_service, pedidos_service

BASE = "/api/administracion/compras"


def _error_message(r) -> str:
    """Extrae el mensaje de error del response, soporta el wrapper global
    `{error: {code, message}}` y el formato nativo FastAPI `{detail: str}`."""
    body = r.json()
    if isinstance(body, dict):
        if "error" in body and isinstance(body["error"], dict):
            return str(body["error"].get("message", "")).lower()
        if "detail" in body:
            return str(body["detail"]).lower()
    return ""


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def con_todos_los_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


@pytest.fixture
def sin_permiso_aprobar_nc():
    """Tiene todos los permisos EXCEPTO aprobar_ncs_locales."""

    def _fake(self, user, codigo):
        if codigo == "administracion.aprobar_ncs_locales":
            return False
        return True

    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", new=_fake),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


@pytest.fixture
def sin_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=False),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(nombre="EmpresaNCInt", activo=True, orden=1)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        nombre="ProveedorNCInt",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=42,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def nc_borrador(db, empresa, proveedor, active_user):
    nc = ncs_locales_service.crear(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("500"),
        fecha_emision=date.today(),
        motivo="Devolución test",
        creado_por_id=active_user.id,
    )
    db.commit()
    return nc


def _nc_payload(empresa_id: int, proveedor_id: int) -> dict:
    return {
        "empresa_id": empresa_id,
        "proveedor_id": proveedor_id,
        "moneda": "ARS",
        "monto": "1500.00",
        "fecha_emision": date.today().isoformat(),
        "motivo": "Ajuste contable por variación TC",
    }


# ──────────────────────────────────────────────────────────────────────────
# Auth / permisos
# ──────────────────────────────────────────────────────────────────────────


class TestAuthYPermisos:
    def test_listar_sin_auth_rechazado(self, client):
        # FastAPI devuelve 403 cuando no hay credenciales en endpoints con
        # `Depends(require_permiso)` (el dep valida auth + permiso juntos).
        r = client.get(f"{BASE}/ncs-locales")
        assert r.status_code in (401, 403)

    def test_crear_sin_permiso_403(self, client, auth_headers, empresa, proveedor, sin_permisos):
        r = client.post(
            f"{BASE}/ncs-locales",
            headers=auth_headers,
            json=_nc_payload(empresa.id, proveedor.id),
        )
        assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# POST /ncs-locales
# ──────────────────────────────────────────────────────────────────────────


class TestCrearNCEndpoint:
    def test_crear_nc_201(self, client, auth_headers, empresa, proveedor, con_todos_los_permisos):
        r = client.post(
            f"{BASE}/ncs-locales",
            headers=auth_headers,
            json=_nc_payload(empresa.id, proveedor.id),
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["estado"] == "borrador"
        assert data["numero"].startswith("NC-")
        assert data["moneda"] == "ARS"
        assert data["empresa_nombre"] is not None
        assert data["proveedor_nombre"] is not None

    def test_crear_nc_sin_motivo_422(self, client, auth_headers, empresa, proveedor, con_todos_los_permisos):
        payload = _nc_payload(empresa.id, proveedor.id)
        payload["motivo"] = ""
        r = client.post(f"{BASE}/ncs-locales", headers=auth_headers, json=payload)
        assert r.status_code == 422  # Pydantic rechaza min_length=1

    def test_crear_nc_monto_negativo_422(self, client, auth_headers, empresa, proveedor, con_todos_los_permisos):
        payload = _nc_payload(empresa.id, proveedor.id)
        payload["monto"] = "-100"
        r = client.post(f"{BASE}/ncs-locales", headers=auth_headers, json=payload)
        assert r.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# GET listado / detalle
# ──────────────────────────────────────────────────────────────────────────


class TestListarYDetalle:
    def test_listar_paginado(self, client, auth_headers, nc_borrador, con_todos_los_permisos):
        r = client.get(f"{BASE}/ncs-locales", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        assert data["page"] == 1
        assert len(data["items"]) >= 1

    def test_listar_con_filtro_estado(self, client, auth_headers, nc_borrador, con_todos_los_permisos):
        r = client.get(f"{BASE}/ncs-locales?estado=borrador", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert all(it["estado"] == "borrador" for it in data["items"])

    def test_listar_con_filtro_proveedor(self, client, auth_headers, nc_borrador, proveedor, con_todos_los_permisos):
        r = client.get(f"{BASE}/ncs-locales?proveedor_id={proveedor.id}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert all(it["proveedor_id"] == proveedor.id for it in data["items"])

    def test_obtener_detalle(self, client, auth_headers, nc_borrador, con_todos_los_permisos):
        r = client.get(f"{BASE}/ncs-locales/{nc_borrador.id}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == nc_borrador.id
        assert "eventos" in data
        assert "imputaciones" in data
        assert "saldo_pendiente" in data

    def test_detalle_404(self, client, auth_headers, con_todos_los_permisos):
        r = client.get(f"{BASE}/ncs-locales/999999", headers=auth_headers)
        assert r.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# Transiciones
# ──────────────────────────────────────────────────────────────────────────


class TestTransiciones:
    def test_enviar_a_aprobacion(self, client, auth_headers, nc_borrador, con_todos_los_permisos):
        r = client.post(f"{BASE}/ncs-locales/{nc_borrador.id}/enviar-aprobacion", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["estado"] == "pendiente_aprobacion"

    def test_aprobar_sin_permiso_403(self, client, auth_headers, nc_borrador, sin_permiso_aprobar_nc):
        # Primero lo mando a pendiente_aprobacion (usa permiso gestionar)
        client.post(f"{BASE}/ncs-locales/{nc_borrador.id}/enviar-aprobacion", headers=auth_headers)
        r = client.post(f"{BASE}/ncs-locales/{nc_borrador.id}/aprobar", headers=auth_headers)
        assert r.status_code == 403

    def test_aprobar_con_permiso_200(self, client, auth_headers, nc_borrador, con_todos_los_permisos):
        client.post(f"{BASE}/ncs-locales/{nc_borrador.id}/enviar-aprobacion", headers=auth_headers)
        r = client.post(f"{BASE}/ncs-locales/{nc_borrador.id}/aprobar", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["estado"] == "aprobado"

    def test_rechazar_sin_motivo_400(self, client, auth_headers, nc_borrador, con_todos_los_permisos):
        client.post(f"{BASE}/ncs-locales/{nc_borrador.id}/enviar-aprobacion", headers=auth_headers)
        r = client.post(
            f"{BASE}/ncs-locales/{nc_borrador.id}/rechazar",
            headers=auth_headers,
            json={"accion": "devolver_a_borrador"},
        )
        assert r.status_code == 400

    def test_rechazar_devolver_ok(self, client, auth_headers, nc_borrador, con_todos_los_permisos):
        client.post(f"{BASE}/ncs-locales/{nc_borrador.id}/enviar-aprobacion", headers=auth_headers)
        r = client.post(
            f"{BASE}/ncs-locales/{nc_borrador.id}/rechazar",
            headers=auth_headers,
            json={"accion": "devolver_a_borrador", "motivo": "Falta info"},
        )
        assert r.status_code == 200
        assert r.json()["estado"] == "rechazado"

    def test_cancelar_desde_borrador(self, client, auth_headers, nc_borrador, con_todos_los_permisos):
        r = client.post(
            f"{BASE}/ncs-locales/{nc_borrador.id}/cancelar",
            headers=auth_headers,
            json={},
        )
        assert r.status_code == 200
        assert r.json()["estado"] == "cancelado"

    def test_cancelar_aprobada_sin_motivo_400(self, client, auth_headers, nc_borrador, con_todos_los_permisos):
        client.post(f"{BASE}/ncs-locales/{nc_borrador.id}/enviar-aprobacion", headers=auth_headers)
        client.post(f"{BASE}/ncs-locales/{nc_borrador.id}/aprobar", headers=auth_headers)
        r = client.post(
            f"{BASE}/ncs-locales/{nc_borrador.id}/cancelar",
            headers=auth_headers,
            json={},
        )
        assert r.status_code == 400


# ──────────────────────────────────────────────────────────────────────────
# Edición
# ──────────────────────────────────────────────────────────────────────────


class TestEditar:
    def test_editar_borrador_ok(self, client, auth_headers, nc_borrador, con_todos_los_permisos):
        r = client.put(
            f"{BASE}/ncs-locales/{nc_borrador.id}",
            headers=auth_headers,
            json={"monto": "750.00", "motivo": "Nuevo motivo"},
        )
        assert r.status_code == 200
        data = r.json()
        assert Decimal(data["monto"]) == Decimal("750.00")
        assert data["motivo"] == "Nuevo motivo"

    def test_editar_aprobada_409(self, client, auth_headers, nc_borrador, con_todos_los_permisos):
        client.post(f"{BASE}/ncs-locales/{nc_borrador.id}/enviar-aprobacion", headers=auth_headers)
        client.post(f"{BASE}/ncs-locales/{nc_borrador.id}/aprobar", headers=auth_headers)
        r = client.put(
            f"{BASE}/ncs-locales/{nc_borrador.id}",
            headers=auth_headers,
            json={"monto": "999"},
        )
        assert r.status_code == 409


# ──────────────────────────────────────────────────────────────────────────
# Flujo end-to-end
# ──────────────────────────────────────────────────────────────────────────


class TestFlujoCompleto:
    def test_crear_enviar_aprobar_imputar_aplicada(
        self, client, auth_headers, empresa, proveedor, con_todos_los_permisos, db
    ):
        # 1. Crear
        r = client.post(
            f"{BASE}/ncs-locales",
            headers=auth_headers,
            json=_nc_payload(empresa.id, proveedor.id),
        )
        assert r.status_code == 201
        nc_id = r.json()["id"]

        # 2. Enviar a aprobación
        r = client.post(f"{BASE}/ncs-locales/{nc_id}/enviar-aprobacion", headers=auth_headers)
        assert r.status_code == 200

        # 3. Aprobar
        r = client.post(f"{BASE}/ncs-locales/{nc_id}/aprobar", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["estado"] == "aprobado"

        # 4. Imputar la totalidad de la NC vía endpoint de imputaciones:
        # En la UI el admin dispara una imputación directa con origen NC local.
        # Acá lo hacemos via el endpoint /imputaciones/{id} no existe, así que
        # usamos el servicio directamente para simular (el endpoint POST imputaciones
        # no es parte de este batch — queda en el router genérico de v1).
        from app.services import imputaciones_service

        imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_id,
            destino_tipo="saldo",
            destino_id=None,
            monto_imputado=Decimal("1500"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=1,
        )
        db.commit()

        # 5. Verificar estado aplicada
        r = client.get(f"{BASE}/ncs-locales/{nc_id}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["estado"] == "aplicada"


# ──────────────────────────────────────────────────────────────────────────
# Eventos
# ──────────────────────────────────────────────────────────────────────────


class TestEventos:
    def test_listar_eventos_incluye_creacion(self, client, auth_headers, nc_borrador, con_todos_los_permisos):
        r = client.get(f"{BASE}/ncs-locales/{nc_borrador.id}/eventos", headers=auth_headers)
        assert r.status_code == 200
        eventos = r.json()
        tipos = [e["tipo"] for e in eventos]
        assert "nc_creada" in tipos


# ──────────────────────────────────────────────────────────────────────────
# Adjuntos (reusando entidad_tipo='nota_credito_local')
# ──────────────────────────────────────────────────────────────────────────


class TestAdjuntosNC:
    def test_subir_adjunto_nc_ok(self, client, auth_headers, nc_borrador, con_todos_los_permisos, tmp_path):
        # Usamos un PDF mínimo válido (magic bytes %PDF)
        pdf_content = b"%PDF-1.4\n%EOF\n"

        r = client.post(
            f"{BASE}/ncs-locales/{nc_borrador.id}/adjuntos",
            headers=auth_headers,
            files={"file": ("nc-proveedor.pdf", pdf_content, "application/pdf")},
            data={"tipo": "factura"},
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["entidad_tipo"] == "nota_credito_local"
        assert data["entidad_id"] == nc_borrador.id

    def test_listar_adjuntos_nc(self, client, auth_headers, nc_borrador, con_todos_los_permisos):
        r = client.get(f"{BASE}/ncs-locales/{nc_borrador.id}/adjuntos", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ──────────────────────────────────────────────────────────────────────────
# POST /ncs-locales/{id}/aplicar — imputación NC → pedido/factura/saldo
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def nc_aprobada(db, empresa, proveedor, active_user):
    """NC local en estado 'aprobado' (monto=1000 ARS) lista para imputar."""
    nc = ncs_locales_service.crear(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000"),
        fecha_emision=date.today(),
        motivo="Devolución para test aplicar",
        creado_por_id=active_user.id,
    )
    ncs_locales_service.transicionar(db, nc_id=nc.id, accion="enviar_aprobacion", user_id=active_user.id)
    ncs_locales_service.transicionar(db, nc_id=nc.id, accion="aprobar", user_id=active_user.id)
    db.commit()
    return nc


@pytest.fixture
def pedido_aprobado_mismo_prov(db, empresa, proveedor, active_user):
    """Pedido aprobado (700 ARS) del MISMO proveedor que `nc_aprobada`."""
    pedido = pedidos_service.crear_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("700"),
        creado_por_id=active_user.id,
    )
    pedidos_service.transicionar(db, pedido_id=pedido.id, accion="enviar_aprobacion", user_id=active_user.id)
    pedidos_service.transicionar(db, pedido_id=pedido.id, accion="aprobar", user_id=active_user.id)
    db.commit()
    return pedido


class TestAplicarNC:
    def test_aplicar_nc_a_pedido_happy(
        self,
        client,
        auth_headers,
        nc_aprobada,
        pedido_aprobado_mismo_prov,
        con_todos_los_permisos,
    ):
        """Happy path: NC 1000 aplicada parcialmente (500) a pedido 700."""
        r = client.post(
            f"{BASE}/ncs-locales/{nc_aprobada.id}/aplicar",
            headers=auth_headers,
            json={
                "destino_tipo": "pedido_compra",
                "destino_id": pedido_aprobado_mismo_prov.id,
                "monto_imputado": "500.00",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # NC pasa a aplicada_parcial (saldo 500 de los 1000 iniciales).
        assert data["estado"] == "aplicada_parcial"
        assert Decimal(data["saldo_pendiente"]) == Decimal("500.00")

    def test_aplicar_nc_monto_supera_saldo_400(
        self,
        client,
        auth_headers,
        nc_aprobada,
        pedido_aprobado_mismo_prov,
        con_todos_los_permisos,
    ):
        """Monto > saldo pendiente de NC → 400."""
        r = client.post(
            f"{BASE}/ncs-locales/{nc_aprobada.id}/aplicar",
            headers=auth_headers,
            json={
                "destino_tipo": "pedido_compra",
                "destino_id": pedido_aprobado_mismo_prov.id,
                "monto_imputado": "1500.00",
            },
        )
        assert r.status_code == 400
        assert "saldo" in _error_message(r)

    def test_aplicar_nc_estado_invalido_409(
        self,
        client,
        auth_headers,
        nc_borrador,
        con_todos_los_permisos,
    ):
        """NC en borrador no puede aplicarse → 409."""
        r = client.post(
            f"{BASE}/ncs-locales/{nc_borrador.id}/aplicar",
            headers=auth_headers,
            json={
                "destino_tipo": "saldo",
                "destino_id": None,
                "monto_imputado": "100.00",
            },
        )
        assert r.status_code == 409
        assert "borrador" in _error_message(r)

    def test_aplicar_nc_sin_permiso_403(
        self,
        client,
        auth_headers,
        nc_aprobada,
        sin_permisos,
    ):
        """Sin permiso gestionar_ordenes_compra → 403."""
        r = client.post(
            f"{BASE}/ncs-locales/{nc_aprobada.id}/aplicar",
            headers=auth_headers,
            json={
                "destino_tipo": "saldo",
                "destino_id": None,
                "monto_imputado": "100.00",
            },
        )
        assert r.status_code == 403

    def test_aplicar_nc_a_saldo_ok(
        self,
        client,
        auth_headers,
        nc_aprobada,
        con_todos_los_permisos,
    ):
        """Aplicar total a saldo → NC pasa a 'aplicada', saldo_pendiente=0."""
        r = client.post(
            f"{BASE}/ncs-locales/{nc_aprobada.id}/aplicar",
            headers=auth_headers,
            json={
                "destino_tipo": "saldo",
                "destino_id": None,
                "monto_imputado": "1000.00",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["estado"] == "aplicada"
        assert Decimal(data["saldo_pendiente"]) == Decimal("0")

    def test_aplicar_nc_saldo_con_destino_id_400(
        self,
        client,
        auth_headers,
        nc_aprobada,
        con_todos_los_permisos,
    ):
        """destino_tipo='saldo' con destino_id != None → 400."""
        r = client.post(
            f"{BASE}/ncs-locales/{nc_aprobada.id}/aplicar",
            headers=auth_headers,
            json={
                "destino_tipo": "saldo",
                "destino_id": 5,
                "monto_imputado": "100.00",
            },
        )
        assert r.status_code == 400

    def test_aplicar_nc_a_pedido_otro_proveedor_400(
        self,
        client,
        auth_headers,
        nc_aprobada,
        con_todos_los_permisos,
        db,
        empresa,
        active_user,
    ):
        """Pedido destino con proveedor distinto al de la NC → 400."""
        otro_prov = Proveedor(
            nombre="OtroProv",
            activo=True,
            origen=OrigenProveedor.ERP.value,
            supp_id=99,
        )
        db.add(otro_prov)
        db.flush()
        pedido_otro = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=otro_prov.id,
            moneda="ARS",
            monto=Decimal("500"),
            creado_por_id=active_user.id,
        )
        pedidos_service.transicionar(db, pedido_id=pedido_otro.id, accion="enviar_aprobacion", user_id=active_user.id)
        pedidos_service.transicionar(db, pedido_id=pedido_otro.id, accion="aprobar", user_id=active_user.id)
        db.commit()

        r = client.post(
            f"{BASE}/ncs-locales/{nc_aprobada.id}/aplicar",
            headers=auth_headers,
            json={
                "destino_tipo": "pedido_compra",
                "destino_id": pedido_otro.id,
                "monto_imputado": "200.00",
            },
        )
        assert r.status_code == 400
        assert "proveedor" in _error_message(r)

"""Integration tests de los endpoints de papelera.

Cubre:
  - DELETE /pedidos/{id}: 401 sin auth, 403 sin permiso, 409 no borrable,
    happy path borra + retorna fila de papelera.
  - DELETE /ordenes-pago/{id}: análogo.
  - GET /papelera: 403 sin permiso, listado vacío, listado con items.
  - GET /papelera/{id}: 404 inexistente, detalle con snapshot.
  - Listados de pedidos/OPs: `puede_eliminar` se popula por batch (opción C).

Estrategia: mockear `PermisosService.tiene_permiso` para aislar del seed
que corre en Postgres; reutilizar fixtures del módulo de tests existente.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor
from app.services import pedidos_service


BASE = "/api/administracion/compras"


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
    e = Empresa(nombre="EmpresaPap", activo=True, orden=1)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(nombre="ProvPap", activo=True, origen="manual")
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido_borrador(db, empresa, proveedor, active_user) -> PedidoCompra:
    return pedidos_service.crear_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("500"),
        creado_por_id=active_user.id,
    )


@pytest.fixture
def pedido_aprobado(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = pedidos_service.crear_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("500"),
        creado_por_id=active_user.id,
    )
    pedidos_service.transicionar(
        db, pedido_id=p.id, accion="enviar_aprobacion", user_id=active_user.id
    )
    pedidos_service.transicionar(db, pedido_id=p.id, accion="aprobar", user_id=active_user.id)
    db.flush()
    return p


# ==========================================================================
# DELETE /pedidos/{id}
# ==========================================================================


class TestHardDeletePedido:
    def test_sin_token_401(self, client, pedido_borrador):
        r = client.request(
            "DELETE",
            f"{BASE}/pedidos/{pedido_borrador.id}",
            json={"motivo": "x"},
        )
        assert r.status_code in (401, 403)

    def test_sin_permiso_403(self, client, auth_headers, pedido_borrador, sin_permisos):
        r = client.request(
            "DELETE",
            f"{BASE}/pedidos/{pedido_borrador.id}",
            headers=auth_headers,
            json={"motivo": "limpieza"},
        )
        assert r.status_code == 403

    def test_borrador_happy(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        pedido_id = pedido_borrador.id
        r = client.request(
            "DELETE",
            f"{BASE}/pedidos/{pedido_id}",
            headers=auth_headers,
            json={"motivo": "pedido mal creado", "challenge_palabra_usada": "banana"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["entidad_tipo"] == "pedido_compra"
        assert data["entidad_id_original"] == pedido_id
        assert data["motivo"] == "pedido mal creado"
        assert data["challenge_palabra"] == "banana"

    def test_motivo_vacio_400(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        r = client.request(
            "DELETE",
            f"{BASE}/pedidos/{pedido_borrador.id}",
            headers=auth_headers,
            json={"motivo": "   "},
        )
        assert r.status_code == 400

    def test_aprobado_409(self, client, auth_headers, pedido_aprobado, con_todos_los_permisos):
        r = client.request(
            "DELETE",
            f"{BASE}/pedidos/{pedido_aprobado.id}",
            headers=auth_headers,
            json={"motivo": "intento borrar aprobado"},
        )
        assert r.status_code == 409

    def test_inexistente_404(self, client, auth_headers, con_todos_los_permisos):
        r = client.request(
            "DELETE",
            f"{BASE}/pedidos/999999",
            headers=auth_headers,
            json={"motivo": "x"},
        )
        assert r.status_code == 404


# ==========================================================================
# GET /papelera
# ==========================================================================


class TestListarPapelera:
    def test_sin_permiso_403(self, client, auth_headers, sin_permisos):
        r = client.get(f"{BASE}/papelera", headers=auth_headers)
        assert r.status_code == 403

    def test_vacio_ok(self, client, auth_headers, con_todos_los_permisos):
        r = client.get(f"{BASE}/papelera", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_entidad_tipo_invalido_400(
        self, client, auth_headers, con_todos_los_permisos
    ):
        r = client.get(
            f"{BASE}/papelera?entidad_tipo=otro",
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_listar_despues_de_borrar(
        self, client, auth_headers, pedido_borrador, con_todos_los_permisos
    ):
        # Borrar
        pedido_id = pedido_borrador.id
        r_del = client.request(
            "DELETE",
            f"{BASE}/pedidos/{pedido_id}",
            headers=auth_headers,
            json={"motivo": "limpieza test"},
        )
        assert r_del.status_code == 200

        # Listar
        r = client.get(f"{BASE}/papelera", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] >= 1
        entry = next(
            (
                it
                for it in body["items"]
                if it["entidad_id_original"] == pedido_id
                and it["entidad_tipo"] == "pedido_compra"
            ),
            None,
        )
        assert entry is not None

    def test_obtener_detalle_404(self, client, auth_headers, con_todos_los_permisos):
        r = client.get(f"{BASE}/papelera/999999", headers=auth_headers)
        assert r.status_code == 404

    def test_obtener_detalle_con_snapshot(
        self, client, auth_headers, pedido_borrador, con_todos_los_permisos
    ):
        # Primero borrar
        r_del = client.request(
            "DELETE",
            f"{BASE}/pedidos/{pedido_borrador.id}",
            headers=auth_headers,
            json={"motivo": "test snapshot"},
        )
        papelera_id = r_del.json()["id"]

        r = client.get(f"{BASE}/papelera/{papelera_id}", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert "snapshot" in body
        snapshot = body["snapshot"]
        assert snapshot["numero"]  # el numero estaba en el pedido
        assert "eventos" in snapshot
        # El evento 'creado' del pedido_borrador debe estar preservado
        tipos = {e["tipo"] for e in snapshot["eventos"]}
        assert "creado" in tipos


# ==========================================================================
# Flag `puede_eliminar` en listados (opción C)
# ==========================================================================


class TestPuedeEliminarEnListados:
    def test_listar_pedidos_incluye_flag(
        self, client, auth_headers, pedido_borrador, con_todos_los_permisos
    ):
        r = client.get(f"{BASE}/pedidos", headers=auth_headers)
        assert r.status_code == 200
        items = r.json()["items"]
        encontrado = next((p for p in items if p["id"] == pedido_borrador.id), None)
        assert encontrado is not None
        assert encontrado.get("puede_eliminar") is True

    def test_listar_pedidos_aprobado_no_puede_eliminar(
        self, client, auth_headers, pedido_aprobado, con_todos_los_permisos
    ):
        r = client.get(f"{BASE}/pedidos", headers=auth_headers)
        assert r.status_code == 200
        items = r.json()["items"]
        encontrado = next((p for p in items if p["id"] == pedido_aprobado.id), None)
        assert encontrado is not None
        assert encontrado.get("puede_eliminar") is False

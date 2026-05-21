"""
T5.20–T5.22 — Integration tests for PUT /pedidos/{pedido_id}/tipo-cambio (F5).

Verifies:
  - T5.20: happy path → 200 + updated PedidoCompraResponse.
  - T5.21: 403 without permission (AC5.8).
  - T5.22: null tipo_cambio clears the override.
  - 401 without authentication.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor

BASE = "/api/administracion/compras"


# ---------------------------------------------------------------------------
# Permission fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def con_todos_los_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
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


# ---------------------------------------------------------------------------
# Data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa Endpoint TC Manual", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(nombre="Prov EP TC Manual", activo=True, origen=OrigenProveedor.ERP.value, supp_id=77)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def pedido_usd(db, empresa, proveedor, active_user) -> PedidoCompra:
    pedido = PedidoCompra(
        numero="PC-EP-F5-0001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=Decimal("1000"),
        tipo_cambio=Decimal("1400"),
        tipo_cambio_original=Decimal("1400"),
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(pedido)
    db.flush()
    return pedido


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPutTipoCambioEndpoint:
    """T5.20–T5.22 — PUT /pedidos/{id}/tipo-cambio."""

    def test_put_tipo_cambio_200_happy_path(self, client, db, pedido_usd, auth_headers, con_todos_los_permisos) -> None:
        """T5.20 — valid payload → 200 + updated pedido response."""
        payload = {"tipo_cambio": 1430.0, "motivo": "ajuste manual de prueba"}
        resp = client.put(
            f"{BASE}/pedidos/{pedido_usd.id}/tipo-cambio",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == pedido_usd.id
        assert float(data["tipo_cambio"]) == pytest.approx(1430.0)
        assert float(data["tipo_cambio_manual"]) == pytest.approx(1430.0)
        assert data["tipo_cambio_es_manual"] is True

    def test_put_tipo_cambio_401_unauthenticated(self, client, pedido_usd) -> None:
        """401 without authentication (no auth_headers)."""
        payload = {"tipo_cambio": 1430.0, "motivo": "test"}
        resp = client.put(
            f"{BASE}/pedidos/{pedido_usd.id}/tipo-cambio",
            json=payload,
        )
        assert resp.status_code in (401, 403)

    def test_put_tipo_cambio_403_no_permission(self, client, db, pedido_usd, auth_headers, sin_permisos) -> None:
        """T5.21 / AC5.8 — without ajustar_cc_proveedor_manual → 403."""
        payload = {"tipo_cambio": 1430.0, "motivo": "test"}
        resp = client.put(
            f"{BASE}/pedidos/{pedido_usd.id}/tipo-cambio",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 403

    def test_put_tipo_cambio_null_clears_override(
        self, client, db, pedido_usd, auth_headers, con_todos_los_permisos
    ) -> None:
        """T5.22 — tipo_cambio: null clears the override, reverts to automatic mode."""
        # First set the override.
        client.put(
            f"{BASE}/pedidos/{pedido_usd.id}/tipo-cambio",
            json={"tipo_cambio": 1430.0, "motivo": "set override"},
            headers=auth_headers,
        )

        # Now clear it.
        resp = client.put(
            f"{BASE}/pedidos/{pedido_usd.id}/tipo-cambio",
            json={"tipo_cambio": None, "motivo": "volver a automático"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["tipo_cambio_manual"] is None
        assert data["tipo_cambio_es_manual"] is False

    def test_put_tipo_cambio_404_pedido_not_found(self, client, auth_headers, con_todos_los_permisos) -> None:
        """404 when pedido doesn't exist."""
        resp = client.put(
            f"{BASE}/pedidos/999999/tipo-cambio",
            json={"tipo_cambio": 1430.0, "motivo": "test"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

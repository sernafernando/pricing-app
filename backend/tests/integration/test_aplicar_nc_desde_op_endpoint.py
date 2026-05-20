"""
T4.10–T4.11 — Integration tests for POST /ordenes-pago/{op_id}/aplicar-nc (F4).

Verifies:
  - T4.10: happy path → HTTP 201, response has imputacion_id and nc_estado.
  - T4.11: 403 without the required permission.
  - 401 without authentication.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.nota_credito_local import NotaCreditoLocal
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor

BASE = "/api/administracion/compras"


# ---------------------------------------------------------------------------
# Permission fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def con_permisos():
    """Force PermisosService.tiene_permiso → True."""
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


@pytest.fixture
def sin_permisos():
    """Force PermisosService.tiene_permiso → False."""
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
    e = Empresa(nombre="Empresa AplicarNC EP", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        nombre="Prov AplicarNC EP",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=9901,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        numero="PC-NCEp-2026-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("20000"),
        tipo_cambio=None,
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def op(db, empresa, proveedor, active_user) -> OrdenPago:
    """OP pagada asociada al proveedor."""
    o = OrdenPago(
        numero="OP-NCEp-2026-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=Decimal("15000"),
        modo_imputacion="especifica",
        estado="pagado",
        actualizar_tc_pedido=False,
        creado_por_id=active_user.id,
    )
    db.add(o)
    db.flush()
    return o


@pytest.fixture
def imputacion_op_pedido(db, op, pedido, proveedor, active_user) -> Imputacion:
    """Imputación existente OP→pedido."""
    imp = Imputacion(
        origen_tipo="orden_pago",
        origen_id=op.id,
        destino_tipo="pedido_compra",
        destino_id=pedido.id,
        monto_imputado=Decimal("15000"),
        moneda_imputada="ARS",
        proveedor_id=proveedor.id,
        es_reversal=False,
        creado_por_id=active_user.id,
    )
    db.add(imp)
    db.flush()
    return imp


@pytest.fixture
def nc_aprobada(db, empresa, proveedor, active_user) -> NotaCreditoLocal:
    """NC local aprobada del mismo proveedor, ARS 10 000."""
    nc = NotaCreditoLocal(
        numero="NC-NCEp-2026-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("10000"),
        fecha_emision=date(2026, 1, 10),
        motivo="Ajuste para test endpoint F4",
        estado="aprobado",
        tipo="credito",
        creado_por_id=active_user.id,
    )
    db.add(nc)
    db.flush()
    return nc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAplicarNCDesdeOPEndpoint:
    """T4.10–T4.11: POST /ordenes-pago/{op_id}/aplicar-nc."""

    def test_sin_auth_401(self, client, op, nc_aprobada, imputacion_op_pedido) -> None:
        """401 / 403 when not authenticated."""
        r = client.post(
            f"{BASE}/ordenes-pago/{op.id}/aplicar-nc",
            json={"nc_id": nc_aprobada.id, "monto": "5000"},
        )
        assert r.status_code in (401, 403)

    def test_sin_permiso_403(self, client, auth_headers, op, nc_aprobada, imputacion_op_pedido, sin_permisos) -> None:
        """T4.11 — authenticated but no gestionar_ordenes_compra → 403."""
        r = client.post(
            f"{BASE}/ordenes-pago/{op.id}/aplicar-nc",
            headers=auth_headers,
            json={"nc_id": nc_aprobada.id, "monto": "5000"},
        )
        assert r.status_code == 403

    def test_happy_path_201(
        self, client, auth_headers, op, pedido, nc_aprobada, imputacion_op_pedido, con_permisos
    ) -> None:
        """T4.10 — valid request → 201, response has imputacion_id and nc_estado."""
        r = client.post(
            f"{BASE}/ordenes-pago/{op.id}/aplicar-nc",
            headers=auth_headers,
            json={"nc_id": nc_aprobada.id, "monto": "8000"},
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert "imputacion_id" in data
        assert "nc_estado" in data
        assert isinstance(data["imputacion_id"], int)
        assert data["nc_estado"] in {"aprobado", "aplicada_parcial", "aplicada"}

    def test_op_not_found_404(self, client, auth_headers, nc_aprobada, con_permisos) -> None:
        """OP inexistente → 404."""
        r = client.post(
            f"{BASE}/ordenes-pago/999999/aplicar-nc",
            headers=auth_headers,
            json={"nc_id": nc_aprobada.id, "monto": "1000"},
        )
        assert r.status_code == 404

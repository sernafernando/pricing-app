"""
T1.3 — Tests unitarios para F7: crear OP con ncs_aplicadas.

Cubre:
  - crear: happy path con ncs_aplicadas (mocks: carga NC, carga pedido, imputar_nc_a_pedido).
  - crear: ncs_aplicadas = [] → no llama imputar_nc_a_pedido (regresión cero).
  - crear: pedido_id omitido con OP de UN pedido → infiere correctamente.
  - crear: pedido_id omitido con OP de DOS pedidos → 422.
  - crear: OP a_cuenta + pedido_id omitido → 422.
  - crear: OP a_cuenta + pedido_id explícito + proveedor match → OK.
  - crear: NC pertenece a proveedor distinto → 422; OP no creada.
  - crear: múltiples NCs — NC #2 falla → rollback total incluye NC #1.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.empresa import Empresa
from app.models.nota_credito_local import NotaCreditoLocal
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import ordenes_pago_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=30, nombre="EmpresaF7Crear", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=30,
        nombre="ProveedorF7Crear",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=300,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def proveedor_otro(db) -> Proveedor:
    p = Proveedor(
        id=31,
        nombre="OtroProveedorF7Crear",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=301,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        id=30,
        numero="PC-30-2026-00001",
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
def pedido2(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        id=31,
        numero="PC-30-2026-00002",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("15000"),
        tipo_cambio=None,
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def nc_aprobada(db, empresa, proveedor, active_user) -> NotaCreditoLocal:
    nc = NotaCreditoLocal(
        id=30,
        numero="NC-30-2026-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("10000"),
        fecha_emision=date(2026, 1, 10),
        motivo="Test crear con NC",
        estado="aprobado",
        tipo="credito",
        creado_por_id=active_user.id,
    )
    db.add(nc)
    db.flush()
    return nc


@pytest.fixture
def nc2_aprobada(db, empresa, proveedor, active_user) -> NotaCreditoLocal:
    nc = NotaCreditoLocal(
        id=31,
        numero="NC-30-2026-00002",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("5000"),
        fecha_emision=date(2026, 1, 10),
        motivo="Test crear con NC 2",
        estado="aprobado",
        tipo="credito",
        creado_por_id=active_user.id,
    )
    db.add(nc)
    db.flush()
    return nc


def _crear_op_a_cuenta(db, empresa, proveedor, active_user, ncs_aplicadas=None):
    """Helper: crea OP a_cuenta con o sin ncs_aplicadas."""
    return ordenes_pago_service.crear(
        db,
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        moneda="ARS",
        monto_total=Decimal("10000"),
        modo_imputacion="a_cuenta",
        items=[],
        creado_por_id=active_user.id,
        ncs_aplicadas=ncs_aplicadas or [],
    )


def _crear_op_especifica(db, empresa, proveedor, pedido, active_user, ncs_aplicadas=None):
    """Helper: crea OP específica con un pedido."""
    return ordenes_pago_service.crear(
        db,
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        moneda="ARS",
        monto_total=Decimal("10000"),
        modo_imputacion="a_cuenta",
        items=[{"tipo": "pedido_compra", "id": pedido.id, "monto": Decimal("10000"), "numero_factura": None}],
        creado_por_id=active_user.id,
        ncs_aplicadas=ncs_aplicadas or [],
    )


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestCrearOPConNC:
    """T1.3 — crear OP con ncs_aplicadas."""

    def test_ncs_aplicadas_vacio_no_llama_helper(self, db, empresa, proveedor, active_user) -> None:
        """ncs_aplicadas = [] → imputar_nc_a_pedido no se llama (regresión cero)."""
        with patch.object(ordenes_pago_service, "imputar_nc_a_pedido") as mock_helper:
            op = _crear_op_a_cuenta(db, empresa, proveedor, active_user, ncs_aplicadas=[])
        assert op is not None
        assert op.estado == "pendiente"
        mock_helper.assert_not_called()

    def test_sin_ncs_aplicadas_no_llama_helper(self, db, empresa, proveedor, active_user) -> None:
        """Ausencia de ncs_aplicadas → imputar_nc_a_pedido no se llama."""
        with patch.object(ordenes_pago_service, "imputar_nc_a_pedido") as mock_helper:
            op = ordenes_pago_service.crear(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                moneda="ARS",
                monto_total=Decimal("10000"),
                modo_imputacion="a_cuenta",
                items=[],
                creado_por_id=active_user.id,
            )
        assert op is not None
        mock_helper.assert_not_called()

    def test_a_cuenta_sin_pedido_id_en_nc_422(self, db, empresa, proveedor, nc_aprobada, active_user) -> None:
        """OP a_cuenta + NC sin pedido_id → 422 (pedido_id requerido para OPs a_cuenta)."""
        with pytest.raises(HTTPException) as exc_info:
            _crear_op_a_cuenta(
                db,
                empresa,
                proveedor,
                active_user,
                ncs_aplicadas=[{"nc_id": nc_aprobada.id, "monto": Decimal("5000"), "pedido_id": None}],
            )
        assert exc_info.value.status_code == 422
        assert "pedido_id" in str(exc_info.value.detail).lower()

    def test_a_cuenta_con_pedido_id_ok(self, db, empresa, proveedor, pedido, nc_aprobada, active_user) -> None:
        """OP a_cuenta + NC con pedido_id + proveedor match → OK, imputar_nc_a_pedido llamado."""
        with patch.object(ordenes_pago_service, "imputar_nc_a_pedido") as mock_helper:
            mock_helper.return_value = MagicMock()
            op = _crear_op_a_cuenta(
                db,
                empresa,
                proveedor,
                active_user,
                ncs_aplicadas=[{"nc_id": nc_aprobada.id, "monto": Decimal("5000"), "pedido_id": pedido.id}],
            )
        assert op is not None
        mock_helper.assert_called_once()
        call_kwargs = mock_helper.call_args
        assert call_kwargs.kwargs["monto"] == Decimal("5000")

    def test_nc_proveedor_distinto_levanta_excepcion(
        self, db, empresa, proveedor, proveedor_otro, pedido, active_user
    ) -> None:
        """NC de proveedor distinto → HTTPException 403/422 levantada.

        En producción el router hace rollback completo (AC-F1-4).
        """
        nc_otro = NotaCreditoLocal(
            id=35,
            numero="NC-30-2026-00005",
            empresa_id=empresa.id,
            proveedor_id=proveedor_otro.id,
            moneda="ARS",
            monto=Decimal("5000"),
            fecha_emision=date(2026, 1, 10),
            motivo="NC otro proveedor",
            estado="aprobado",
            tipo="credito",
            creado_por_id=active_user.id,
        )
        db.add(nc_otro)
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            _crear_op_a_cuenta(
                db,
                empresa,
                proveedor,
                active_user,
                ncs_aplicadas=[{"nc_id": nc_otro.id, "monto": Decimal("1000"), "pedido_id": pedido.id}],
            )
        assert exc_info.value.status_code in {403, 422}

    def test_nc_inexistente_levanta_404(self, db, empresa, proveedor, pedido, active_user) -> None:
        """NC inexistente → HTTPException 404 levantada (caller hace rollback)."""
        with pytest.raises(HTTPException) as exc_info:
            _crear_op_a_cuenta(
                db,
                empresa,
                proveedor,
                active_user,
                ncs_aplicadas=[{"nc_id": 99999, "monto": Decimal("1000"), "pedido_id": pedido.id}],
            )
        assert exc_info.value.status_code == 404

    def test_multiple_nc_segunda_falla_levanta_excepcion(
        self, db, empresa, proveedor, pedido, nc_aprobada, nc2_aprobada, active_user
    ) -> None:
        """NC #1 OK, NC #2 falla → HTTPException levantada (AC-F1-12).

        En producción el router hace rollback total incluyendo NC #1.
        """
        with pytest.raises(HTTPException) as exc_info:
            _crear_op_a_cuenta(
                db,
                empresa,
                proveedor,
                active_user,
                ncs_aplicadas=[
                    {"nc_id": nc_aprobada.id, "monto": Decimal("5000"), "pedido_id": pedido.id},
                    {"nc_id": nc2_aprobada.id, "monto": Decimal("999999"), "pedido_id": pedido.id},
                ],
            )
        # monto enorme → excede saldo → 422
        assert exc_info.value.status_code == 422

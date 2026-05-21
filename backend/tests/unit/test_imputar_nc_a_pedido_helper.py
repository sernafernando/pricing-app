"""
T1.2 — Tests unitarios para el helper compartido `imputar_nc_a_pedido`.

Cubre:
  - Happy path: NC aprobada, pedido aprobado, misma moneda, monto ≤ saldo → retorna Imputacion.
  - Fails 403: nc.proveedor_id != pedido.proveedor_id.
  - Fails 409: nc.estado == 'aplicada'.
  - Fails 422: nc.estado == 'rechazada'.
  - Fails 422: nc.estado == 'pendiente'.
  - Fails 422: pedido.estado == 'cancelado'.
  - Fails 422: monto > nc.saldo_disponible.
  - Fails 422: cross-moneda NC→pedido (NC USD, pedido ARS).
  - NC state transitions: monto == saldo_disponible → nc.estado = 'aplicada'.
  - monto < saldo_disponible → nc.estado = 'aplicada_parcial'.
  - nc.monto_ya_aplicado incrementado correctamente.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.nota_credito_local import NotaCreditoLocal
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import ordenes_pago_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=20, nombre="EmpresaF7Helper", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=20,
        nombre="ProveedorF7",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=200,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def proveedor_otro(db) -> Proveedor:
    p = Proveedor(
        id=21,
        nombre="OtroProveedorF7",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=201,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido_ars(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        id=20,
        numero="PC-20-2026-00001",
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
def pedido_usd(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        id=21,
        numero="PC-20-2026-00002",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=Decimal("500"),
        tipo_cambio=Decimal("1400"),
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido_cancelado(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        id=22,
        numero="PC-20-2026-00003",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("5000"),
        tipo_cambio=None,
        estado="cancelado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


def _make_nc(
    db,
    *,
    id: int,
    proveedor_id: int,
    empresa_id: int,
    estado: str,
    monto: Decimal,
    moneda: str = "ARS",
    creado_por_id: int,
) -> NotaCreditoLocal:
    nc = NotaCreditoLocal(
        id=id,
        numero=f"NC-20-2026-{id:05d}",
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        moneda=moneda,
        monto=monto,
        fecha_emision=date(2026, 1, 10),
        motivo="Test helper",
        estado=estado,
        tipo="credito",
        creado_por_id=creado_por_id,
    )
    db.add(nc)
    db.flush()
    return nc


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestImputarNcAPedidoHelper:
    """T1.2 — Tests para imputar_nc_a_pedido helper."""

    def test_happy_path_retorna_imputacion(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """NC aprobada, pedido aprobado, misma moneda, monto <= saldo → retorna Imputacion."""
        nc = _make_nc(
            db,
            id=200,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("10000"),
            creado_por_id=active_user.id,
        )

        imp = ordenes_pago_service.imputar_nc_a_pedido(
            db,
            nc=nc,
            pedido=pedido_ars,
            monto=Decimal("5000"),
            creado_por_id=active_user.id,
        )

        assert isinstance(imp, Imputacion)
        assert imp.origen_tipo == "nota_credito_local"
        assert imp.origen_id == nc.id
        assert imp.destino_tipo == "pedido_compra"
        assert imp.destino_id == pedido_ars.id
        assert imp.monto_imputado == Decimal("5000")

    def test_fails_403_proveedor_mismatch(
        self, db, empresa, proveedor, proveedor_otro, pedido_ars, active_user
    ) -> None:
        """nc.proveedor_id != pedido.proveedor_id → 403."""
        nc = _make_nc(
            db,
            id=201,
            proveedor_id=proveedor_otro.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("10000"),
            creado_por_id=active_user.id,
        )
        # pedido_ars belongs to proveedor, nc belongs to proveedor_otro

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.imputar_nc_a_pedido(
                db,
                nc=nc,
                pedido=pedido_ars,
                monto=Decimal("1000"),
                creado_por_id=active_user.id,
            )
        assert exc_info.value.status_code == 403

    def test_fails_409_nc_aplicada(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """nc.estado == 'aplicada' → 409."""
        nc = _make_nc(
            db,
            id=202,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aplicada",
            monto=Decimal("5000"),
            creado_por_id=active_user.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.imputar_nc_a_pedido(
                db,
                nc=nc,
                pedido=pedido_ars,
                monto=Decimal("1000"),
                creado_por_id=active_user.id,
            )
        assert exc_info.value.status_code == 409

    def test_fails_422_nc_rechazada(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """nc.estado == 'rechazado' → 422."""
        nc = _make_nc(
            db,
            id=203,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="rechazado",
            monto=Decimal("5000"),
            creado_por_id=active_user.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.imputar_nc_a_pedido(
                db,
                nc=nc,
                pedido=pedido_ars,
                monto=Decimal("1000"),
                creado_por_id=active_user.id,
            )
        assert exc_info.value.status_code == 422

    def test_fails_422_nc_pendiente(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """nc.estado == 'pendiente_aprobacion' → 422."""
        nc = _make_nc(
            db,
            id=204,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="pendiente_aprobacion",
            monto=Decimal("5000"),
            creado_por_id=active_user.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.imputar_nc_a_pedido(
                db,
                nc=nc,
                pedido=pedido_ars,
                monto=Decimal("1000"),
                creado_por_id=active_user.id,
            )
        assert exc_info.value.status_code == 422

    def test_fails_422_pedido_cancelado(self, db, empresa, proveedor, pedido_cancelado, active_user) -> None:
        """pedido.estado == 'cancelado' → 422."""
        nc = _make_nc(
            db,
            id=205,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("5000"),
            creado_por_id=active_user.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.imputar_nc_a_pedido(
                db,
                nc=nc,
                pedido=pedido_cancelado,
                monto=Decimal("1000"),
                creado_por_id=active_user.id,
            )
        assert exc_info.value.status_code == 422

    def test_fails_422_monto_excede_saldo(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """monto > nc.saldo_disponible → 422."""
        nc = _make_nc(
            db,
            id=206,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("3000"),
            creado_por_id=active_user.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.imputar_nc_a_pedido(
                db,
                nc=nc,
                pedido=pedido_ars,
                monto=Decimal("9999"),
                creado_por_id=active_user.id,
            )
        assert exc_info.value.status_code == 422

    def test_fails_422_cross_moneda(self, db, empresa, proveedor, pedido_usd, active_user) -> None:
        """NC en ARS contra pedido en USD → 422 (cross-moneda bloqueado en v1)."""
        nc = _make_nc(
            db,
            id=207,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("10000"),
            moneda="ARS",
            creado_por_id=active_user.id,
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.imputar_nc_a_pedido(
                db,
                nc=nc,
                pedido=pedido_usd,
                monto=Decimal("1000"),
                creado_por_id=active_user.id,
            )
        assert exc_info.value.status_code == 422

    def test_nc_estado_cambia_a_aplicada_cuando_saldo_agotado(
        self, db, empresa, proveedor, pedido_ars, active_user
    ) -> None:
        """Monto == saldo_disponible → nc.estado debe ser 'aplicada' después."""
        nc = _make_nc(
            db,
            id=208,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("5000"),
            creado_por_id=active_user.id,
        )

        ordenes_pago_service.imputar_nc_a_pedido(
            db,
            nc=nc,
            pedido=pedido_ars,
            monto=Decimal("5000"),
            creado_por_id=active_user.id,
        )
        db.flush()
        db.refresh(nc)
        # The state is managed by ncs_locales_service via imputaciones_service
        # After imputación completa (monto = saldo), estado should be 'aplicada'
        assert nc.estado == "aplicada"

    def test_nc_estado_parcial_cuando_saldo_no_agotado(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """Monto < saldo_disponible → nc.estado es 'aplicada_parcial'."""
        nc = _make_nc(
            db,
            id=209,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("10000"),
            creado_por_id=active_user.id,
        )

        ordenes_pago_service.imputar_nc_a_pedido(
            db,
            nc=nc,
            pedido=pedido_ars,
            monto=Decimal("3000"),
            creado_por_id=active_user.id,
        )
        db.flush()
        db.refresh(nc)
        assert nc.estado == "aplicada_parcial"

    def test_saldo_disponible_reducido_tras_imputar(self, db, empresa, proveedor, pedido_ars, active_user) -> None:
        """El saldo disponible de la NC se reduce en el monto imputado."""
        from app.services import ncs_locales_service

        nc = _make_nc(
            db,
            id=210,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            estado="aprobado",
            monto=Decimal("10000"),
            creado_por_id=active_user.id,
        )
        saldo_antes = ncs_locales_service.calcular_saldo_pendiente(db, nc.id)

        ordenes_pago_service.imputar_nc_a_pedido(
            db,
            nc=nc,
            pedido=pedido_ars,
            monto=Decimal("4000"),
            creado_por_id=active_user.id,
        )
        db.flush()

        saldo_despues = ncs_locales_service.calcular_saldo_pendiente(db, nc.id)
        assert saldo_antes - saldo_despues == Decimal("4000")

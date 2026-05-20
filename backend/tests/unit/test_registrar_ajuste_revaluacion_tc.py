"""
T1.31–T1.33 — Tests for cc_proveedor_service.registrar_ajuste_revaluacion_tc.

Verifies that re-valuation emits an append-only CC ajuste movement with the
correct sign and does NOT modify existing rows.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tipo_cambio import TipoCambio
from app.services import cc_proveedor_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa AJT Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(id=1, nombre="Prov AJT", activo=True, origen=OrigenProveedor.ERP.value, supp_id=2)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def tipo_cambio_usd(db) -> None:
    tc = TipoCambio(fecha=date(2026, 1, 1), moneda="USD", compra=1400.0, venta=1410.0)
    db.add(tc)
    db.flush()


def _make_pedido_usd(db, empresa, proveedor, user_id: int, monto: Decimal = Decimal("1000")) -> PedidoCompra:
    pedido = PedidoCompra(
        numero="PC-AJT-001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=monto,
        tipo_cambio=Decimal("1400"),
        tipo_cambio_original=Decimal("1400"),
        estado="aprobado",
        creado_por_id=user_id,
    )
    db.add(pedido)
    db.flush()
    return pedido


# ──────────────────────────────────────────────────────────────────────────
# T1.31 — append-only: creates one new row
# ──────────────────────────────────────────────────────────────────────────


class TestRegistrarAjusteRevaluacionTc:
    def test_emits_append_only_ajuste_row(self, db, empresa, proveedor, tipo_cambio_usd, active_user) -> None:
        """T1.31 — calling the helper creates ONE new cc_mov row (tipo='ajuste')
        and does NOT modify existing rows."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid)

        # Seed one existing 'debe' row to verify it's untouched.
        existing_mov = cc_proveedor_service.insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 5, 1),
            tipo="debe",
            monto=Decimal("1400000"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=None,
        )
        existing_id = existing_mov.id
        existing_tipo = existing_mov.tipo

        count_before = db.query(CCProveedorMovimiento).count()

        cc_proveedor_service.registrar_ajuste_revaluacion_tc(
            db,
            pedido=pedido,
            tc_anterior=Decimal("1400"),
            tc_nuevo=Decimal("1450"),
            user_id=uid,
            motivo="test_caso_a",
        )

        count_after = db.query(CCProveedorMovimiento).count()
        assert count_after == count_before + 1, "Should create exactly one new row"

        # Existing row must be unchanged.
        existing_reloaded = db.get(CCProveedorMovimiento, existing_id)
        assert existing_reloaded.tipo == existing_tipo

        # New row must be tipo='ajuste'.
        new_mov = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.tipo == "ajuste").one_or_none()
        assert new_mov is not None
        assert new_mov.tipo == "ajuste"

    def test_signo_positivo_when_tc_rises(self, db, empresa, proveedor, tipo_cambio_usd, active_user) -> None:
        """T1.32 — TC rises: signo_ajuste=+1 (ARS debt increases)."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, monto=Decimal("1000"))

        cc_proveedor_service.registrar_ajuste_revaluacion_tc(
            db,
            pedido=pedido,
            tc_anterior=Decimal("1400"),
            tc_nuevo=Decimal("1450"),  # TC rose
            user_id=uid,
            motivo="tc_sube",
        )

        mov = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.tipo == "ajuste").one()
        assert mov.signo_ajuste == 1, "TC rise → ARS debt increases → signo_ajuste=+1"
        # Delta ARS = (1450 - 1400) * 1000 = 50000
        assert mov.monto == Decimal("50000")

    def test_signo_negativo_when_tc_falls(self, db, empresa, proveedor, tipo_cambio_usd, active_user) -> None:
        """T1.33 — TC falls: signo_ajuste=-1 (ARS debt decreases)."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, monto=Decimal("1000"))

        cc_proveedor_service.registrar_ajuste_revaluacion_tc(
            db,
            pedido=pedido,
            tc_anterior=Decimal("1450"),
            tc_nuevo=Decimal("1400"),  # TC fell
            user_id=uid,
            motivo="tc_baja",
        )

        mov = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.tipo == "ajuste").one()
        assert mov.signo_ajuste == -1, "TC fall → ARS debt decreases → signo_ajuste=-1"
        # Delta ARS = abs((1400 - 1450)) * 1000 = 50000 (monto is always positive)
        assert mov.monto == Decimal("50000")

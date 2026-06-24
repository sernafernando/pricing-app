"""
Regression test: Caso-A payment of a USD pedido must NOT create any
cc_proveedor_movimientos row with origen_tipo='revaluacion_tc'.

Background: TC re-valuation was a vestigial feature that posted a phantom ARS
adjustment to the supplier CC when the effective TC changed after a Caso-A
payment. This was incorrect — a pedido is not invoiced, so the final paid debt
(Caso-A weighted TC) is the source of truth. The phantom 'revaluacion_tc'
adjustment is no longer created.

Also asserts that after a full Caso-A payment the ARS balance via
calcular_saldo_por_moneda is 0 (USD debe/haber net to 0, no phantom ARS row).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.caja import Caja, CajaTipoDocumento
from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tipo_cambio import TipoCambio
from app.services import cc_proveedor_service, ordenes_pago_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures (mirrors test_ejecutar_pago_f1.py setup)
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa NoReval", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(nombre="Prov NoReval", activo=True, origen=OrigenProveedor.ERP.value, supp_id=199)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def caja_ars(db, empresa) -> Caja:
    caja = Caja(
        nombre="Caja ARS NoReval",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("10000000"),
        saldo_actual=Decimal("10000000"),
        activo=True,
    )
    db.add(caja)
    db.flush()
    return caja


@pytest.fixture
def tipos_doc_caja(db) -> None:
    existing = db.query(CajaTipoDocumento).filter_by(nombre="Orden de Pago").first()
    if not existing:
        td = CajaTipoDocumento(nombre="Orden de Pago", descripcion="OP", activo=True)
        db.add(td)
        db.flush()


@pytest.fixture
def tipo_cambio_usd(db) -> None:
    tc = TipoCambio(fecha=date(2026, 1, 1), moneda="USD", compra=Decimal("1480"), venta=Decimal("1490"))
    db.add(tc)
    db.flush()


# ──────────────────────────────────────────────────────────────────────────
# Regression test
# ──────────────────────────────────────────────────────────────────────────


class TestCasoANoRevaluacion:
    def test_full_caso_a_payment_does_not_create_revaluacion_tc_movement(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ) -> None:
        """
        Regression: full Caso-A payment of a USD 1000 pedido (TC orig 1480,
        paid at TC 1510) must NOT generate any cc_proveedor_movimientos row
        with origen_tipo='revaluacion_tc'.

        The phantom 30000 ARS debit (= (1510-1480) * 1000) must not appear.
        """
        uid = active_user.id

        # Create an approved USD pedido at TC 1480.
        pedido = PedidoCompra(
            numero="PC-NOREVAL-0001",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="USD",
            monto=Decimal("1000"),
            tipo_cambio=Decimal("1480"),
            tipo_cambio_original=Decimal("1480"),
            estado="aprobado",
            creado_por_id=uid,
        )
        db.add(pedido)
        db.flush()

        # Create and execute a full Caso-A ARS payment at TC 1510.
        # USD 1000 × 1510 = ARS 1510000.
        op = ordenes_pago_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto_total=Decimal("1510000"),
            tipo_cambio=Decimal("1510"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido.id, "monto": Decimal("1510000")}],
            creado_por_id=uid,
            actualizar_tc_pedido=True,  # Caso A
        )

        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date(2026, 6, 24),
            user_id=uid,
        )
        db.flush()

        # Assert: no revaluacion_tc movement must exist for this pedido.
        reval_rows = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.proveedor_id == proveedor.id,
                CCProveedorMovimiento.origen_tipo == "revaluacion_tc",
            )
            .all()
        )
        assert reval_rows == [], (
            f"Expected no revaluacion_tc rows, got {len(reval_rows)}: {[(r.monto, r.moneda) for r in reval_rows]}"
        )

    def test_full_caso_a_payment_ars_saldo_is_zero(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ) -> None:
        """
        After a full Caso-A payment, calcular_saldo_por_moneda must NOT include
        an ARS entry (no phantom ARS adjustment was posted). USD saldo nets to 0.
        """
        uid = active_user.id

        pedido = PedidoCompra(
            numero="PC-NOREVAL-0002",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="USD",
            monto=Decimal("1000"),
            tipo_cambio=Decimal("1480"),
            tipo_cambio_original=Decimal("1480"),
            estado="aprobado",
            creado_por_id=uid,
        )
        db.add(pedido)
        db.flush()

        op = ordenes_pago_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto_total=Decimal("1510000"),
            tipo_cambio=Decimal("1510"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido.id, "monto": Decimal("1510000")}],
            creado_por_id=uid,
            actualizar_tc_pedido=True,  # Caso A
        )

        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date(2026, 6, 24),
            user_id=uid,
        )
        db.flush()

        saldos = cc_proveedor_service.calcular_saldo_por_moneda(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
        )

        # ARS must not appear — no phantom revaluacion_tc row was posted.
        # (The only CC movement created by ejecutar_pago for a USD pedido is the
        # USD haber from the imputacion; no ARS adjustment is emitted.)
        assert "ARS" not in saldos, (
            f"Expected no ARS saldo entry, got ARS={saldos.get('ARS')}. "
            "A phantom revaluacion_tc row may have been created."
        )

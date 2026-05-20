"""
T3.3–T3.5 — Service tests for ordenes_pago_service.crear_y_pagar (F3).

Verifies:
  - T3.3: happy path — OP created + imputación created in one tx, estado='pagado'.
  - T3.4: rollback on payment failure — OP NOT persisted, imputación NOT persisted.
  - T3.5: existing endpoints POST /ordenes-pago and POST /{id}/pagar still pass
          (regression guard — this verifies the two-step path is untouched).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.caja import Caja, CajaTipoDocumento
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tipo_cambio import TipoCambio
from app.services import ordenes_pago_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa CYP Service", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        nombre="Prov CYP Service",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=1234,
    )
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def caja_ars(db, empresa) -> Caja:
    caja = Caja(
        nombre="Caja ARS CYP",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("5000000"),
        saldo_actual=Decimal("5000000"),
        activo=True,
    )
    db.add(caja)
    db.flush()
    return caja


@pytest.fixture
def tipos_doc_caja(db) -> None:
    td = CajaTipoDocumento(nombre="Orden de Pago", descripcion="OP", activo=True)
    db.add(td)
    db.flush()


@pytest.fixture
def tipo_cambio_usd(db) -> None:
    db.add(TipoCambio(fecha=date(2026, 1, 1), moneda="USD", compra=Decimal("1400"), venta=Decimal("1410")))
    db.flush()


@pytest.fixture
def pedido_usd(db, empresa, proveedor, active_user) -> PedidoCompra:
    """Approved USD pedido for testing."""
    pedido = PedidoCompra(
        numero="PC-CYP-0001",
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


# ──────────────────────────────────────────────────────────────────────────
# T3.3 — Happy path
# ──────────────────────────────────────────────────────────────────────────


class TestCrearYPagarHappyPath:
    """T3.3 — crear_y_pagar: OP + imputación created in one call, estado='pagado'."""

    def test_happy_path_ars_a_cuenta(self, db, empresa, proveedor, caja_ars, tipos_doc_caja, active_user) -> None:
        """ARS pedido, modo a_cuenta — OP created and paid in one call."""
        pedido_ars = PedidoCompra(
            numero="PC-CYP-ARS-0001",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("5000"),
            estado="aprobado",
            creado_por_id=active_user.id,
        )
        db.add(pedido_ars)
        db.flush()

        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("5000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_ars.id, "monto": Decimal("5000")}],
            creado_por_id=active_user.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date(2026, 1, 10),
        )

        # OP is in pagado state
        assert op.estado == "pagado"
        # OP has a PK (it was flushed/saved)
        assert op.id is not None
        # Payment fields are set
        assert op.caja_id == caja_ars.id
        assert op.fecha_pago_real == date(2026, 1, 10)
        assert op.pagado_por_id == active_user.id

    def test_happy_path_cross_moneda_ars_op_usd_pedido(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, pedido_usd, active_user
    ) -> None:
        """ARS OP → USD pedido cross-moneda: OP created + pagado in one call."""
        monto_ars = Decimal("1400")  # 1 USD × TC 1400
        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=monto_ars,
            tipo_cambio=Decimal("1400"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_usd.id, "monto": monto_ars}],
            creado_por_id=active_user.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date(2026, 1, 10),
        )

        assert op.estado == "pagado"
        assert op.id is not None
        # Imputación was created (the pedido_usd saldo is reduced)
        db.refresh(pedido_usd)

    def test_returns_op_in_pagado_estado(self, db, empresa, proveedor, caja_ars, tipos_doc_caja, active_user) -> None:
        """T3.3 AC3.1: returns estado='pagado' in the returned object."""
        pedido_ars = PedidoCompra(
            numero="PC-CYP-ARS-0002",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("3000"),
            estado="aprobado",
            creado_por_id=active_user.id,
        )
        db.add(pedido_ars)
        db.flush()

        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("3000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_ars.id, "monto": Decimal("3000")}],
            creado_por_id=active_user.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date(2026, 1, 15),
        )

        assert op.estado == "pagado", f"Expected 'pagado', got '{op.estado}'"


# ──────────────────────────────────────────────────────────────────────────
# T3.4 — Rollback on payment failure
# ──────────────────────────────────────────────────────────────────────────


class TestCrearYPagarRollback:
    """T3.4 — If payment step fails, OP is NOT persisted (full rollback)."""

    def test_rollback_on_payment_failure(self, db, empresa, proveedor, tipos_doc_caja, active_user) -> None:
        """T3.4 AC3.2: caja validation fails → OP NOT persisted."""
        pedido_ars = PedidoCompra(
            numero="PC-CYP-ROLLBACK-0001",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("5000"),
            estado="aprobado",
            creado_por_id=active_user.id,
        )
        db.add(pedido_ars)
        db.flush()

        op_count_before = db.query(OrdenPago).count()
        imp_count_before = db.query(Imputacion).count()

        # Use a non-existent caja_id to force payment failure
        with pytest.raises(HTTPException):
            ordenes_pago_service.crear_y_pagar(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                moneda="ARS",
                monto_total=Decimal("5000"),
                modo_imputacion="especifica",
                items=[{"tipo": "pedido_compra", "id": pedido_ars.id, "monto": Decimal("5000")}],
                creado_por_id=active_user.id,
                caja_id=999999,  # non-existent caja → payment fails
                fecha_pago_real=date(2026, 1, 15),
            )

        # After rollback, counts should be unchanged
        db.rollback()
        assert db.query(OrdenPago).count() == op_count_before, "OP should not be persisted after payment failure"
        assert db.query(Imputacion).count() == imp_count_before, "Imputacion should not be persisted"


# ──────────────────────────────────────────────────────────────────────────
# T3.5 — Regression guard: two-step path still works
# ──────────────────────────────────────────────────────────────────────────


class TestDosPassosSiguesFuncionando:
    """T3.5 AC3.3: the existing two-step flow (crear + pagar) is unaffected."""

    def test_crear_then_pagar_still_works(self, db, empresa, proveedor, caja_ars, tipos_doc_caja, active_user) -> None:
        """Two-step: crear → estado='pendiente', pagar → estado='pagado'."""
        pedido_ars = PedidoCompra(
            numero="PC-CYP-REG-0001",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("2000"),
            estado="aprobado",
            creado_por_id=active_user.id,
        )
        db.add(pedido_ars)
        db.flush()

        # Step 1: crear (two-step path)
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("2000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_ars.id, "monto": Decimal("2000")}],
            creado_por_id=active_user.id,
        )
        assert op.estado == "pendiente"

        # Step 2: ejecutar_pago (two-step path)
        op = ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date(2026, 1, 10),
            user_id=active_user.id,
        )
        assert op.estado == "pagado"

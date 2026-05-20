"""
T2.11–T2.15 — Tests for pedidos_service.calcular_varianza_tc (F2).

Verifies the derived ARS variance computation per spec §3.3 and AC2:
  - T2.11: AC2.7 — no Caso-B payments → varianza_tc_neta=0.
  - T2.12: AC2.1 — TC rose, Caso-B USD 999 → varianza +49 950 ARS.
  - T2.13: AC2.3 — TC fell, Caso-B USD 999 → varianza -49 950 ARS.
  - T2.14: Scenario 2.B — partial Caso-A + Caso-B, only Caso-B portion variances.
  - T2.15: AC2.2/2.4 — variance cleared by NC/ND imputacion covering the full amount.

Uses the same direct-ORM approach as test_ejecutar_pago_f1.py for speed.
calcular_varianza_tc is a pure reader — tests only assert its output.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.caja import Caja, CajaTipoDocumento
from app.models.empresa import Empresa
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tipo_cambio import TipoCambio
from app.services import (
    cc_proveedor_service,
    imputaciones_service,
    ncs_locales_service,
    ordenes_pago_service,
    pedidos_service,
)


# ---------------------------------------------------------------------------
# Fixtures — mirror test_ejecutar_pago_f1.py pattern
# ---------------------------------------------------------------------------


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa Varianza Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(nombre="Prov Varianza Test", activo=True, origen=OrigenProveedor.ERP.value, supp_id=888)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def caja_ars(db, empresa) -> Caja:
    caja = Caja(
        nombre="Caja ARS Varianza",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("50000000"),
        saldo_actual=Decimal("50000000"),
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
    db.add(TipoCambio(fecha=date(2026, 1, 2), moneda="USD", compra=Decimal("1450"), venta=Decimal("1460")))
    db.flush()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pedido_usd(db, empresa, proveedor, active_user, monto: Decimal, tc_orig: Decimal) -> PedidoCompra:
    """Create an approved USD pedido with set tipo_cambio_original."""
    n = db.query(PedidoCompra).count() + 1
    pedido = PedidoCompra(
        numero=f"PC-VAR-{n:04d}",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=monto,
        tipo_cambio=tc_orig,
        tipo_cambio_original=tc_orig,
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(pedido)
    db.flush()
    return pedido


def _op_ars(
    db,
    empresa,
    proveedor,
    caja,
    user_id: int,
    tc: Decimal,
    monto_ars: Decimal,
    pedido: PedidoCompra,
    actualizar_tc: bool,
) -> OrdenPago:
    """Create a pendiente ARS OP targeting the pedido."""
    op = ordenes_pago_service.crear(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=monto_ars,
        tipo_cambio=tc,
        modo_imputacion="especifica",
        items=[{"tipo": "pedido_compra", "id": pedido.id, "monto": monto_ars}],
        creado_por_id=user_id,
        actualizar_tc_pedido=actualizar_tc,
    )
    return op


def _pagar(db, op, caja, user_id: int) -> None:
    """Execute payment for the given OP."""
    ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op.id,
        caja_id=caja.id,
        fecha_pago_real=date(2026, 1, 2),
        user_id=user_id,
    )
    db.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCalcularVarianzaTC:
    """T2.11–T2.15: calcular_varianza_tc spec compliance."""

    def test_varianza_tc_caso_a_full_no_varianza(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ):
        """T2.11 — AC2.7: no Caso-B payments → varianza_tc_neta=0."""
        uid = active_user.id
        pedido = _pedido_usd(db, empresa, proveedor, active_user, Decimal("1000"), Decimal("1400"))
        op = _op_ars(db, empresa, proveedor, caja_ars, uid, Decimal("1450"), Decimal("1450000"), pedido, True)
        _pagar(db, op, caja_ars, uid)
        db.refresh(pedido)

        varianza = pedidos_service.calcular_varianza_tc(db, pedido)

        assert varianza == Decimal("0"), f"Expected 0, got {varianza}"

    def test_varianza_tc_positive_tc_rose(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ):
        """T2.12 — AC2.1: TC_orig=1400, TC_ef=1450 (Caso A), Caso-B USD 999 → +49950 ARS."""
        uid = active_user.id
        pedido = _pedido_usd(db, empresa, proveedor, active_user, Decimal("1000"), Decimal("1400"))
        # Caso A: USD 1 at TC 1450 → TC_ef moves to 1450.
        op_a = _op_ars(db, empresa, proveedor, caja_ars, uid, Decimal("1450"), Decimal("1450"), pedido, True)
        _pagar(db, op_a, caja_ars, uid)
        # Caso B: remaining USD 999 at TC 1450 (ARS 1449*1450 but monto_ars = 999*1450 = 1448550).
        op_b = _op_ars(db, empresa, proveedor, caja_ars, uid, Decimal("1450"), Decimal("1448550"), pedido, False)
        _pagar(db, op_b, caja_ars, uid)
        db.refresh(pedido)

        varianza = pedidos_service.calcular_varianza_tc(db, pedido)

        # Variance = (TC_ef - TC_orig) * monto_caso_b_usd = (1450-1400) * 999 = 49950
        assert varianza == Decimal("49950"), f"Expected 49950, got {varianza}"

    def test_varianza_tc_negative_tc_fell(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ):
        """T2.13 — AC2.3: TC_orig=1450, TC_ef=1400 (Caso A), Caso-B USD 999 → -49950 ARS."""
        uid = active_user.id
        pedido = _pedido_usd(db, empresa, proveedor, active_user, Decimal("1000"), Decimal("1450"))
        # Caso A: USD 1 at TC 1400 → TC_ef = 1400.
        op_a = _op_ars(db, empresa, proveedor, caja_ars, uid, Decimal("1400"), Decimal("1400"), pedido, True)
        _pagar(db, op_a, caja_ars, uid)
        # Caso B: 999 USD at TC 1400 = 1398600 ARS.
        op_b = _op_ars(db, empresa, proveedor, caja_ars, uid, Decimal("1400"), Decimal("1398600"), pedido, False)
        _pagar(db, op_b, caja_ars, uid)
        db.refresh(pedido)

        varianza = pedidos_service.calcular_varianza_tc(db, pedido)

        # Variance = (1400-1450) * 999 = -49950
        assert varianza == Decimal("-49950"), f"Expected -49950, got {varianza}"

    def test_varianza_tc_partial_caso_b(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ):
        """T2.14 — Scenario 2.B: partial Caso-A + Caso-B, only Caso-B portion counts."""
        uid = active_user.id
        pedido = _pedido_usd(db, empresa, proveedor, active_user, Decimal("1000"), Decimal("1450"))
        # Caso A: USD 1 at TC 1400 → TC_ef = 1400.
        op_a = _op_ars(db, empresa, proveedor, caja_ars, uid, Decimal("1400"), Decimal("1400"), pedido, True)
        _pagar(db, op_a, caja_ars, uid)
        # Caso B: USD 999 at TC 1400 = 1398600 ARS.
        op_b = _op_ars(db, empresa, proveedor, caja_ars, uid, Decimal("1400"), Decimal("1398600"), pedido, False)
        _pagar(db, op_b, caja_ars, uid)
        db.refresh(pedido)

        varianza = pedidos_service.calcular_varianza_tc(db, pedido)

        # TC_ef=1400, TC_orig=1450. Caso-B=999 USD. (1400-1450)*999 = -49950.
        assert varianza == Decimal("-49950"), f"Expected -49950, got {varianza}"

    def test_varianza_cleared_by_nd_nc_imputacion(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ):
        """T2.15 — AC2.2/2.4: after NC/ND covers full varianza, varianza_tc_neta=0."""
        uid = active_user.id
        pedido = _pedido_usd(db, empresa, proveedor, active_user, Decimal("1000"), Decimal("1400"))
        # TC rises to 1450 via Caso A (1 USD).
        op_a = _op_ars(db, empresa, proveedor, caja_ars, uid, Decimal("1450"), Decimal("1450"), pedido, True)
        _pagar(db, op_a, caja_ars, uid)
        # 999 USD Caso B → varianza = (1450-1400)*999 = 49950 ARS.
        op_b = _op_ars(db, empresa, proveedor, caja_ars, uid, Decimal("1450"), Decimal("1448550"), pedido, False)
        _pagar(db, op_b, caja_ars, uid)
        db.refresh(pedido)

        varianza_antes = pedidos_service.calcular_varianza_tc(db, pedido)
        assert varianza_antes == Decimal("49950"), f"Setup: expected 49950, got {varianza_antes}"

        # Create ND (tipo='debito') and impute exactly the varianza amount to this pedido.
        nd = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=varianza_antes,
            fecha_emision=date.today(),
            motivo="varianza TC resolver",
            creado_por_id=uid,
            tipo="debito",
        )
        ncs_locales_service.transicionar(db, nc_id=nd.id, accion="enviar_aprobacion", user_id=uid)
        ncs_locales_service.transicionar(db, nc_id=nd.id, accion="aprobar", user_id=uid)

        imp = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nd.id,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=varianza_antes,
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=uid,
        )
        cc_proveedor_service.aplicar_imputacion(db, imputacion_id=imp.id)
        db.refresh(pedido)

        varianza_despues = pedidos_service.calcular_varianza_tc(db, pedido)
        assert varianza_despues == Decimal("0"), f"After full ND, varianza should be 0, got {varianza_despues}"

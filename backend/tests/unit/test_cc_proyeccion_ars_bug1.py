"""
C.1 / C.3 — CC ARS projection tests (bug #1 fix: REQ-MM-007, design §6).

Tests that:
  - C.1a: HABER movement from imputacion uses imp.tipo_cambio (not pedido weighted-avg).
  - C.1b: Native USD saldo is unchanged by the TC variance in ARS projection.
  - C.1c: varianza_tc_ars field is present and correct per movement.
  - C.3: same-moneda USD imputacion with AD-7 TC generates correct varianza.

Scenario: USD pedido registered at TC=1410. Paid by USD OP at TC=1450.
  - CC ARS projection for the HABER must use TC=1450, NOT TC=1410.
  - Native USD saldo is unaffected (stays in USD).
"""

from __future__ import annotations

from datetime import date, datetime, UTC
from decimal import Decimal

import pytest

from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services.cc_proveedor_service import calcular_saldo_por_moneda


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — import the private function under test
# ─────────────────────────────────────────────────────────────────────────────


def _get_enriquecer():
    """Import the private function from the router module."""
    from app.routers.administracion_compras import _enriquecer_movimientos_cc  # noqa: PLC0415

    return _enriquecer_movimientos_cc


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=50, nombre="Empresa CC Bug1 Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        id=50,
        nombre="Proveedor Bug1 Test",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=50,
    )
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def pedido_usd_tc_1410(db, empresa: Empresa, proveedor: Proveedor, active_user) -> PedidoCompra:
    """USD pedido registered at TC=1410 (tc_snapshot / tipo_cambio_original)."""
    p = PedidoCompra(
        numero="PC-BUG1-001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=Decimal("1000"),
        tipo_cambio=Decimal("1410"),
        tipo_cambio_original=Decimal("1410"),
        tipo_cambio_manual=None,
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


def _make_cc_debe(
    db,
    empresa: Empresa,
    proveedor: Proveedor,
    pedido: PedidoCompra,
    user_id: int,
    monto: Decimal = Decimal("1000"),
) -> CCProveedorMovimiento:
    """Create a DEBE movement for the pedido (original debt in USD)."""
    mov = CCProveedorMovimiento(
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        fecha_movimiento=date.today(),
        tipo="debe",
        monto=monto,
        moneda="USD",
        tipo_cambio_a_ars=None,
        origen_tipo="pedido_compra",
        origen_id=pedido.id,
        creado_por_id=user_id,
        created_at=datetime.now(UTC),
    )
    db.add(mov)
    db.flush()
    return mov


def _make_imputacion_and_haber(
    db,
    empresa: Empresa,
    proveedor: Proveedor,
    pedido: PedidoCompra,
    user_id: int,
    tc_op: Decimal,
    monto_usd: Decimal = Decimal("1000"),
) -> tuple[Imputacion, CCProveedorMovimiento]:
    """Create an OP + imputacion (with tipo_cambio=tc_op) + HABER CC movement."""
    n = db.query(OrdenPago).count() + 1
    op = OrdenPago(
        numero=f"OP-BUG1-{n:04d}",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto_total=monto_usd,
        tipo_cambio=tc_op,
        modo_imputacion="especifica",
        estado="pagado",
        actualizar_tc_pedido=False,
        creado_por_id=user_id,
    )
    db.add(op)
    db.flush()

    imp = Imputacion(
        origen_tipo="orden_pago",
        origen_id=op.id,
        destino_tipo="pedido_compra",
        destino_id=pedido.id,
        proveedor_id=proveedor.id,
        monto_imputado=monto_usd,
        moneda_imputada="USD",
        tipo_cambio=tc_op,  # AD-7: same-moneda USD imp carries op TC
        es_reversal=False,
        creado_por_id=user_id,
    )
    db.add(imp)
    db.flush()

    haber = CCProveedorMovimiento(
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        fecha_movimiento=date.today(),
        tipo="haber",
        monto=monto_usd,
        moneda="USD",
        tipo_cambio_a_ars=None,  # No persisted ARS TC on haber — must be resolved via imp
        origen_tipo="imputacion",
        origen_id=imp.id,
        creado_por_id=user_id,
        created_at=datetime.now(UTC),
    )
    db.add(haber)
    db.flush()

    return imp, haber


# ─────────────────────────────────────────────────────────────────────────────
# C.1a — HABER uses imp.tipo_cambio, NOT the pedido weighted avg
# ─────────────────────────────────────────────────────────────────────────────


def test_cc_proyeccion_ars_usa_tc_liquidacion_por_mov(db, empresa, proveedor, pedido_usd_tc_1410, active_user):
    """C.1a — USD pedido@TC=1410, paid by USD OP@TC=1450.
    The HABER ARS projection must use TC=1450 (the liquidation TC of that OP).
    Historically it used TC=1410 (pedido weighted avg) — that is bug #1.
    Spec: REQ-MM-007, design §6.2.
    """
    _enriquecer_movimientos_cc = _get_enriquecer()

    imp, haber_mov = _make_imputacion_and_haber(
        db,
        empresa,
        proveedor,
        pedido_usd_tc_1410,
        active_user.id,
        tc_op=Decimal("1450"),
        monto_usd=Decimal("1000"),
    )

    result = _enriquecer_movimientos_cc(db, [haber_mov])
    assert len(result) == 1
    haber_resp = result[0]

    # The ARS projection must reflect TC=1450, NOT TC=1410.
    expected_monto_ars = (Decimal("1000") * Decimal("1450")).quantize(Decimal("0.01"))
    assert haber_resp.monto_ars == expected_monto_ars, (
        f"Expected monto_ars={expected_monto_ars} (TC=1450), got {haber_resp.monto_ars}. "
        "Bug #1: projection was using pedido TC (1410) instead of imp TC (1450)."
    )
    assert haber_resp.tc_aplicado == Decimal("1450")


# ─────────────────────────────────────────────────────────────────────────────
# C.1b — Native USD saldo is unchanged by TC variance
# ─────────────────────────────────────────────────────────────────────────────


def test_cc_saldo_nativo_no_cambia_por_varianza_tc(db, empresa, proveedor, pedido_usd_tc_1410, active_user):
    """C.1b — The native USD saldo (calcular_saldo_por_moneda) must not change
    regardless of which TC is used for ARS projection.
    Spec: REQ-MM-007, design §6.1 (saldo nativo intocable).
    """
    monto_usd = Decimal("1000")

    # Create the DEBE movement (debt in USD).
    _make_cc_debe(db, empresa, proveedor, pedido_usd_tc_1410, active_user.id, monto=monto_usd)

    # Pay with OP at a different TC than the pedido's tc_snapshot.
    _make_imputacion_and_haber(
        db,
        empresa,
        proveedor,
        pedido_usd_tc_1410,
        active_user.id,
        tc_op=Decimal("1450"),
        monto_usd=monto_usd,
    )

    # The native USD saldo must be 0 (debe=1000, haber=1000 → net 0).
    saldos = calcular_saldo_por_moneda(db, proveedor_id=proveedor.id)
    usd_saldo = saldos.get("USD")

    assert usd_saldo == Decimal("0"), (
        f"Native USD saldo should be 0 after full payment (debe=haber=1000). Got: {usd_saldo}. "
        "The ARS projection TC change must NOT affect the native saldo."
    )


# ─────────────────────────────────────────────────────────────────────────────
# C.1c — varianza_tc_ars field present and correct
# ─────────────────────────────────────────────────────────────────────────────


def test_cc_por_pedido_expone_varianza_tc_ars(db, empresa, proveedor, pedido_usd_tc_1410, active_user):
    """C.1c — Movement HABER must expose varianza_tc_ars = (tc_op - tc_pedido) * usd.
    Formula: (1450 - 1410) * 1000 = 40000 ARS.
    Spec: REQ-MM-007, design §6.2, §4.1.
    """
    _enriquecer_movimientos_cc = _get_enriquecer()

    imp, haber_mov = _make_imputacion_and_haber(
        db,
        empresa,
        proveedor,
        pedido_usd_tc_1410,
        active_user.id,
        tc_op=Decimal("1450"),
        monto_usd=Decimal("1000"),
    )

    result = _enriquecer_movimientos_cc(db, [haber_mov])
    assert len(result) == 1
    haber_resp = result[0]

    # varianza_tc_ars = (1450 - 1410) * 1000 = 40000.00
    expected_varianza = Decimal("40000.00")
    assert hasattr(haber_resp, "varianza_tc_ars"), (
        "CCMovimientoResponse must expose varianza_tc_ars field (C.2 adds this field)."
    )
    assert haber_resp.varianza_tc_ars == expected_varianza, (
        f"Expected varianza_tc_ars={expected_varianza}, got {haber_resp.varianza_tc_ars}."
    )


# ─────────────────────────────────────────────────────────────────────────────
# C.3 — Same-moneda USD with AD-7 imp TC generates correct varianza
# ─────────────────────────────────────────────────────────────────────────────


def test_fx_same_moneda_usd_con_tc_ad7(db, empresa, proveedor, pedido_usd_tc_1410, active_user):
    """C.3 / ADR-4 — Same-moneda USD imp (AD-7) with tc_op != tc_pedido_snapshot.
    The CC projection should still use imp.tipo_cambio and expose varianza_tc_ars.
    This confirms AD-7 imps (same-moneda USD, but op TC != pedido TC) are handled.
    Spec: ADR-4, design §5.1.
    """
    _enriquecer_movimientos_cc = _get_enriquecer()

    # tc_op = 1450 != tc_pedido = 1410 → varianza = (1450-1410)*500 = 20000
    imp, haber_mov = _make_imputacion_and_haber(
        db,
        empresa,
        proveedor,
        pedido_usd_tc_1410,
        active_user.id,
        tc_op=Decimal("1450"),
        monto_usd=Decimal("500"),
    )

    result = _enriquecer_movimientos_cc(db, [haber_mov])
    assert len(result) == 1
    haber_resp = result[0]

    # ARS projection: 500 * 1450 = 725000.00
    assert haber_resp.monto_ars == Decimal("725000.00"), f"Expected monto_ars=725000.00, got {haber_resp.monto_ars}"
    assert haber_resp.tc_aplicado == Decimal("1450")

    # varianza_tc_ars = (1450 - 1410) * 500 = 20000.00
    expected_varianza = Decimal("20000.00")
    assert hasattr(haber_resp, "varianza_tc_ars")
    assert haber_resp.varianza_tc_ars == expected_varianza, (
        f"Expected varianza_tc_ars=20000, got {haber_resp.varianza_tc_ars}"
    )

"""
Tests para el modelo net-item de cobertura NC/DAC.

Modelo corregido (fix over-imputación):
  El item pedido/factura lleva el monto NETO (ya descontados NC y DAC).
  El balance es:
    monto_total = sum(pedido/factura NET items) + sum(pago_a_cuenta)

  NC y DAC no son términos del balance. Su efecto está reflejado en los
  montos netos de los items.

Cobertura:
  - Regresión: OP solo con pedidos sigue balanceando.
  - NC mismo moneda: item ya es neto (item=25M, monto_total=25M) → balancea.
  - NC cross-moneda: item ya es neto en moneda OP → balancea.
  - DAC same-moneda: item ya es neto (item=25M, monto_total=25M) → balancea.
  - pago_a_cuenta sigue siendo ADITIVO.
  - Mismatch levanta 422.
  - Old additive model (item full + NC subtractive) ahora falla correctamente.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.ordenes_pago_service import validar_balance_op


# ──────────────────────────────────────────────────────────────────────────
# Minimal stubs (no DB needed for validar_balance_op unit tests)
# ──────────────────────────────────────────────────────────────────────────


class _FakeOP:
    """Stub de OrdenPago con los campos que usa validar_balance_op."""

    def __init__(self, *, monto_total: Decimal, moneda: str = "ARS") -> None:
        self.monto_total = monto_total
        self.moneda = moneda


class _FakeSession:
    """Stub de Session que responde get() con objetos pre-seed."""

    def __init__(self, objects: dict | None = None) -> None:
        self._objects: dict[tuple, object] = objects or {}

    def get(self, model_class: type, pk: int) -> object | None:
        return self._objects.get((model_class.__name__, pk))


def _fake_nc(*, nc_id: int, moneda: str, monto: Decimal, tipo_cambio: Decimal | None = None) -> object:
    """Factory de stub NC."""

    class _NC:
        pass

    nc = _NC()
    nc.id = nc_id
    nc.moneda = moneda
    nc.monto = monto
    nc.tipo_cambio = tipo_cambio
    return nc


# ──────────────────────────────────────────────────────────────────────────
# 1. Regresión: OP solo con pedidos, sin NCs — sin cambio de comportamiento
# ──────────────────────────────────────────────────────────────────────────


def test_regression_op_solo_pedidos_balancea() -> None:
    """
    OP ARS, sum(items)=30_000_000, monto_total=30_000_000, sin NCs → balance OK.
    """
    op = _FakeOP(monto_total=Decimal("30000000"), moneda="ARS")
    session = _FakeSession()
    items = [{"tipo": "pedido_compra", "monto": 30_000_000}]
    # No debe lanzar excepción.
    validar_balance_op(session, op, items)


# ──────────────────────────────────────────────────────────────────────────
# 2. NC same-moneda: REDUCE el cash a pagar
# ──────────────────────────────────────────────────────────────────────────


def test_nc_same_moneda_reduce_cash() -> None:
    """
    Net-item model: NC discount is baked into the item monto.
    OP=ARS, item=25M (net = 30M - 5M NC), monto_total=25M → balancea.
    NC is not a balance term — it is reflected in the net item.
    """

    nc_id = 1
    nc = _fake_nc(nc_id=nc_id, moneda="ARS", monto=Decimal("5000000"), tipo_cambio=None)
    session = _FakeSession({("NotaCreditoLocal", nc_id): nc})

    op = _FakeOP(monto_total=Decimal("25000000"), moneda="ARS")
    # Item is NET (25M), not full (30M). NC is not a balance term.
    items = [{"tipo": "pedido_compra", "monto": 25_000_000}]

    # Must NOT raise: item=25M == monto_total=25M
    validar_balance_op(session, op, items)


def test_nc_same_moneda_full_item_raises() -> None:
    """
    In the net-item model, sending the FULL item (30M) while monto_total=25M → 422.
    The item must already be net-of-NC (25M) to balance.
    """
    from fastapi import HTTPException

    nc_id = 2
    nc = _fake_nc(nc_id=nc_id, moneda="ARS", monto=Decimal("5000000"), tipo_cambio=None)
    session = _FakeSession({("NotaCreditoLocal", nc_id): nc})

    # monto_total=25M, but item is full 30M → diferencia = 30M - 25M = +5M ≠ 0
    op = _FakeOP(monto_total=Decimal("25000000"), moneda="ARS")
    items = [{"tipo": "pedido_compra", "monto": 30_000_000}]  # full, not net — wrong

    with pytest.raises(HTTPException) as exc_info:
        validar_balance_op(session, op, items)

    assert exc_info.value.status_code == 422
    assert "diferencia" in exc_info.value.detail.lower() or "balancea" in exc_info.value.detail.lower()


# ──────────────────────────────────────────────────────────────────────────
# 3. NC cross-moneda: OP=ARS, NC=USD → convertir con TC propio de la NC
# ──────────────────────────────────────────────────────────────────────────


def test_nc_cross_moneda_net_item_balancea() -> None:
    """
    Net-item model with cross-moneda NC.
    OP=ARS, pedido=23_404_073 ARS, NC=5_000 USD at tc=1_400 → NC_ARS=7_000_000.
    Frontend computes net item = 23_404_073 - 7_000_000 = 16_404_073.
    Item sent = 16_404_073 (net), monto_total = 16_404_073 → balancea.
    """

    nc_id = 10
    nc = _fake_nc(nc_id=nc_id, moneda="USD", monto=Decimal("5000"), tipo_cambio=Decimal("1400"))
    session = _FakeSession({("NotaCreditoLocal", nc_id): nc})

    op = _FakeOP(monto_total=Decimal("16404073"), moneda="ARS")
    # Item is NET (already discounted 7M NC ARS equivalent).
    items = [{"tipo": "pedido_compra", "monto": "16404073"}]

    validar_balance_op(session, op, items)


def test_nc_cross_moneda_net_item_tc_override_balancea() -> None:
    """
    Same scenario with tc_override=1_450.
    NC_ARS = 5_000 * 1_450 = 7_250_000 → net item = 23_404_073 - 7_250_000 = 16_154_073.
    """

    nc_id = 11
    nc = _fake_nc(nc_id=nc_id, moneda="USD", monto=Decimal("5000"), tipo_cambio=Decimal("1400"))
    session = _FakeSession({("NotaCreditoLocal", nc_id): nc})

    op = _FakeOP(monto_total=Decimal("16154073"), moneda="ARS")
    items = [{"tipo": "pedido_compra", "monto": "16154073"}]

    validar_balance_op(session, op, items)


def test_nc_cross_moneda_wrong_monto_raises() -> None:
    """
    OP=ARS, net item=16_404_073, monto_total=16_000_000 (incorrecto) → 422.
    """
    from fastapi import HTTPException

    nc_id = 12
    nc = _fake_nc(nc_id=nc_id, moneda="USD", monto=Decimal("5000"), tipo_cambio=Decimal("1400"))
    session = _FakeSession({("NotaCreditoLocal", nc_id): nc})

    op = _FakeOP(monto_total=Decimal("16000000"), moneda="ARS")
    items = [{"tipo": "pedido_compra", "monto": "16404073"}]  # net but total is wrong

    with pytest.raises(HTTPException) as exc_info:
        validar_balance_op(session, op, items)

    assert exc_info.value.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# 4. DAC same-moneda: subtractive (DAC no tiene tipo_cambio — same-moneda only)
# ──────────────────────────────────────────────────────────────────────────


def test_dac_net_item_balancea() -> None:
    """
    Net-item model with DAC.
    OP=ARS, pedido saldo=30M, DAC=5M → net cash item = 25M, monto_total = 25M.
    dinero_a_cuenta item is present in the list but NOT counted in the balance.
    """
    op = _FakeOP(monto_total=Decimal("25000000"), moneda="ARS")
    items = [
        {"tipo": "pedido_compra", "monto": 25_000_000},  # NET: 30M - 5M DAC
        {"tipo": "dinero_a_cuenta", "monto": 5_000_000},  # side payment, not balance term
    ]
    session = _FakeSession()

    validar_balance_op(session, op, items)


def test_dac_full_item_raises() -> None:
    """
    Sending the FULL pedido item (30M) with DAC 5M and monto_total=25M → 422
    because items sum (30M) ≠ monto_total (25M) in the net-item model.
    (Old model passed this; new model correctly rejects it.)
    """
    from fastapi import HTTPException

    op = _FakeOP(monto_total=Decimal("25000000"), moneda="ARS")
    items = [
        {"tipo": "pedido_compra", "monto": 30_000_000},  # full, not net — wrong
        {"tipo": "dinero_a_cuenta", "monto": 5_000_000},
    ]
    session = _FakeSession()

    with pytest.raises(HTTPException) as exc_info:
        validar_balance_op(session, op, items)

    assert exc_info.value.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# 5. pago_a_cuenta sigue siendo ADITIVO
# ──────────────────────────────────────────────────────────────────────────


def test_pago_a_cuenta_aditivo() -> None:
    """
    pago_a_cuenta es excedente de cash en moneda OP → sigue siendo ADITIVO.
    OP=ARS, item=8M, pago_a_cuenta=2M → monto_total=10M (8+2).
    """
    op = _FakeOP(monto_total=Decimal("10000000"), moneda="ARS")
    items = [
        {"tipo": "pedido_compra", "monto": 8_000_000},
        {"tipo": "pago_a_cuenta", "monto": 2_000_000},
    ]
    session = _FakeSession()

    validar_balance_op(session, op, items)


# ──────────────────────────────────────────────────────────────────────────
# 6. Mismatch levanta 422 con mensaje útil
# ──────────────────────────────────────────────────────────────────────────


def test_mismatch_levanta_422_con_mensaje() -> None:
    """
    Diferencia != 0 → HTTPException 422 con 'diferencia' o 'balancea' en detail.
    """
    from fastapi import HTTPException

    op = _FakeOP(monto_total=Decimal("20000"), moneda="ARS")
    items = [{"tipo": "pedido_compra", "monto": 15_000}]
    session = _FakeSession()

    with pytest.raises(HTTPException) as exc_info:
        validar_balance_op(session, op, items)

    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail.lower()
    assert "diferencia" in detail or "balancea" in detail

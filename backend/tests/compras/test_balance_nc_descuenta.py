"""
Tests para el nuevo modelo de cobertura NC/DAC (AD-NC-01):

  monto_total = sum(pedido/factura items) + sum(pago_a_cuenta) - sum(NC en moneda OP) - sum(DAC en moneda OP)

Cobertura:
  - Regresión: OP solo con pedidos sigue balanceando sin NCs.
  - NC mismo moneda reduce el cash: OP=ARS, item=30M ARS, NC=5M ARS → monto_total=25M.
  - NC cross-moneda vía TC propio: OP=ARS, item=23.404.073 ARS, NC=5000 USD, tc=1400 → NC_ARS=7M → monto_total=16.404.073.
  - NC cross-moneda con tipo_cambio_override: mismo escenario pero tc_override=1450 → NC_ARS=7.25M.
  - DAC same-moneda: subtractive (DAC no tiene tipo_cambio, solo funciona same-moneda).
  - pago_a_cuenta sigue siendo ADITIVO (excedente aumenta el cash requerido).
  - Mismatch (balance != 0) levanta 422 con mensaje claro.

Strict TDD: estos tests se escriben ANTES de cambiar validar_balance_op.
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
    validar_balance_op(session, op, items, ncs_pendientes=None)


# ──────────────────────────────────────────────────────────────────────────
# 2. NC same-moneda: REDUCE el cash a pagar
# ──────────────────────────────────────────────────────────────────────────


def test_nc_same_moneda_reduce_cash() -> None:
    """
    OP=ARS, item=30M, NC ARS=5M → monto_total correcto = 25M (no 35M).
    Con monto_total=25M debe balancear.
    """

    nc_id = 1
    nc = _fake_nc(nc_id=nc_id, moneda="ARS", monto=Decimal("5000000"), tipo_cambio=None)
    session = _FakeSession({("NotaCreditoLocal", nc_id): nc})

    op = _FakeOP(monto_total=Decimal("25000000"), moneda="ARS")
    items = [{"tipo": "pedido_compra", "monto": 30_000_000}]
    ncs_pendientes = [{"nc_id": nc_id, "monto": "5000000"}]

    # Must NOT raise: 30M - 5M = 25M == monto_total
    validar_balance_op(session, op, items, ncs_pendientes=ncs_pendientes)


def test_nc_same_moneda_old_additive_model_raises() -> None:
    """
    Con el nuevo modelo, monto_total=35M cuando NC es subtractive → 422.
    (Esto verifica que el modelo VIEJO fallaría y el nuevo rechaza 35M.)
    """
    from fastapi import HTTPException

    nc_id = 2
    nc = _fake_nc(nc_id=nc_id, moneda="ARS", monto=Decimal("5000000"), tipo_cambio=None)
    session = _FakeSession({("NotaCreditoLocal", nc_id): nc})

    # monto_total=35M es el incorrecto (modelo aditivo viejo)
    op = _FakeOP(monto_total=Decimal("35000000"), moneda="ARS")
    items = [{"tipo": "pedido_compra", "monto": 30_000_000}]
    ncs_pendientes = [{"nc_id": nc_id, "monto": "5000000"}]

    with pytest.raises(HTTPException) as exc_info:
        validar_balance_op(session, op, items, ncs_pendientes=ncs_pendientes)

    assert exc_info.value.status_code == 422
    assert "diferencia" in exc_info.value.detail.lower() or "balancea" in exc_info.value.detail.lower()


# ──────────────────────────────────────────────────────────────────────────
# 3. NC cross-moneda: OP=ARS, NC=USD → convertir con TC propio de la NC
# ──────────────────────────────────────────────────────────────────────────


def test_nc_cross_moneda_usa_tc_propio() -> None:
    """
    OP=ARS, item=23_404_073 ARS, NC=5_000 USD, nc.tipo_cambio=1_400
    → NC_ARS = 5_000 * 1_400 = 7_000_000
    → monto_total correcto = 23_404_073 - 7_000_000 = 16_404_073
    """

    nc_id = 10
    nc = _fake_nc(nc_id=nc_id, moneda="USD", monto=Decimal("5000"), tipo_cambio=Decimal("1400"))
    session = _FakeSession({("NotaCreditoLocal", nc_id): nc})

    op = _FakeOP(monto_total=Decimal("16404073"), moneda="ARS")
    items = [{"tipo": "pedido_compra", "monto": "23404073"}]
    ncs_pendientes = [{"nc_id": nc_id, "monto": "5000"}]

    validar_balance_op(session, op, items, ncs_pendientes=ncs_pendientes)


def test_nc_cross_moneda_tc_override() -> None:
    """
    Mismo escenario pero con tipo_cambio_override=1_450 en el nc item.
    NC_ARS = 5_000 * 1_450 = 7_250_000
    monto_total = 23_404_073 - 7_250_000 = 16_154_073
    """

    nc_id = 11
    nc = _fake_nc(nc_id=nc_id, moneda="USD", monto=Decimal("5000"), tipo_cambio=Decimal("1400"))
    session = _FakeSession({("NotaCreditoLocal", nc_id): nc})

    op = _FakeOP(monto_total=Decimal("16154073"), moneda="ARS")
    items = [{"tipo": "pedido_compra", "monto": "23404073"}]
    ncs_pendientes = [{"nc_id": nc_id, "monto": "5000", "tipo_cambio_override": "1450"}]

    validar_balance_op(session, op, items, ncs_pendientes=ncs_pendientes)


def test_nc_cross_moneda_wrong_monto_raises() -> None:
    """
    OP=ARS, item=23_404_073, NC=5_000 USD, tc=1_400 → NC_ARS=7_000_000
    Si monto_total=16_000_000 (incorrecto) → 422.
    """
    from fastapi import HTTPException

    nc_id = 12
    nc = _fake_nc(nc_id=nc_id, moneda="USD", monto=Decimal("5000"), tipo_cambio=Decimal("1400"))
    session = _FakeSession({("NotaCreditoLocal", nc_id): nc})

    op = _FakeOP(monto_total=Decimal("16000000"), moneda="ARS")
    items = [{"tipo": "pedido_compra", "monto": "23404073"}]
    ncs_pendientes = [{"nc_id": nc_id, "monto": "5000"}]

    with pytest.raises(HTTPException) as exc_info:
        validar_balance_op(session, op, items, ncs_pendientes=ncs_pendientes)

    assert exc_info.value.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# 4. DAC same-moneda: subtractive (DAC no tiene tipo_cambio — same-moneda only)
# ──────────────────────────────────────────────────────────────────────────


def test_dac_same_moneda_subtractive() -> None:
    """
    OP=ARS, item=30M, DAC=5M ARS (mismo moneda) → monto_total = 25M.
    Los items dinero_a_cuenta son subtractive bajo el nuevo modelo.
    """
    op = _FakeOP(monto_total=Decimal("25000000"), moneda="ARS")
    items = [
        {"tipo": "pedido_compra", "monto": 30_000_000},
        {"tipo": "dinero_a_cuenta", "monto": 5_000_000},
    ]
    session = _FakeSession()

    validar_balance_op(session, op, items, ncs_pendientes=None)


def test_dac_old_additive_model_raises() -> None:
    """
    Con el nuevo modelo subtractive, monto_total=35M (viejo additive) → 422.
    """
    from fastapi import HTTPException

    op = _FakeOP(monto_total=Decimal("35000000"), moneda="ARS")
    items = [
        {"tipo": "pedido_compra", "monto": 30_000_000},
        {"tipo": "dinero_a_cuenta", "monto": 5_000_000},
    ]
    session = _FakeSession()

    with pytest.raises(HTTPException) as exc_info:
        validar_balance_op(session, op, items, ncs_pendientes=None)

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

    validar_balance_op(session, op, items, ncs_pendientes=None)


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
        validar_balance_op(session, op, items, ncs_pendientes=None)

    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail.lower()
    assert "diferencia" in detail or "balancea" in detail

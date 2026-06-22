"""
Tests unitarios — cheque como componente de cobertura en validar_balance_op.

TDD Strict — RED phase. Cubre FR-1.2, FR-1.3:
  - Cheque cubre 100% la OP (diferencia 0).
  - Cheque + caja combinados (diferencia 0).
  - Cheque insuficiente → falta cubrir → 422.
  - Cross-moneda cheque ARS / OP USD → una sola conversión con TC, tolerancia.
  - Regresión: comportamiento existente sin cheques no cambia.

La firma extendida de validar_balance_op acepta cheques_op_moneda opcional,
que es Σ de los montos de los cheques ya derivados a moneda OP.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.services.ordenes_pago_service import validar_balance_op


# ──────────────────────────────────────────────────────────────────────────
# Stubs (sin DB)
# ──────────────────────────────────────────────────────────────────────────


class _FakeOP:
    def __init__(self, *, monto_total: Decimal, moneda: str = "ARS") -> None:
        self.monto_total = monto_total
        self.moneda = moneda


class _FakeSession:
    def __init__(self) -> None:
        self._objects: dict = {}

    def get(self, model_class: type, pk: int) -> object | None:
        return self._objects.get((model_class.__name__, pk))


# ──────────────────────────────────────────────────────────────────────────
# 1. Cheque cubre 100% — diferencia cero
# ──────────────────────────────────────────────────────────────────────────


def test_cheque_cubre_100_pct() -> None:
    """
    OP ARS 1_000_000. Cheque ARS 1_000_000 (mismo_moneda → monto_op_moneda=1_000_000).
    items=[] (pago_a_cuenta=0). cheques_op_moneda=1_000_000 → diferencia=0.
    """
    op = _FakeOP(monto_total=Decimal("1000000"), moneda="ARS")
    session = _FakeSession()
    items: list[dict] = []
    validar_balance_op(session, op, items, cheques_op_moneda=Decimal("1000000"))


# ──────────────────────────────────────────────────────────────────────────
# 2. Cheque + pago_a_cuenta combinados
# ──────────────────────────────────────────────────────────────────────────


def test_cheque_mas_pago_a_cuenta_combinados() -> None:
    """
    OP ARS 1_000_000. Cheque cubre 700_000, caja (pago_a_cuenta item) 300_000.
    base_items=0, pago_a_cuenta=300_000, cheques=700_000 → total=1_000_000 → OK.

    Nota: en modo 'a_cuenta' sin pedido específico, el efectivo va como pago_a_cuenta.
    En modo 'especifica', el efectivo iría en base_items. Acá testeamos ambos vectores.
    """
    op = _FakeOP(monto_total=Decimal("1000000"), moneda="ARS")
    session = _FakeSession()
    # Efectivo via pago_a_cuenta item
    items = [{"tipo": "pago_a_cuenta", "monto": "300000"}]
    validar_balance_op(session, op, items, cheques_op_moneda=Decimal("700000"))


def test_cheque_mas_pedido_item_combinados() -> None:
    """
    OP ARS 1_000_000. Cheque 700_000, pedido item neto 300_000.
    base_items=300_000, cheques=700_000 → total=1_000_000 → OK.
    """
    op = _FakeOP(monto_total=Decimal("1000000"), moneda="ARS")
    session = _FakeSession()
    items = [{"tipo": "pedido_compra", "id": 999, "monto": "300000"}]

    # Fake pedido so _validar_items_saldo_pendiente does not reject

    class _FakePedido:
        moneda = "ARS"

    session._objects[("PedidoCompra", 999)] = _FakePedido()

    # _validar_items_saldo_pendiente calls calcular_saldo_pendiente_pedido —
    # patch it so it returns a high number (not under test here).
    import app.services.pedidos_service as _ps  # noqa: PLC0415

    orig = _ps.calcular_saldo_pendiente_pedido
    _ps.calcular_saldo_pendiente_pedido = lambda s, pid: Decimal("9999999")  # type: ignore[assignment]
    try:
        validar_balance_op(session, op, items, cheques_op_moneda=Decimal("700000"))
    finally:
        _ps.calcular_saldo_pendiente_pedido = orig


# ──────────────────────────────────────────────────────────────────────────
# 3. Cheque insuficiente → 422
# ──────────────────────────────────────────────────────────────────────────


def test_cheque_insuficiente_levanta_422() -> None:
    """
    OP ARS 1_000_000, cheque 600_000, sin caja → diferencia = -400_000 → 422.
    """
    op = _FakeOP(monto_total=Decimal("1000000"), moneda="ARS")
    session = _FakeSession()
    items: list[dict] = []

    with pytest.raises(HTTPException) as exc_info:
        validar_balance_op(session, op, items, cheques_op_moneda=Decimal("600000"))

    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail.lower()
    assert "diferencia" in detail or "balancea" in detail


# ──────────────────────────────────────────────────────────────────────────
# 4. Cross-moneda: cheque ARS / OP USD
# ──────────────────────────────────────────────────────────────────────────


def test_cheque_ars_op_usd_cross_moneda() -> None:
    """
    OP USD 1_000, TC=1_400. Cheque ARS 1_400_000 → monto_op_moneda = 1_000 USD.
    La derivación la hace el caller (ejecutar_pago/crear_y_pagar), no validar_balance_op.
    validar_balance_op recibe cheques_op_moneda ya derivados: 1_000 USD.
    items=[], cheques_op_moneda=1_000 USD → diferencia=0.
    """
    op = _FakeOP(monto_total=Decimal("1000"), moneda="USD")
    session = _FakeSession()
    items: list[dict] = []
    # caller ya derivó: 1_400_000 ARS / 1_400 = 1_000 USD
    validar_balance_op(session, op, items, cheques_op_moneda=Decimal("1000"))


def test_cheque_ars_op_usd_tolerancia_sub_centavo() -> None:
    """
    Cross-moneda ARS→USD puede dejar ruido float sub-centavo.
    1_400_001 ARS / 1_400 = 1_000.000714... USD → q_usd = 1_000.00 USD.
    cheques_op_moneda = 1_000.0007 → diferencia = 0.0007 < 0.005 → OK.
    """
    op = _FakeOP(monto_total=Decimal("1000"), moneda="USD")
    session = _FakeSession()
    items: list[dict] = []
    validar_balance_op(session, op, items, cheques_op_moneda=Decimal("1000.0007"))


# ──────────────────────────────────────────────────────────────────────────
# 5. Regresión: sin cheques → comportamiento idéntico al anterior
# ──────────────────────────────────────────────────────────────────────────


def test_sin_cheques_comportamiento_sin_cambio() -> None:
    """cheques_op_moneda omitido → no cambia el balance existente."""
    op = _FakeOP(monto_total=Decimal("30000000"), moneda="ARS")
    session = _FakeSession()
    items = [{"tipo": "pedido_compra", "monto": 30_000_000}]

    import app.services.pedidos_service as _ps  # noqa: PLC0415

    class _FakePedido:
        moneda = "ARS"

    session._objects[("PedidoCompra", None)] = _FakePedido()
    orig = _ps.calcular_saldo_pendiente_pedido
    _ps.calcular_saldo_pendiente_pedido = lambda s, pid: Decimal("9999999")  # type: ignore[assignment]
    try:
        # Must not raise — same as before
        validar_balance_op(session, op, items)
    finally:
        _ps.calcular_saldo_pendiente_pedido = orig

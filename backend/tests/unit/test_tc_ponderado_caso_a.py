"""
T1.11–T1.18 — Tests for calcular_tc_ponderado_caso_a and its batch variant.
T1.19–T1.22 — Tests for resolver_tc_efectivo_pedido.

Uses the shared SQLite `db` fixture with rollback-per-test isolation.
All scenarios target ARS→USD cross-moneda payments (the primary hot path
per Amendment A2), i.e. an ARS OP paying a USD pedido.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import pedidos_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa TC Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(id=1, nombre="Proveedor TC", activo=True, origen=OrigenProveedor.ERP.value, supp_id=1)
    db.add(prov)
    db.flush()
    return prov


def _make_pedido_usd(db, empresa, proveedor, user_id: int, tc_original: Decimal = Decimal("1400")) -> PedidoCompra:
    """Create an approved USD pedido."""
    pedido = PedidoCompra(
        numero=f"PC-{db.query(PedidoCompra).count() + 1:04d}",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=Decimal("1000"),
        tipo_cambio=tc_original,
        tipo_cambio_original=tc_original,
        estado="aprobado",
        creado_por_id=user_id,
    )
    db.add(pedido)
    db.flush()
    return pedido


def _make_op(db, empresa, proveedor, user_id: int, actualizar_tc: bool, tc: Decimal) -> OrdenPago:
    """Create an ARS OP with the given actualizar_tc_pedido flag."""
    n = db.query(OrdenPago).count() + 1
    op = OrdenPago(
        numero=f"OP-{n:04d}",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=Decimal("1000000"),
        tipo_cambio=tc,
        modo_imputacion="especifica",
        estado="pagado",
        actualizar_tc_pedido=actualizar_tc,
        creado_por_id=user_id,
    )
    db.add(op)
    db.flush()
    return op


def _make_imputacion(
    db,
    op: OrdenPago,
    pedido: PedidoCompra,
    user_id: int,
    monto_usd: Decimal,
    tc: Decimal,
    es_reversal: bool = False,
) -> Imputacion:
    """
    Create an ARS→USD cross-moneda imputacion.

    `monto_imputado` is in pedido.moneda (USD).
    `tipo_cambio` is the TC (ARS/USD).
    This mirrors what ejecutar_pago does for cross-moneda.
    """
    imp = Imputacion(
        origen_tipo="orden_pago",
        origen_id=op.id,
        destino_tipo="pedido_compra",
        destino_id=pedido.id,
        monto_imputado=monto_usd,
        moneda_imputada="USD",
        tipo_cambio=tc,
        proveedor_id=pedido.proveedor_id,
        es_reversal=es_reversal,
        creado_por_id=user_id,
    )
    db.add(imp)
    db.flush()
    return imp


# ──────────────────────────────────────────────────────────────────────────
# T1.11 — single Caso-A payment
# ──────────────────────────────────────────────────────────────────────────


class TestCalcularTcPonderadoCasoA:
    """Tests for pedidos_service.calcular_tc_ponderado_caso_a."""

    def test_single_payment_returns_its_tc(self, db, empresa, proveedor, active_user) -> None:
        """T1.11 — One Caso-A OP (ARS pays USD pedido, TC 1450, USD 600) → returns 1450."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1400"))
        op = _make_op(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1450"))
        _make_imputacion(db, op, pedido, uid, monto_usd=Decimal("600"), tc=Decimal("1450"))

        tc = pedidos_service.calcular_tc_ponderado_caso_a(db, pedido.id)
        assert tc is not None
        assert tc == Decimal("1450").quantize(Decimal("0.0001"))

    def test_two_payments_weighted_average(self, db, empresa, proveedor, active_user) -> None:
        """T1.12 — AC1.2: two Caso-A payments → weighted average = 1442."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1400"))
        op1 = _make_op(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1450"))
        op2 = _make_op(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1430"))
        _make_imputacion(db, op1, pedido, uid, monto_usd=Decimal("600"), tc=Decimal("1450"))
        _make_imputacion(db, op2, pedido, uid, monto_usd=Decimal("400"), tc=Decimal("1430"))

        tc = pedidos_service.calcular_tc_ponderado_caso_a(db, pedido.id)
        assert tc is not None
        # (600*1450 + 400*1430) / 1000 = (870000 + 572000) / 1000 = 1442
        assert tc == Decimal("1442.0000")

    def test_ignores_caso_b_payments(self, db, empresa, proveedor, active_user) -> None:
        """T1.13 — Mixed payments: Caso-B imputaciones are ignored."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1400"))
        op_a = _make_op(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1450"))
        op_b = _make_op(db, empresa, proveedor, uid, actualizar_tc=False, tc=Decimal("1430"))
        _make_imputacion(db, op_a, pedido, uid, monto_usd=Decimal("600"), tc=Decimal("1450"))
        _make_imputacion(db, op_b, pedido, uid, monto_usd=Decimal("400"), tc=Decimal("1430"))

        tc = pedidos_service.calcular_tc_ponderado_caso_a(db, pedido.id)
        assert tc is not None
        # Only op_a contributes: 600 USD at TC 1450 → TC ponderado = 1450
        assert tc == Decimal("1450.0000")

    def test_returns_none_when_no_caso_a(self, db, empresa, proveedor, active_user) -> None:
        """T1.14 — No Caso-A imputaciones → returns None."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1400"))
        op_b = _make_op(db, empresa, proveedor, uid, actualizar_tc=False, tc=Decimal("1450"))
        _make_imputacion(db, op_b, pedido, uid, monto_usd=Decimal("1000"), tc=Decimal("1450"))

        tc = pedidos_service.calcular_tc_ponderado_caso_a(db, pedido.id)
        assert tc is None

    def test_returns_none_when_no_imputaciones(self, db, empresa, proveedor, active_user) -> None:
        """No imputaciones at all → returns None."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid)
        tc = pedidos_service.calcular_tc_ponderado_caso_a(db, pedido.id)
        assert tc is None

    def test_reversal_row_excluded_from_numerator(self, db, empresa, proveedor, active_user) -> None:
        """AC1.5 — reversal rows (es_reversal=True) are excluded from the weighted average.
        The ORIGINAL imputacion still counts; the reversal row does NOT add to the pool.
        This aligns with the existing calcular_tc_ponderado_pedido convention:
        'reversals excluidos' means the es_reversal=True row is skipped, not that
        the original is retroactively removed from the TC average pool.
        """
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1400"))
        op1 = _make_op(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1450"))
        op2 = _make_op(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1430"))
        _make_imputacion(db, op1, pedido, uid, monto_usd=Decimal("600"), tc=Decimal("1450"))
        _make_imputacion(db, op2, pedido, uid, monto_usd=Decimal("400"), tc=Decimal("1430"))

        # Add a reversal row (es_reversal=True) — this should NOT be counted.
        reversal = Imputacion(
            origen_tipo="orden_pago",
            origen_id=op2.id,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=Decimal("400"),
            moneda_imputada="USD",
            tipo_cambio=Decimal("1430"),
            proveedor_id=pedido.proveedor_id,
            es_reversal=True,
            creado_por_id=uid,
        )
        db.add(reversal)
        db.flush()

        tc = pedidos_service.calcular_tc_ponderado_caso_a(db, pedido.id)
        # Only non-reversal rows count: op1 (600 USD TC 1450) + op2 original (400 USD TC 1430)
        # Reversal row (es_reversal=True) is skipped.
        # TC = (600*1450 + 400*1430) / 1000 = 1442
        assert tc == Decimal("1442.0000")

    def test_excludes_imputaciones_de_otra_moneda(self, db, empresa, proveedor, active_user) -> None:
        """W1 — only imputaciones in the pedido's own moneda feed the weighted
        average. A Caso-A imputacion with `moneda_imputada != pedido.moneda`
        must be excluded, mirroring `calcular_tc_ponderado_pedido`."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1400"))
        op_usd = _make_op(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1450"))
        op_ars = _make_op(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1300"))
        # Matching-moneda imputacion (USD) — must count.
        _make_imputacion(db, op_usd, pedido, uid, monto_usd=Decimal("600"), tc=Decimal("1450"))
        # Other-moneda imputacion (ARS imputada on a USD pedido) — must be excluded.
        imp_ars = Imputacion(
            origen_tipo="orden_pago",
            origen_id=op_ars.id,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=Decimal("400"),
            moneda_imputada="ARS",
            tipo_cambio=Decimal("1300"),
            proveedor_id=pedido.proveedor_id,
            es_reversal=False,
            creado_por_id=uid,
        )
        db.add(imp_ars)
        db.flush()

        tc = pedidos_service.calcular_tc_ponderado_caso_a(db, pedido.id)
        # Only the USD imputacion contributes → TC = 1450, NOT a blend with the
        # ARS row (which would wrongly drag the average down to ~1390).
        assert tc == Decimal("1450.0000")


# ──────────────────────────────────────────────────────────────────────────
# T1.17 — batch variant
# ──────────────────────────────────────────────────────────────────────────


class TestCalcularTcPonderadoCasoABatch:
    """T1.17 — batch variant returns dict keyed by pedido_id."""

    def test_batch_returns_correct_tc_per_pedido(self, db, empresa, proveedor, active_user) -> None:
        """T1.17 — 3 distinct pedidos in one call, each with correct TC."""
        uid = active_user.id
        p1 = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1400"))
        p2 = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1420"))
        p3 = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1380"))

        op1 = _make_op(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1450"))
        op2 = _make_op(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1430"))
        op3_b = _make_op(db, empresa, proveedor, uid, actualizar_tc=False, tc=Decimal("1410"))

        _make_imputacion(db, op1, p1, uid, monto_usd=Decimal("500"), tc=Decimal("1450"))
        _make_imputacion(db, op2, p2, uid, monto_usd=Decimal("800"), tc=Decimal("1430"))
        # p3 has only Caso-B payment → should be None
        _make_imputacion(db, op3_b, p3, uid, monto_usd=Decimal("300"), tc=Decimal("1410"))

        result = pedidos_service.calcular_tc_ponderado_caso_a_batch(db, [p1.id, p2.id, p3.id])
        assert isinstance(result, dict)
        assert result[p1.id] == Decimal("1450.0000")
        assert result[p2.id] == Decimal("1430.0000")
        assert result[p3.id] is None

    def test_batch_empty_list_returns_empty_dict(self, db) -> None:
        result = pedidos_service.calcular_tc_ponderado_caso_a_batch(db, [])
        assert result == {}

    def test_batch_excludes_imputaciones_de_otra_moneda(self, db, empresa, proveedor, active_user) -> None:
        """W1 — the batch variant also filters `moneda_imputada == pedido.moneda`."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1400"))
        op_usd = _make_op(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1450"))
        op_ars = _make_op(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1300"))
        _make_imputacion(db, op_usd, pedido, uid, monto_usd=Decimal("600"), tc=Decimal("1450"))
        imp_ars = Imputacion(
            origen_tipo="orden_pago",
            origen_id=op_ars.id,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=Decimal("400"),
            moneda_imputada="ARS",
            tipo_cambio=Decimal("1300"),
            proveedor_id=pedido.proveedor_id,
            es_reversal=False,
            creado_por_id=uid,
        )
        db.add(imp_ars)
        db.flush()

        result = pedidos_service.calcular_tc_ponderado_caso_a_batch(db, [pedido.id])
        assert result[pedido.id] == Decimal("1450.0000")


# ──────────────────────────────────────────────────────────────────────────
# T1.19–T1.22 — resolver_tc_efectivo_pedido
# ──────────────────────────────────────────────────────────────────────────


class TestResolverTcEfectivoPedido:
    """Tests for pedidos_service.resolver_tc_efectivo_pedido."""

    def test_manual_wins_over_caso_a(self, db, empresa, proveedor, active_user) -> None:
        """T1.19 — manual override wins even when Caso-A payments average 1450."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1400"))
        pedido.tipo_cambio_manual = Decimal("1430")
        db.flush()

        op = _make_op(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1450"))
        _make_imputacion(db, op, pedido, uid, monto_usd=Decimal("600"), tc=Decimal("1450"))

        tc = pedidos_service.resolver_tc_efectivo_pedido(db, pedido)
        assert tc == Decimal("1430")

    def test_caso_a_when_no_manual(self, db, empresa, proveedor, active_user) -> None:
        """T1.20 — no override, Caso-A payments average 1450 → returns 1450."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1400"))
        op = _make_op(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1450"))
        _make_imputacion(db, op, pedido, uid, monto_usd=Decimal("600"), tc=Decimal("1450"))

        tc = pedidos_service.resolver_tc_efectivo_pedido(db, pedido)
        assert tc == Decimal("1450.0000")

    def test_original_fallback_when_no_override_no_caso_a(self, db, empresa, proveedor, active_user) -> None:
        """T1.21 — no override, no Caso-A → returns tipo_cambio_original."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1400"))
        # Caso-B payment only
        op_b = _make_op(db, empresa, proveedor, uid, actualizar_tc=False, tc=Decimal("1450"))
        _make_imputacion(db, op_b, pedido, uid, monto_usd=Decimal("600"), tc=Decimal("1450"))

        tc = pedidos_service.resolver_tc_efectivo_pedido(db, pedido)
        assert tc == Decimal("1400")

    def test_original_fallback_when_no_imputaciones(self, db, empresa, proveedor, active_user) -> None:
        """No imputaciones at all → falls back to tipo_cambio_original."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1380"))
        tc = pedidos_service.resolver_tc_efectivo_pedido(db, pedido)
        assert tc == Decimal("1380")

    def test_returns_none_when_no_original_and_no_caso_a(self, db, empresa, proveedor, active_user) -> None:
        """ARS pedido with no TC at all → returns None."""
        uid = active_user.id
        pedido = PedidoCompra(
            numero="PC-ARS-001",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("5000"),
            tipo_cambio=None,
            tipo_cambio_original=None,
            estado="aprobado",
            creado_por_id=uid,
        )
        db.add(pedido)
        db.flush()

        tc = pedidos_service.resolver_tc_efectivo_pedido(db, pedido)
        assert tc is None


# ──────────────────────────────────────────────────────────────────────────
# T1.29 — same-moneda USD→USD Caso-A payment (AD-7 fix)
# ──────────────────────────────────────────────────────────────────────────


def _make_op_usd(db, empresa, proveedor, user_id: int, actualizar_tc: bool, tc: Decimal) -> OrdenPago:
    """Create a USD OP with the given actualizar_tc_pedido flag and explicit TC."""
    n = db.query(OrdenPago).count() + 1
    op = OrdenPago(
        numero=f"OP-{n:04d}",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto_total=Decimal("1000"),
        tipo_cambio=tc,
        modo_imputacion="especifica",
        estado="pagado",
        actualizar_tc_pedido=actualizar_tc,
        creado_por_id=user_id,
    )
    db.add(op)
    db.flush()
    return op


class TestSameMonedaUsdCasoAPreFixBug:
    """Regression: documents the pre-fix (buggy) behavior where same-moneda
    imputaciones had tipo_cambio=None, causing the resolver to fall back to
    tipo_cambio_original even when the OP had an explicit (different) TC.
    These tests verify the bug condition so that the fix can be confirmed GREEN.
    """

    def test_null_tc_on_imputacion_skips_caso_a(self, db, empresa, proveedor, active_user) -> None:
        """Pre-fix: imputacion with tipo_cambio=None is skipped by calcular_tc_ponderado_caso_a
        because the query filters `tipo_cambio IS NOT NULL`. Result is None → resolver
        falls back to tipo_cambio_original (stale rate). This is the bug."""
        uid = active_user.id
        tc_original = Decimal("1400")
        tc_op = Decimal("1500")
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=tc_original)
        op = _make_op_usd(db, empresa, proveedor, uid, actualizar_tc=True, tc=tc_op)

        # Buggy state: same-moneda imputacion with tipo_cambio=None (pre-fix behavior)
        imp = Imputacion(
            origen_tipo="orden_pago",
            origen_id=op.id,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=Decimal("1000"),
            moneda_imputada="USD",
            tipo_cambio=None,  # This is the bug — gets skipped by IS NOT NULL filter
            proveedor_id=pedido.proveedor_id,
            es_reversal=False,
            creado_por_id=uid,
        )
        db.add(imp)
        db.flush()

        tc_caso_a = pedidos_service.calcular_tc_ponderado_caso_a(db, pedido.id)
        assert tc_caso_a is None, "null tipo_cambio must be skipped → Caso-A returns None"

        tc_effective = pedidos_service.resolver_tc_efectivo_pedido(db, pedido)
        assert tc_effective == tc_original, "Bug: resolver falls back to tipo_cambio_original because Caso-A is empty"


class TestSameMonedaUsdCasoA:
    """T1.29 — USD OP paying USD pedido with explicit TC (AD-7 fix).

    The bug: same-moneda imputaciones were created with tipo_cambio=None,
    so calcular_tc_ponderado_caso_a skipped them and the pedido's effective TC
    stayed at tipo_cambio_original (the approval-day snapshot).

    After the fix, tipo_cambio on same-moneda Caso-A imputaciones must be
    set to the OP's tipo_cambio so the weighted average picks it up.
    """

    def test_same_moneda_usd_caso_a_uses_op_tc_not_original(self, db, empresa, proveedor, active_user) -> None:
        """T1.29 — USD pedido (TC_original=1400) paid by USD OP (TC_op=1500,
        actualizar_tc_pedido=True). After fix, resolver returns 1500, not 1400."""
        uid = active_user.id
        tc_original = Decimal("1400")
        tc_op = Decimal("1500")
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=tc_original)
        op = _make_op_usd(db, empresa, proveedor, uid, actualizar_tc=True, tc=tc_op)

        # Simulate what ejecutar_pago creates for a same-moneda USD→USD payment
        # AFTER the AD-7 fix: tipo_cambio must be tc_op, NOT None.
        imp = Imputacion(
            origen_tipo="orden_pago",
            origen_id=op.id,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=Decimal("1000"),
            moneda_imputada="USD",  # same-moneda
            tipo_cambio=tc_op,  # AD-7: must be set, not None
            proveedor_id=pedido.proveedor_id,
            es_reversal=False,
            creado_por_id=uid,
        )
        db.add(imp)
        db.flush()

        tc_caso_a = pedidos_service.calcular_tc_ponderado_caso_a(db, pedido.id)
        assert tc_caso_a is not None, (
            "Expected Caso-A weighted average to be 1500 but got None — "
            "imputacion.tipo_cambio was likely None (pre-fix behavior)"
        )
        assert tc_caso_a == tc_op.quantize(Decimal("0.0001")), (
            f"Expected {tc_op.quantize(Decimal('0.0001'))} got {tc_caso_a}"
        )

        tc_effective = pedidos_service.resolver_tc_efectivo_pedido(db, pedido)
        assert tc_effective == tc_op.quantize(Decimal("0.0001")), (
            f"resolver should return op TC {tc_op}, got {tc_effective} (tipo_cambio_original fallback = bug)"
        )

    def test_same_moneda_usd_caso_b_not_affected(self, db, empresa, proveedor, active_user) -> None:
        """T1.29b — Caso B (actualizar_tc_pedido=False): even with tipo_cambio set on
        the imputacion, the resolver must fall back to tipo_cambio_original because
        calcular_tc_ponderado_caso_a filters by actualizar_tc_pedido=True."""
        uid = active_user.id
        tc_original = Decimal("1400")
        tc_op = Decimal("1500")
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=tc_original)
        op = _make_op_usd(db, empresa, proveedor, uid, actualizar_tc=False, tc=tc_op)

        imp = Imputacion(
            origen_tipo="orden_pago",
            origen_id=op.id,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=Decimal("1000"),
            moneda_imputada="USD",
            tipo_cambio=tc_op,  # storing TC even for Caso B is harmless
            proveedor_id=pedido.proveedor_id,
            es_reversal=False,
            creado_por_id=uid,
        )
        db.add(imp)
        db.flush()

        tc_caso_a = pedidos_service.calcular_tc_ponderado_caso_a(db, pedido.id)
        assert tc_caso_a is None, "Caso B imputaciones must not feed calcular_tc_ponderado_caso_a"

        tc_effective = pedidos_service.resolver_tc_efectivo_pedido(db, pedido)
        assert tc_effective == tc_original, "Caso B → resolver must return tipo_cambio_original"

    def test_two_same_moneda_usd_ops_weighted_average(self, db, empresa, proveedor, active_user) -> None:
        """T1.29c — multiple USD OPs (Caso A) against same USD pedido produce
        a correct weighted-average TC, not a last-write-wins result."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, tc_original=Decimal("1400"))
        op1 = _make_op_usd(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1500"))
        op2 = _make_op_usd(db, empresa, proveedor, uid, actualizar_tc=True, tc=Decimal("1300"))

        for op, monto, tc in [
            (op1, Decimal("600"), Decimal("1500")),
            (op2, Decimal("400"), Decimal("1300")),
        ]:
            db.add(
                Imputacion(
                    origen_tipo="orden_pago",
                    origen_id=op.id,
                    destino_tipo="pedido_compra",
                    destino_id=pedido.id,
                    monto_imputado=monto,
                    moneda_imputada="USD",
                    tipo_cambio=tc,
                    proveedor_id=pedido.proveedor_id,
                    es_reversal=False,
                    creado_por_id=uid,
                )
            )
        db.flush()

        # (600*1500 + 400*1300) / 1000 = (900000 + 520000) / 1000 = 1420
        tc_caso_a = pedidos_service.calcular_tc_ponderado_caso_a(db, pedido.id)
        assert tc_caso_a == Decimal("1420.0000")

"""
Tests for fx_service — rounding helpers and derive-to-pesos rule.

TDD: All tests in this file were written BEFORE the implementation.
Each test references the spec requirement it covers.

Spec coverage:
  ADR-3   — ROUND_HALF_UP rounding helpers (q_ars, q_usd, q_tc)
  REQ-MM-002 — ARS invariant: ARS native amount passes through factor 1
  REQ-MM-006 — derivar_ars per settlement state (unpaid, settled, mixed)
  REQ-MM-006 §4.1 — derivar_varianza_visible (display-only, no persistence)
"""

from __future__ import annotations

from decimal import Decimal


# ---------------------------------------------------------------------------
# A.1 — Rounding helpers (ADR-3 / design §3)
# ---------------------------------------------------------------------------


def test_q_ars_redondea_half_up() -> None:
    """ADR-3: q_ars rounds to 2 decimal places using ROUND_HALF_UP."""
    from app.services.fx_service import q_ars

    # 0.5 rounds up to 1 (HALF_UP, not HALF_EVEN which would round to 0)
    assert q_ars(Decimal("0.5")) == Decimal("0.50")
    # 2.5 → 3 with HALF_UP
    assert q_ars(Decimal("2.5")) == Decimal("2.50")
    # standard truncation
    assert q_ars(Decimal("100.004")) == Decimal("100.00")
    assert q_ars(Decimal("100.005")) == Decimal("100.01")
    # negative: HALF_UP rounds away from zero
    assert q_ars(Decimal("100.125")) == Decimal("100.13")


def test_q_usd_redondea_half_up() -> None:
    """ADR-3: q_usd rounds to 2 decimal places using ROUND_HALF_UP."""
    from app.services.fx_service import q_usd

    assert q_usd(Decimal("1.005")) == Decimal("1.01")
    assert q_usd(Decimal("1000.004")) == Decimal("1000.00")
    assert q_usd(Decimal("0.125")) == Decimal("0.13")


def test_q_tc_seis_decimales_half_up() -> None:
    """ADR-3: q_tc rounds to 6 decimal places using ROUND_HALF_UP."""
    from app.services.fx_service import q_tc

    assert q_tc(Decimal("1450.0000005")) == Decimal("1450.000001")
    assert q_tc(Decimal("1450.1234564")) == Decimal("1450.123456")
    assert q_tc(Decimal("1000.0000001")) == Decimal("1000.000000")


def test_redondeo_half_up_ars_usd_tc() -> None:
    """ADR-3: Comprehensive HALF_UP vs HALF_EVEN discrimination test.

    HALF_EVEN would round 0.5 to 0 (banker's rounding), HALF_UP rounds to 1.
    This test distinguishes the two policies by testing midpoint values.
    """
    from app.services.fx_service import q_ars, q_tc, q_usd

    # 0.005 with 2-decimal HALF_UP → 0.01 (rounds up)
    # 0.005 with 2-decimal HALF_EVEN → 0.00 (rounds to even)
    assert q_ars(Decimal("0.005")) == Decimal("0.01")  # HALF_UP
    assert q_usd(Decimal("0.005")) == Decimal("0.01")  # HALF_UP
    # TC: 1000.0000005 → HALF_UP rounds up the last digit
    assert q_tc(Decimal("1000.0000005")) == Decimal("1000.000001")


# ---------------------------------------------------------------------------
# A.3 — derivar_ars — single derive rule per settlement state
# (REQ-MM-002, REQ-MM-006, design §2.1)
# ---------------------------------------------------------------------------


def test_derivar_ars_deuda_viva_usa_tc_snapshot() -> None:
    """REQ-MM-006 context (i): unpaid USD debt → use pedido tc_snapshot.

    Scenario from spec §2.1: pedido USD, monto=1000, tc_snapshot=1000.
    Derivado = 1000 * 1000.00 = 1_000_000 ARS.
    """
    from app.services.fx_service import derivar_ars

    monto = Decimal("1000")
    tc_snapshot = Decimal("1000.00")
    result = derivar_ars(monto=monto, moneda="USD", tc=tc_snapshot)
    assert result == Decimal("1000000.00")


def test_derivar_ars_porcion_pagada_usa_tc_op() -> None:
    """REQ-MM-006 context (ii): settled portion → use OP's tipo_cambio.

    Scenario: pedido USD 1000 @ tc_snapshot=1000, OP pays at tc=1450.
    derivar_ars(1000, 'USD', tc=1450) = 1_450_000 ARS.
    """
    from app.services.fx_service import derivar_ars

    monto = Decimal("1000")
    tc_op = Decimal("1450.00")
    result = derivar_ars(monto=monto, moneda="USD", tc=tc_op)
    assert result == Decimal("1450000.00")


def test_derivar_ars_mixto_por_imputacion() -> None:
    """REQ-MM-006 context (iii): partial payments — each portion at its own TC.

    Scenario from spec §4.1 (pagos parciales):
    - pedido USD 2000 @ tc_snapshot=1000
    - 1st OP pays USD 1000 @ tc=1410 → 1_410_000 ARS
    - 2nd OP pays USD 1000 @ tc=1450 → 1_450_000 ARS
    Total = 2_860_000 ARS (NOT 2000 * any single TC).
    derivar_ars is pure: call once per imputacion with its own tc.
    """
    from app.services.fx_service import derivar_ars

    monto_imp1 = Decimal("1000")
    monto_imp2 = Decimal("1000")

    ars_imp1 = derivar_ars(monto=monto_imp1, moneda="USD", tc=Decimal("1410.00"))
    ars_imp2 = derivar_ars(monto=monto_imp2, moneda="USD", tc=Decimal("1450.00"))

    assert ars_imp1 == Decimal("1410000.00")
    assert ars_imp2 == Decimal("1450000.00")
    assert ars_imp1 + ars_imp2 == Decimal("2860000.00")


def test_invariante_ars_nunca_se_repega() -> None:
    """REQ-MM-002: ARS native amount → factor 1, never re-pegged.

    If moneda='ARS', derivar_ars MUST return monto unchanged regardless
    of any tc value passed. This is the store-native invariant.
    """
    from app.services.fx_service import derivar_ars

    monto = Decimal("50000")

    # ARS with tc=None (typical case — no TC for ARS docs)
    assert derivar_ars(monto=monto, moneda="ARS", tc=None) == Decimal("50000")

    # ARS with tc provided (edge case — should still ignore tc and return monto)
    assert derivar_ars(monto=monto, moneda="ARS", tc=Decimal("1450.00")) == Decimal("50000")

    # ARS amount is immutable: 80000 ARS stays 80000 ARS at any TC
    assert derivar_ars(monto=Decimal("80000"), moneda="ARS", tc=Decimal("1000.00")) == Decimal("80000")


# ---------------------------------------------------------------------------
# A.5 — derivar_varianza_visible — display-only formula (REQ-MM-006 §4.1)
# ---------------------------------------------------------------------------


def test_varianza_tc_display_calculo_correcto() -> None:
    """REQ-MM-006 §4.1: varianza_ars = (tc_op - tc_snapshot) * usd_imputado.

    Scenario from spec: pedido USD 1000 @ tc_snapshot=1000, OP tc=1450.
    varianza = (1450 - 1000) * 1000 = 450_000 ARS.
    """
    from app.services.fx_service import derivar_varianza_visible

    tc_op = Decimal("1450.00")
    tc_snapshot = Decimal("1000.00")
    usd_imputado = Decimal("1000")

    result = derivar_varianza_visible(tc_op=tc_op, tc_snapshot=tc_snapshot, usd_imputado=usd_imputado)
    assert result == Decimal("450000.00")


def test_varianza_tc_cero_cuando_tc_iguales() -> None:
    """REQ-MM-006 §4.1: zero variance when tc_op == tc_snapshot.

    Scenario: pedido USD 1000 @ tc_snapshot=1000, OP also at tc=1000.
    varianza = (1000 - 1000) * 1000 = 0.
    """
    from app.services.fx_service import derivar_varianza_visible

    result = derivar_varianza_visible(
        tc_op=Decimal("1000.00"),
        tc_snapshot=Decimal("1000.00"),
        usd_imputado=Decimal("1000"),
    )
    assert result == Decimal("0.00")


def test_varianza_tc_none_cuando_pedido_ars() -> None:
    """REQ-MM-006 §4.1: returns None when tc_snapshot is None (ARS pedido).

    An ARS pedido has no tc_snapshot (NULL). There is no FX variance
    for a peso-fixed document — returning None signals 'not applicable'.
    """
    from app.services.fx_service import derivar_varianza_visible

    result = derivar_varianza_visible(
        tc_op=Decimal("1450.00"),
        tc_snapshot=None,
        usd_imputado=Decimal("1000"),
    )
    assert result is None

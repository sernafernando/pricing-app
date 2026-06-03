"""
fx_service — Currency derivation primitives for the Compras module.

Implements the single derive-to-pesos rule (ADR-2 / design §2) and
centralized ROUND_HALF_UP helpers (ADR-3 / design §3).

All functions are pure (no DB side-effects) so they are unit-testable
in isolation.

Covered requirements:
  REQ-MM-002 — ARS invariant: ARS native amount passes through unchanged.
  REQ-MM-006 — derivar_ars per settlement state.
  REQ-MM-006 §4.1 — derivar_varianza_visible (display-only).
  ADR-3 — ROUND_HALF_UP centralized helpers.
  ADR-7 — fx_service as dedicated module (not inflating cc_proveedor_service).
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rounding precision constants (ADR-3 / design §3)
# ---------------------------------------------------------------------------

_PRECISION_ARS = Decimal("0.01")  # 2 decimal places
_PRECISION_USD = Decimal("0.01")  # 2 decimal places
_PRECISION_TC = Decimal("0.000001")  # 6 decimal places


# ---------------------------------------------------------------------------
# Public rounding helpers
# ---------------------------------------------------------------------------


def q_ars(x: Decimal) -> Decimal:
    """Round ARS amount to 2 decimal places using ROUND_HALF_UP.

    Centralized helper — all ARS derivations in the module MUST go through
    this function (ADR-3).
    """
    return x.quantize(_PRECISION_ARS, rounding=ROUND_HALF_UP)


def q_usd(x: Decimal) -> Decimal:
    """Round USD amount to 2 decimal places using ROUND_HALF_UP.

    Centralized helper — all USD amounts in the module MUST go through
    this function (ADR-3).
    """
    return x.quantize(_PRECISION_USD, rounding=ROUND_HALF_UP)


def q_tc(x: Decimal) -> Decimal:
    """Round a TC (tipo de cambio) to 6 decimal places using ROUND_HALF_UP.

    Centralized helper — TC values MUST go through this function to avoid
    silent precision drift (ADR-3).
    """
    return x.quantize(_PRECISION_TC, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Single derive-to-pesos rule (ADR-2 / design §2)
# ---------------------------------------------------------------------------


def derivar_ars(
    monto: Decimal,
    moneda: str,
    tc: Optional[Decimal],
) -> Decimal:
    """Derive the ARS equivalent of a native amount using the single rule.

    Rule (design §2.1 — ADR-2):
      - moneda == 'ARS': return monto unchanged (REQ-MM-002 invariant).
        The ARS nominal is FIXED; it is never re-pegged by any TC.
      - moneda == 'USD': return q_ars(monto * tc).
        The caller is responsible for passing the correct TC per context:
          (i)  Unpaid debt → pedido.tc_snapshot
          (ii) Settled portion → OP.tipo_cambio (imp.tipo_cambio)
          (iii) Mixed/partial → call once per imputacion with its own TC

    Args:
        monto: Native amount in the document's own currency.
        moneda: 'ARS' or 'USD' (the document's native currency).
        tc: Tipo de cambio (ARS per 1 USD). Must be not-None when moneda='USD'.

    Returns:
        ARS equivalent, rounded with q_ars.

    Raises:
        ValueError: if moneda='USD' and tc is None.
    """
    if moneda == "ARS":
        # REQ-MM-002: ARS nominal fixed — never re-peg regardless of tc value.
        return monto

    if moneda == "USD":
        if tc is None:
            raise ValueError("derivar_ars: tc es requerido para montos USD (REQ-MM-002 / design §2)")
        return q_ars(monto * tc)

    # Unknown currency — log a warning and pass through unchanged
    logger.warning(
        "⚠️ derivar_ars: moneda desconocida '%s', devolviendo monto sin conversión",
        moneda,
    )
    return monto


# ---------------------------------------------------------------------------
# Variance visibility helper (REQ-MM-006 §4.1 / design §4.1)
# ---------------------------------------------------------------------------


def derivar_varianza_visible(
    tc_op: Optional[Decimal],
    tc_snapshot: Optional[Decimal],
    usd_imputado: Decimal,
) -> Optional[Decimal]:
    """Compute the display-only TC variance for a cross-moneda imputacion.

    Formula (design §4.1):
        varianza_ars = (tc_op - tc_pedido_snapshot) * usd_imputado

    This is PURE (no DB side-effects) and must NOT be persisted.
    It is included in API responses as a nullable field `varianza_tc_ars`.

    Args:
        tc_op: TC of the OP that settled the debt (imp.tipo_cambio).
        tc_snapshot: TC at the time the pedido was created (pedido.tc_snapshot).
                     None for ARS pedidos → returns None (not applicable).
        usd_imputado: USD amount that was imputated (imp.monto_imputado).

    Returns:
        ARS variance (can be negative), rounded with q_ars.
        None if tc_snapshot is None (ARS pedido — no FX variance applies).
    """
    if tc_snapshot is None:
        # REQ-MM-002: ARS document has no tc_snapshot → variance not applicable.
        return None

    if tc_op is None:
        # No liquidation TC → variance cannot be computed.
        return None

    varianza = (tc_op - tc_snapshot) * usd_imputado
    return q_ars(varianza)

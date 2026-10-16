"""In-memory result of the single Gauss-metrics producer (design D2, D7).

`OrderMetrics` mirrors every `ml_order_metrics` column plus `lineas` (the
Total Gauss deduction chain lines, persisted separately into
`ml_venta_deducciones` by `store.recompute_order_metrics`, never a column of
this table -- design D2's "Chain lines stay in `ml_venta_deducciones`").

`GaussStatus` is the CHECK-constrained value of `ml_order_metrics.gauss_status`.
`__post_init__` enforces the two invariants the module docstring of
`deducciones.py` already lives by, now at the boundary of the shared type
instead of only inside `calcular_total_gauss`'s own logic:

- `unresolved` is the ONLY status allowed to carry `total_gauss=None`; every
  other status requires a real number (design D2: "Unresolved is NULL +
  status, never 0"). `unresolved` also forces `markup_pct=None` -- a markup
  computed off nothing is not a real number either.
- `markup_pct` is `None` whenever `costo_mercaderia` is `None` or exactly
  zero, REGARDLESS of status -- a percentage against an unknown or zero
  denominator is a lie, never a fabricated `0%` (deducciones.py's own
  `calcular_total_gauss` rule, ~562-571).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Tuple


class GaussStatus(str, enum.Enum):
    """`ml_order_metrics.gauss_status` CHECK-constrained values (design D2)."""

    OK = "ok"
    PROVISIONAL = "provisional"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class OrderMetrics:
    """One order's computed Gauss metrics -- the return value of
    `compute.compute_order_metrics`, consumed by `store.recompute_order_metrics`."""

    order_id: int
    neto: Optional[Decimal]
    neto_sin_iva: Optional[Decimal]
    iva_reconcilia: Optional[bool]
    costo_mercaderia: Optional[Decimal]
    total_gauss: Optional[Decimal]
    markup_pct: Optional[Decimal]
    gauss_status: GaussStatus
    provisional_falta: Optional[str]
    unresolved_reason: Optional[str]
    formula_version: int
    computed_at: datetime
    # `(code, monto, concepto)` -- verbatim `TotalGaussResultado.lineas`
    # shape (deducciones.py), NOT a column of `ml_order_metrics`.
    lineas: List[Tuple[str, Optional[Decimal], Optional[str]]] = field(default_factory=list)
    # TP-Link figures (metricas-ml-tplink-mode P3). Defaulted so a caller
    # that predates them still builds a valid (TP-unknown) result.
    costo_tp: Optional[Decimal] = None
    total_tp: Optional[Decimal] = None
    markup_tp: Optional[Decimal] = None
    tp_incompleto: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.gauss_status == GaussStatus.UNRESOLVED:
            if self.total_gauss is not None:
                raise ValueError("gauss_status=unresolved requires total_gauss=None")
            if self.markup_pct is not None:
                raise ValueError("gauss_status=unresolved requires markup_pct=None")
        elif self.total_gauss is None:
            raise ValueError(f"gauss_status={self.gauss_status.value} requires a non-None total_gauss")

        if self.markup_pct is not None and (self.costo_mercaderia is None or self.costo_mercaderia == 0):
            raise ValueError("markup_pct must be None when costo_mercaderia is None or zero")

        # TP: an incomplete order carries no TP figure; a Total TP needs a
        # Total Gauss and a TP cost; a markup needs a non-zero TP cost.
        if self.tp_incompleto and (self.costo_tp, self.total_tp, self.markup_tp) != (None, None, None):
            raise ValueError("tp_incompleto requires costo_tp, total_tp and markup_tp to be None")
        if self.total_tp is not None and (self.total_gauss is None or self.costo_tp is None):
            raise ValueError("total_tp requires a total_gauss and a costo_tp")
        if self.markup_tp is not None and (self.total_tp is None or not self.costo_tp):
            raise ValueError("markup_tp requires a total_tp and a non-zero costo_tp")

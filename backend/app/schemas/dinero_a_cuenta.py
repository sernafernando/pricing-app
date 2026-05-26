"""
Schemas Pydantic v2 para dinero_a_cuenta y saldo-a-favor breakdown.

References:
  - design §2.1, §2.2, AD-8
  - tasks T2.5
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DineroACuentaResponse(BaseModel):
    """Response schema para una fila de dinero_a_cuenta (GET §2.1)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    proveedor_id: int
    empresa_id: int
    monto: Decimal = Field(description="Monto original creado. Inmutable.")
    moneda: str = Field(description="'ARS' o 'USD'")
    saldo_disponible: Decimal = Field(description="Saldo consumible derivado de imputaciones (AD-3).")
    estado: str = Field(description="'disponible' | 'consumido_parcial' | 'consumido'")
    origen_op_id: int = Field(description="ID de la OP que generó este dinero a cuenta.")
    origen_op_numero: Optional[str] = Field(
        default=None,
        description="Número legible de la OP de origen.",
    )
    created_at: datetime


class SaldoComponentePorMoneda(BaseModel):
    """Breakdown del saldo a favor para una moneda específica."""

    moneda: str
    saldo_a_favor_total: Decimal = Field(
        description=(
            "Magnitud del saldo a favor del CC en esta moneda. "
            "POSITIVO = cuánto le debemos al proveedor. CERO si el proveedor tiene deuda. Nunca negativo."
        )
    )
    componente_dinero_a_cuenta: Decimal = Field(description="Porción real-money (overpay trackeable, disponible).")
    componente_nc: Decimal = Field(description="Porción documental (NC crédito pendiente de aplicar).")


class SaldoAFavorBreakdown(BaseModel):
    """
    Breakdown del saldo a favor del CC de un proveedor (GET §2.2).

    El total = componente_dinero_a_cuenta + componente_nc + resto (saldo
    de otros orígenes como imputaciones legacy destino='saldo').
    AD-8: todo derivado, sin columnas extra en cc_proveedor_movimientos.
    """

    model_config = ConfigDict(from_attributes=True)

    proveedor_id: int

    # ARS como moneda principal de display
    saldo_a_favor_total_ars: Decimal = Field(
        description=(
            "Magnitud del saldo a favor total del CC en ARS. "
            "POSITIVO = cuánto le debemos al proveedor (a su favor). "
            "CERO cuando el proveedor tiene deuda neta con nosotros. "
            "Nunca negativo. Misma escala que componente_dinero_a_cuenta_ars y componente_nc_ars."
        )
    )
    componente_dinero_a_cuenta_ars: Decimal = Field(description="Real-money disponible (overpay ARS).")
    componente_nc_ars: Decimal = Field(description="Crédito documental ARS pendiente (NC locales + ERP).")

    # Breakdown completo por moneda (incluye USD si aplica)
    por_moneda: dict[str, SaldoComponentePorMoneda] = Field(
        default_factory=dict,
        description="Breakdown per-moneda para multi-moneda support.",
    )

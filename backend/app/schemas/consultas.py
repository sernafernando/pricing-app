"""
Pydantic v2 schemas for the Consultas module — ranking endpoint.

REQ-01: Ranking rows contain item_id, codigo, descripcion, marca, categoria,
pm (nullable), calculated_ageing_days (nullable), erp_ageing (nullable),
last_purchase_date (nullable), last_purchase_qty (nullable),
stock_valuation_ars (nullable), potential_revenue_ars (nullable), total_stock.

REQ-04: Dynamic sort via sort_by / sort_dir; unknown sort_by → 422.
REQ-05: Pagination page / page_size (1-200).
REQ-03: Filters: marca, categoria, pm, stor_ids.
ADR-4: ventana_dias in {30, 60, 90, 180}.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Allowed values
# ---------------------------------------------------------------------------

VENTANA_DIAS_PERMITIDAS: frozenset[int] = frozenset({30, 60, 90, 180})

SORT_COLUMNS_PERMITIDAS: frozenset[str] = frozenset(
    {
        "dias_sin_venta",
        "unidades_vendidas_ventana",
        "total_stock",
        "valor_costo",
        "valor_venta",
        "last_purchase_date",
        "codigo",
        "descripcion",
        "marca",
        "categoria",
    }
)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class RankingItemRow(BaseModel):
    """Single row in the ranking response."""

    item_id: int
    codigo: str
    descripcion: str
    marca: Optional[str]
    categoria: Optional[str]
    pm: Optional[str] = Field(default=None, description="Nombre del PM (nullable)")

    # Ageing
    dias_sin_venta: Optional[int] = Field(
        default=None,
        description="Días desde la última venta calculados por la app. Null si nunca vendió.",
    )
    erp_ageing_dias: Optional[int] = Field(
        default=None,
        description="Días de ageing según el ERP (sync periódico). Null hasta que se sincronice.",
    )

    # Purchase
    last_purchase_date: Optional[date] = None
    last_purchase_qty: Optional[int] = None

    # Stock and valuation
    total_stock: int = Field(default=0)
    valor_costo: Optional[float] = Field(
        default=None,
        description="total_stock × costo convertido a ARS. Null si no hay TC disponible.",
    )
    valor_venta: Optional[float] = Field(
        default=None,
        description="total_stock × precio lista clasica (prli_id=4). Null si no hay precio.",
    )

    # Sales velocity
    unidades_vendidas_ventana: int = Field(
        default=0,
        description="Unidades vendidas en la ventana seleccionada.",
    )

    # Currency metadata (badge/tooltip — never used for arithmetic)
    moneda_costo: Optional[str] = Field(default=None, description="ARS o USD")

    model_config = ConfigDict(from_attributes=True)


class RankingResponse(BaseModel):
    """Paginated ranking response envelope."""

    items: list[RankingItemRow]
    total: int = Field(description="Total de filas sin paginar")
    page: int
    page_size: int

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Facets schemas
# ---------------------------------------------------------------------------


class DepositoFacet(BaseModel):
    """Single depósito option for the facets dropdown."""

    id: int
    label: str

    model_config = ConfigDict(from_attributes=True)


class RankingFacetsResponse(BaseModel):
    """Facets response for ranking filter dropdowns.

    All lists are sorted ascending. marcas and categorias are filtered to
    activo=TRUE products only. pms correspond to the exact display name
    produced by the ranking endpoint (usuarios.nombre). depositos include
    only stor_ids present in tb_item_storage.
    """

    marcas: list[str]
    categorias: list[str]
    pms: list[str]
    depositos: list[DepositoFacet]

    model_config = ConfigDict(from_attributes=True)

"""Costo SI read API (sell-in-costo-si T2, S13 consumers come in T3).

`GET /api/costo-si/{item_id}`: the costo SI (moving weighted average by sell in, USD, 5 decimals) in force on `fecha`
(default today) and the product's whole breakdown, one step per purchase invoice. A combo answers its components'.
Needs `sell_in.ver`, the permission that already shows sell-in costs.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.services.costo_si import lectura
from app.services.ml_daily_metrics import board

router = APIRouter(prefix="/costo-si", tags=["costo-si"], dependencies=[Depends(require_permiso("sell_in.ver"))])


class SellInOut(BaseModel):
    origen: str
    ref: int
    porcentaje: Decimal


class PasoOut(BaseModel):
    orden: int
    tipo: str
    fecha: date
    ct_transaction: Optional[int]
    cantidad: int
    costo_neto_usd: Optional[Decimal]
    sell_ins: List[SellInOut]
    sell_in_pct: Decimal
    costo_neto_neto_usd: Optional[Decimal]
    stock_antes: int
    stock_base: int
    stock_despues: int
    promedio_usd: Optional[Decimal]
    tipo_cambio: Optional[Decimal]
    fuente_tc: Optional[str]
    en_compras: bool
    moneda: str  # the currency the step's amounts are in: the product's cost currency (L18)


class ComponenteOut(BaseModel):
    item_id: int
    cantidad: Decimal
    costo_si_usd: Optional[Decimal]
    moneda: Optional[str]


class CostoSiOut(BaseModel):
    item_id: int
    fecha: date
    es_combo: bool
    costo_si_usd: Optional[Decimal]  # in `costo_si_moneda` (the name predates L18)
    costo_si_moneda: Optional[str]
    vigente_desde: Optional[date]
    pasos: List[PasoOut]
    componentes: List[ComponenteOut]


@router.get("/{item_id}", response_model=CostoSiOut)
def costo_si(
    item_id: int,
    fecha: Optional[date] = Query(None, description="Date the value is in force on (default: today)"),
    db: Session = Depends(get_db),
) -> CostoSiOut:
    """The product's costo SI on `fecha` and its breakdown (net, each sell in %, net-net, stock before, average
    after). `costo_si_usd` is null when no sell in ever applied to the product."""
    found = lectura.leer(db, item_id, fecha or board.today_business())
    return CostoSiOut(
        item_id=found.item_id,
        fecha=found.fecha,
        es_combo=found.es_combo,
        costo_si_usd=found.costo_si_usd,
        costo_si_moneda=found.moneda,
        vigente_desde=found.vigente_desde,
        pasos=[PasoOut(**p) for p in found.pasos],
        componentes=[ComponenteOut(**vars(c)) for c in found.componentes],
    )

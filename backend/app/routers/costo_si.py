"""Costo SI read API (sell-in-costo-si T2, S13 consumers come in T3).

`GET /api/costo-si/{item_id}`: the costo SI (moving weighted average by sell in, USD, 5 decimals) in force on `fecha`
(default today) and the product's whole breakdown, one step per purchase invoice. A combo answers its components'.
Needs `sell_in.ver`, the permission that already shows sell-in costs.

Suspicious purchases (owner L29): `GET /api/costo-si/sospechosas` lists the purchases held out of the average for a
price below 1/10 or above 10x the costo SI right before them, `GET /api/costo-si/sospechosas/resumen` counts the
pending ones, and `POST /api/costo-si/sospechosas/{id}/aceptar` / `.../excluir` record a reviewer's decision, which
also needs `costo_si.revisar`. Accepting lets the purchase into the average: the product is recomputed from the
invoice date (backups, and everything that follows a costo SI change).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permiso
from app.core.database import get_db
from app.core.exceptions import ErrorCode, api_error
from app.models.usuario import Usuario
from app.services.costo_si import lectura, sospechas
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


class SospechosaOut(BaseModel):
    id: int
    item_id: int
    codigo: Optional[str]
    descripcion: Optional[str]
    ct_transaction: int
    factura: Optional[str]  # the invoice number
    fecha: date
    cantidad: int
    precio: Decimal  # net unit price in `moneda`, before sell ins
    moneda: str
    precio_factura: Decimal  # the unit price as loaded on the invoice, in `moneda_factura`
    moneda_factura: str
    tipo_cambio: Optional[Decimal]  # the rate it was converted at; None when the invoice is in `moneda`
    referencia: Decimal  # the cost it was checked against
    fuente_ref: str  # 'costo_si' | 'lista'
    ratio: Decimal  # precio / referencia
    estado: str  # 'pendiente' | 'aceptada' | 'excluida'
    detectada_at: datetime
    revisado_por: Optional[int]
    revisor: Optional[str]
    revisado_at: Optional[datetime]
    nota: Optional[str]


class SospechasResumenOut(BaseModel):
    pendientes: int


class DecisionIn(BaseModel):
    precio: Decimal = Field(description="The price the reviewer saw: a row whose price changed since is refused (409)")
    nota: Optional[str] = Field(None, max_length=500)


@router.get("/sospechosas", response_model=List[SospechosaOut])
def listar_sospechosas(
    estado: Optional[str] = Query(None, pattern="^(pendiente|aceptada|excluida)$"),
    item_id: Optional[int] = Query(None),
    desde: Optional[date] = Query(None, description="Invoices from this date on"),
    db: Session = Depends(get_db),
) -> List[SospechosaOut]:
    """The purchases held out of costo SI (or accepted) for a suspicious price, newest invoice first."""
    return [SospechosaOut(**f) for f in sospechas.listar(db, estado, item_id, desde)]


@router.get("/sospechosas/resumen", response_model=SospechasResumenOut)
def resumen_sospechosas(db: Session = Depends(get_db)) -> SospechasResumenOut:
    """How many suspicious purchases wait for a review (the tab's badge)."""
    return SospechasResumenOut(pendientes=sospechas.pendientes(db))


def _decidir(db: Session, sospecha_id: int, decision: str, body: DecisionIn, usuario: Usuario) -> SospechosaOut:
    try:
        fila = sospechas.decidir(db, sospecha_id, decision, usuario.id, body.precio, body.nota)
    except sospechas.PrecioCambiado:
        db.rollback()
        raise api_error(
            409,
            ErrorCode.CONFLICT,
            "La compra cambió desde que se cargó la lista (factura corregida). Recargue la lista.",
        )
    if fila is None:
        db.rollback()
        raise api_error(404, ErrorCode.NOT_FOUND, "Compra sospechosa no encontrada")
    db.commit()
    return SospechosaOut(**fila)


@router.post(
    "/sospechosas/{sospecha_id}/aceptar",
    response_model=SospechosaOut,
    dependencies=[Depends(require_permiso(sospechas.PERMISO_REVISAR))],
)
def aceptar_sospechosa(
    sospecha_id: int,
    body: DecisionIn,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> SospechosaOut:
    """The purchase enters the average: its product is requeued and recomputed from the invoice date (L15)."""
    return _decidir(db, sospecha_id, sospechas.ACEPTADA, body, current_user)


@router.post(
    "/sospechosas/{sospecha_id}/excluir",
    response_model=SospechosaOut,
    dependencies=[Depends(require_permiso(sospechas.PERMISO_REVISAR))],
)
def excluir_sospechosa(
    sospecha_id: int,
    body: DecisionIn,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> SospechosaOut:
    """The purchase stays out of the average (a decision on record; a corrected invoice is reviewed again)."""
    return _decidir(db, sospecha_id, sospechas.EXCLUIDA, body, current_user)


@router.get("/{item_id}", response_model=CostoSiOut)
def costo_si(
    item_id: int,
    fecha: Optional[date] = Query(None, description="Date the value is in force on (default: today)"),
    db: Session = Depends(get_db),
) -> CostoSiOut:
    """The product's costo SI on `fecha` and its breakdown (net, each sell in %, net-net, stock before, average
    after). `costo_si_usd` is null before the product's start (its first sell in, or 2026-11-01 without one: L21),
    for a combo, or without a start cost and a purchase since."""
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

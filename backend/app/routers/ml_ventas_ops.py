"""Router: ML operations sale-centric view (slice 4 of
ml-ventas-fuente-de-verdad).

Design D4: one storage layer, two read surfaces. This router is the
sale-centric one -- order + items + shipment + linked claim + linked
questions/messages, resolved through `ml_operation_links`. The existing
`ml_bot` router (bot-centric, keyed on question/message) is UNCHANGED by
this module; see `tests/integration/test_ml_ventas_ops_router.py` for the
regression proof.

Gated by:
- `ml_ops.ver` permission (no permission -> 403), checked FIRST.
- `ML_ORDERS_OPS_ENABLED` (flag OFF -> 503, spec: inert by default), checked
  only once permission is confirmed.

Permission is intentionally checked before the flag (same precedent/
rationale as `pxq.py`'s `_SYNC_STATUS_TO_HTTP` comment): a user WITHOUT
permission must always get 403 regardless of flag state, or the response
would leak whether the feature exists/is enabled to someone who cannot use
it either way. 503 then unambiguously means "you can use this, but it's
switched off right now" for a user who already cleared the permission gate.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.constants import BUSINESS_TIMEZONE
from app.core.database import get_db
from app.models.ml_bot_message import MlBotMessage
from app.models.ml_bot_question import MlBotQuestion
from app.models.ml_orders_ops import (
    COST_SYNC_FIELD_PREFIX,
    COST_SYNC_KIND,
    COST_SYNC_SENTINEL_ORDER_ID,
    INGEST_FAILED_KIND,
    UNENUMERABLE_KIND,
    MlOperationLink,
    MlOpsDivergence,
    MlOrderItemOps,
    MlOrdersOps,
    MlShipmentOps,
)
from app.models.ml_payments import MlPaymentOps
from app.models.rma_claim_ml import RmaClaimML
from app.models.usuario import Usuario
from app.services.ml_orders_ingestion.activity_receiver_service import drain_activity
from app.services.ml_orders_ingestion.mode_resolution import resolve_modo_logistico
from app.services.ml_orders_ingestion.operation_status import (
    GOODS_STATUSES,
    OPERATION_STATUSES,
)
from app.services.ml_ventas_desglose.breakdown_service import (
    RELEVANT_PAYMENT_STATUSES,
    compute_breakdown,
    compute_neto_desglose_by_order_ids,
)
from app.services.ml_sales_query.aggregate import aggregate_order_metrics
from app.services.ml_sales_query.filters import (
    SalesFilter,
    build_scope,
    collapse,
    effective_switches,
    excluded_by_toggle_counts,
)
from app.services.ml_ventas_desglose.deducciones import resolve_costo_mercaderia_detalle
from app.services.ml_ventas_desglose.iva import descomponer_neto
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.producto import ProductoERP
from app.services.order_metrics import health as order_metrics_health
from app.services.order_metrics.read import metrics_state_for_orders, read_stored_metrics
from app.services.order_metrics.types import GaussStatus
from app.services.permisos_service import PermisosService

DIVERGENCE_KINDS = (
    "missing_in_gbp",
    "missing_in_ml",
    "field_mismatch",
    "out_of_window_update",
    UNENUMERABLE_KIND,
    "unknown",
    INGEST_FAILED_KIND,
    # ventas-ml-rediseno PR6 (design D10): opened by `order_metrics.divergence`
    # when a stored `ml_order_metrics` row disagrees with a fresh recompute.
    "stored_metrics_mismatch",
)
DIVERGENCE_STATES = ("open", "acknowledged", "resolved", "ignored")
# `window_not_enumerable` uses `order_id=0` as a sentinel (no single order
# for an unenumerable leaf, see `sweep_service.record_unenumerable_window`)
# -- MUST NOT render as an order id (mandatory debt from slice 3).
_UNENUMERABLE_SENTINEL_ORDER_ID = 0

router = APIRouter(prefix="/ml-ventas-ops", tags=["ML Ventas Ops"])


def require_permission(permission: str):
    """Dependency for a required permission code -- same pattern as
    `document_templates.py`/`alertas.py`, reused rather than reinvented."""

    def _check_permission(
        current_user: Usuario = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> Usuario:
        permisos_service = PermisosService(db)
        if not permisos_service.tiene_permiso(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No tienes permiso: {permission}",
            )
        return current_user

    return _check_permission


def _require_flag_enabled() -> None:
    if not settings.ML_ORDERS_OPS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML operations source-of-truth is disabled (ML_ORDERS_OPS_ENABLED=false)",
        )


# ── Schemas ──────────────────────────────────────────────────────


def _as_str(value: Any) -> Optional[str]:
    """A raw-JSON value we declare as a string, or None. ML has changed a
    scalar into an object before now, and a response model that raises on it
    would take the whole order detail down (BREAKDOWN R32: the new fields are
    ADDITIVE, so their absence is never an error)."""
    return value if isinstance(value, str) else None


def _as_int(value: Any) -> Optional[int]:
    """Same rule for an integer field. `bool` is excluded on purpose: it is
    an `int` subclass, and `True` is not one installment."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class OrderOpsSummary(BaseModel):
    order_id: int
    pack_id: Optional[int] = None
    status: Optional[str] = None
    status_detail: Optional[str] = None
    buyer_id: Optional[int] = None
    buyer_nickname: Optional[str] = None
    seller_id: int
    total_amount: Optional[float] = None
    paid_amount: Optional[float] = None
    currency_id: Optional[str] = None
    # PR12 (BREAKDOWN R32): additive, buyer's real name from
    # `raw_order["buyer"]` -- `None` when `raw_order` was never captured or
    # carries no `buyer` block, never invented.
    buyer_first_name: Optional[str] = None
    buyer_last_name: Optional[str] = None
    # PR12: additive, THIS order's first synced payment's own
    # `payment_method_id`/`installments`, read from `MlPaymentOps.raw_payload`
    # -- no typed column carries them (explore finding). `None` when no
    # payment has synced yet. Card brand/last-4 stay out of scope: ML does
    # not send them.
    payment_method_id: Optional[str] = None
    installments: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_order(
        cls, order: "MlOrdersOps", payment_method_id: Optional[str], installments: Optional[int]
    ) -> "OrderOpsSummary":
        # Raw ML JSON: a shape we did not expect must degrade to nulls, never
        # take the whole endpoint down with it.
        raw_order = order.raw_order if isinstance(order.raw_order, dict) else {}
        buyer = raw_order.get("buyer")
        if not isinstance(buyer, dict):
            buyer = {}
        return cls(
            order_id=order.order_id,
            pack_id=order.pack_id,
            status=order.status,
            status_detail=order.status_detail,
            buyer_id=order.buyer_id,
            buyer_nickname=order.buyer_nickname,
            seller_id=order.seller_id,
            total_amount=float(order.total_amount) if order.total_amount is not None else None,
            paid_amount=float(order.paid_amount) if order.paid_amount is not None else None,
            currency_id=order.currency_id,
            buyer_first_name=_as_str(buyer.get("first_name")),
            buyer_last_name=_as_str(buyer.get("last_name")),
            payment_method_id=payment_method_id,
            installments=installments,
        )


class OrderItemOpsSummary(BaseModel):
    item_id: str
    variation_id: Optional[int] = None
    seller_sku: Optional[str] = None
    title: Optional[str] = None
    quantity: Optional[int] = None
    unit_price: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class ShipmentOpsSummary(BaseModel):
    shipment_id: int
    status: Optional[str] = None
    substatus: Optional[str] = None
    tracking_number: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ClaimSummary(BaseModel):
    claim_id: int
    claim_type: Optional[str] = None
    status: Optional[str] = None
    reason_category: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class QuestionSummary(BaseModel):
    ml_question_id: int
    item_id: str
    question_text: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class MessageSummary(BaseModel):
    ml_message_id: str
    text: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class BreakdownLineSummary(BaseModel):
    """One line of the cost breakdown.

    `origen` says WHERE the number came from, and it is not one value any
    more. `"api"` means ML's own payment/billing data, straight through
    with nothing computed here (corte 6 of ml-ventas-desglose-costos).
    `"propio"` means OUR preparation tables -- today the real Flex cost,
    resolved from the shipping label's `costo_override` or the logistics
    provider's cordon tariff, which ML never tells us.

    The distinction is the point: an operator reading a Flex sale has to
    be able to tell the cost we pay from the charge ML bills.

    `"recuperable"` (ml-ventas-neto-iibb-varios D2) is a third value: a
    SIRTAC withholding, shown so the operator can see it, but NOT part of
    what was subtracted to arrive at Neto -- it is a recoverable tax
    credit ML already gave back inside Neto itself (see
    `OperationBreakdownSummary.retenciones_recuperables`)."""

    concepto: str
    monto: float
    origen: str = "api"


class ItemDesgloseLineSummary(BaseModel):
    """One product line under "Monto de la operación" -- ml-ventas-desglose-
    costos, "detalle de productos". `monto=None` means THIS item has no
    known `unit_price` (never a fabricated `$0`); when that happens
    `item_lines_reconcilia` on the parent is `False` and the whole list
    must be read as untrustworthy, not just this one row."""

    item_id: str
    variation_id: Optional[int] = None
    seller_sku: Optional[str] = None
    title: Optional[str] = None
    quantity: Optional[int] = None
    monto: Optional[float] = None


class OperationBreakdownSummary(BaseModel):
    """The sale's cost breakdown. `incompleto=True` with a populated
    `incomplete_reasons` means data is missing -- `neto` is never a
    fabricated number in that case (it is `None` when payments have not
    even synced).

    The lines do NOT sum to `neto`. `origen="api"` lines explain what ML
    already subtracted to arrive at `neto`; `origen="propio"` lines are
    costs WE pay that ML never saw, and they sit alongside `neto` rather
    than inside it. Anything rendering this must not present the two as a
    single column that adds up.

    `monto_operacion` is the gross the sale was paid for -- `paid_amount`
    summed across every order in the operation, BEFORE any line in `lines`
    comes off it -- so a reader has a starting figure to read the charges
    against. `None` (never `0`) whenever any member order's `paid_amount`
    is not yet known; a `0` here would read as a real, measured amount."""

    lines: List[BreakdownLineSummary]
    neto: Optional[float] = None
    incompleto: bool
    incomplete_reasons: List[str]
    monto_operacion: Optional[float] = None
    # Per-item breakdown of `monto_operacion` -- see `ItemDesgloseLineSummary`.
    # `monto_operacion` IS these lines' own total, so they cannot disagree
    # with it by construction. `item_lines_reconcilia=False` therefore means
    # the total could not be formed at all -- no items, a missing price, or
    # a missing quantity -- and `item_lines_razon` names which. The renderer
    # must surface that instead of presenting a list that looks complete
    # but is not.
    #
    # It once also meant "the lines do not add up to `monto_operacion`",
    # back when that heading was `paid_amount`. That comparison is gone
    # along with the mis-specification that made it necessary.
    item_lines: List[ItemDesgloseLineSummary] = Field(default_factory=list)
    item_lines_reconcilia: bool = True
    item_lines_razon: Optional[str] = None
    # ml-ventas-neto-iibb-varios R1/R4: `neto` already carries the SIRTAC
    # add-back. `retenciones_recuperables` is the non-refunded SIRTAC total
    # and `neto_depositado` is what ML actually deposited (`neto` minus
    # it) -- both `None` only when `neto` itself is `None`.
    neto_depositado: Optional[float] = None
    retenciones_recuperables: Optional[float] = None

    @classmethod
    def from_domain(cls, breakdown) -> "OperationBreakdownSummary":
        return cls(
            lines=[
                BreakdownLineSummary(concepto=line.concepto, monto=float(line.monto), origen=line.origen)
                for line in breakdown.lines
            ],
            neto=float(breakdown.neto) if breakdown.neto is not None else None,
            incompleto=breakdown.incompleto,
            incomplete_reasons=list(breakdown.incomplete_reasons),
            monto_operacion=(float(breakdown.monto_operacion) if breakdown.monto_operacion is not None else None),
            neto_depositado=(float(breakdown.neto_depositado) if breakdown.neto_depositado is not None else None),
            retenciones_recuperables=(
                float(breakdown.retenciones_recuperables) if breakdown.neto is not None else None
            ),
            item_lines=[
                ItemDesgloseLineSummary(
                    item_id=item.item_id,
                    variation_id=item.variation_id,
                    seller_sku=item.seller_sku,
                    title=item.title,
                    quantity=item.quantity,
                    monto=float(item.monto) if item.monto is not None else None,
                )
                for item in breakdown.item_lines
            ],
            item_lines_reconcilia=breakdown.item_lines_reconcilia,
            item_lines_razon=breakdown.item_lines_razon,
        )


class IvaComponenteSummary(BaseModel):
    """One line of `DescomposicionIvaSummary`: `alicuota=None` marks a
    withholding or residual charge that carries no IVA (D8/D11)."""

    concepto: str
    alicuota: Optional[float] = None
    bruto: float
    base: float
    iva: float
    # ml-ventas-neto-iibb-varios D3: a SIRTAC component is displayed
    # (bruto/base/iva keep their value) but contributes 0 to `suma_bruto`/
    # `neto_sin_iva` -- it was already added back into `neto`. Every other
    # component stays `informativo=False`.
    informativo: bool = False


class DescomposicionIvaSummary(BaseModel):
    """PR4's IVA split of THIS order's `neto` (ml-ventas-modo-logistico
    PR6, design D8-D12). `neto_sin_iva=None` with a non-empty `razones`
    means the split could not be trusted -- never a fabricated number."""

    componentes: List[IvaComponenteSummary]
    neto_sin_iva: Optional[float] = None
    reconcilia: bool
    diferencia: Optional[float] = None
    razones: List[str]
    # ml-ventas-neto-iibb-varios R2: the non-refunded débitos/créditos
    # amount doubled as an extra IVA-free component -- 0 (never None) when
    # the order carries no such charge.
    debitos_creditos_retiro: float = 0
    # ml-ventas-neto-iibb-varios R3 (PR2): Σ base of the "Venta" components
    # -- the goods, without IVA. `None` when not yet computed (PR1) or when
    # the split itself could not be formed.
    base_venta_sin_iva: Optional[float] = None

    @classmethod
    def from_domain(cls, desc) -> "DescomposicionIvaSummary":
        return cls(
            componentes=[
                IvaComponenteSummary(
                    concepto=componente.concepto,
                    alicuota=float(componente.alicuota) if componente.alicuota is not None else None,
                    bruto=float(componente.bruto),
                    base=float(componente.base),
                    iva=float(componente.iva),
                    informativo=componente.informativo,
                )
                for componente in desc.componentes
            ],
            neto_sin_iva=float(desc.neto_sin_iva) if desc.neto_sin_iva is not None else None,
            reconcilia=desc.reconcilia,
            diferencia=float(desc.diferencia) if desc.diferencia is not None else None,
            razones=list(desc.razones),
            debitos_creditos_retiro=float(desc.debitos_creditos_retiro),
            base_venta_sin_iva=(float(desc.base_venta_sin_iva) if desc.base_venta_sin_iva is not None else None),
        )


class DeduccionLineaSummary(BaseModel):
    """One link of `CadenaTotalGaussSummary.lineas`. `monto=None` is the
    exact link that blocked the chain (design D7) -- the UI points at it,
    it never reads as a zero deduction."""

    code: str
    monto: Optional[float] = None
    # The per-order label (e.g. the logistics company name for
    # `envio_flex`) when the deduction has one to offer -- `None` means
    # "use the frontend's static label for this `code`", never "no label".
    concepto: Optional[str] = None


class ItemCostoLineSummary(BaseModel):
    """One item's frozen-cost arithmetic behind "Costo de mercadería"
    (product-owner request: replicate the number). `conocido=False` means
    this item has no frozen `MlOrderItemCosto` row at all -- every other
    field is `None` in that case, and the renderer must read it as
    "unknown", never as a `$0` cost.

    `tipo_cambio`/`tipo_cambio_fecha` are `None` whenever `moneda != "USD"`:
    an ARS-costed item never had a conversion applied, and the renderer
    must not fabricate an empty conversion row for one.

    `fuente` and `costo_fecha` are passed through verbatim from
    `MlOrderItemCosto` -- see that model's own docstring for what each
    `fuente` value means (`erp_publicacion`/`erp_sku`: current ERP cost;
    `hist_publicacion`/`hist_sku`/`hist_combo`: a dated historical cost from
    the backfill) and why `costo_fecha` is `None` for a live-frozen row."""

    item_id: str
    variation_id: Optional[int] = None
    title: Optional[str] = None
    quantity: Optional[int] = None
    conocido: bool
    moneda: Optional[str] = None
    costo_origen: Optional[float] = None
    tipo_cambio: Optional[float] = None
    tipo_cambio_fecha: Optional[date] = None
    costo_unitario_ars: Optional[float] = None
    fuente: Optional[str] = None
    costo_fecha: Optional[date] = None

    @classmethod
    def from_domain(cls, detalle) -> "ItemCostoLineSummary":
        return cls(
            item_id=detalle.item_id,
            variation_id=detalle.variation_id,
            title=detalle.title,
            quantity=detalle.quantity,
            conocido=detalle.conocido,
            moneda=detalle.moneda,
            costo_origen=float(detalle.costo_origen) if detalle.costo_origen is not None else None,
            tipo_cambio=float(detalle.tipo_cambio) if detalle.tipo_cambio is not None else None,
            tipo_cambio_fecha=detalle.tipo_cambio_fecha,
            costo_unitario_ars=(float(detalle.costo_unitario_ars) if detalle.costo_unitario_ars is not None else None),
            fuente=detalle.fuente,
            costo_fecha=detalle.costo_fecha,
        )


class CadenaTotalGaussSummary(BaseModel):
    """This order's deduction chain, in chain order (`neto_sin_iva` minus
    each applicable deduction). `total_gauss=None` whenever `neto_sin_iva`
    itself is unknown OR any applicable deduction resolved unknown (except
    the Flex-only provisional case below).

    `markup` is the sale's REAL markup -- `total_gauss / costo_mercaderia`
    as a percentage, see `TotalGaussResultado.markup`'s docstring in
    `deducciones.py` for why this formula over the theoretical one.
    `None` (never `0`, never infinite) whenever `total_gauss` is unknown,
    the goods cost is unknown, or the cost is exactly zero.

    `provisional` (total-gauss-provisorio) is `True` when `total_gauss` was
    computed WITHOUT the Flex freight cost, because that cost is not
    resolvable yet (shipping label not loaded at the warehouse) -- see
    `TotalGaussResultado.provisional`'s docstring. `provisional_falta`
    names the missing concept (e.g. "Envío Flex") for the UI badge.

    `costo_mercaderia_items` (product-owner request: replicate the goods
    cost) is the per-item arithmetic behind the `costo_mercaderia` link
    above -- see `ItemCostoLineSummary`. Always populated regardless of
    whether `costo_mercaderia` itself resolved (an operator can still see
    WHICH items have a known cost and which do not)."""

    total_gauss: Optional[float] = None
    lineas: List[DeduccionLineaSummary]
    markup: Optional[float] = None
    provisional: bool = False
    provisional_falta: Optional[str] = None
    costo_mercaderia_items: List[ItemCostoLineSummary] = Field(default_factory=list)

    @classmethod
    def from_stored(cls, stored, costo_items: Optional[List] = None) -> "CadenaTotalGaussSummary":
        """ventas-ml-rediseno PR7 (design D2/D13, spec SM R5/R6): the
        detail panel's chain now renders from the STORED
        `app.services.order_metrics.types.OrderMetrics` (`read.read_stored_metrics`),
        never from a live `calcular_total_gauss` call. `stored=None` means
        this order has no `ml_order_metrics` row yet (`pending`/never
        computed) -- rendered as fully unknown, never a fabricated number.
        `costo_mercaderia_items` is unrelated to the Total Gauss chain (it
        reads the frozen cost snapshot directly) and is unaffected by this
        switch."""
        if stored is None:
            return cls(
                total_gauss=None,
                lineas=[],
                markup=None,
                provisional=False,
                provisional_falta=None,
                costo_mercaderia_items=[ItemCostoLineSummary.from_domain(item) for item in (costo_items or [])],
            )
        return cls(
            total_gauss=float(stored.total_gauss) if stored.total_gauss is not None else None,
            lineas=[
                DeduccionLineaSummary(code=code, monto=float(monto) if monto is not None else None, concepto=concepto)
                for code, monto, concepto in stored.lineas
            ],
            markup=float(stored.markup_pct) if stored.markup_pct is not None else None,
            provisional=stored.gauss_status == GaussStatus.PROVISIONAL,
            provisional_falta=stored.provisional_falta,
            costo_mercaderia_items=[ItemCostoLineSummary.from_domain(item) for item in (costo_items or [])],
        )


class SaleCentricOperation(BaseModel):
    order: OrderOpsSummary
    items: List[OrderItemOpsSummary]
    shipment: Optional[ShipmentOpsSummary] = None
    claim: Optional[ClaimSummary] = None
    questions: List[QuestionSummary]
    messages: List[MessageSummary]
    breakdown: OperationBreakdownSummary
    # ml-ventas-modo-logistico PR5: ALWAYS recomputed live (design D2), same
    # as every field of `breakdown` above -- never `MlOrdersOps.total_gauss`.
    total_gauss: Optional[float] = None
    # ml-ventas-modo-logistico PR6: THIS order's own IVA split and
    # deduction chain -- both already computed by PR4/PR5 to produce the
    # `total_gauss` above, exposed here so the UI can show WHY it is (or
    # is not) known, instead of just the final figure.
    iva_decomposicion: DescomposicionIvaSummary
    cadena_total_gauss: CadenaTotalGaussSummary
    # ventas-ml-rediseno PR7 (design D9, spec SM R6): 'ok' | 'provisional' |
    # 'unresolved' | 'recalculating' | 'failed' | 'pending' for THIS order.
    # While 'recalculating', `total_gauss`/`cadena_total_gauss` above may
    # be stale (or absent) -- the panel must show this explicit indicator
    # instead of asserting the chain-equals-stored invariant.
    metrics_state: str

    model_config = ConfigDict(from_attributes=True)


class DivergenceSummary(BaseModel):
    """A single `ml_ops_divergence` row. `order_id` is `None` for
    `window_not_enumerable` rows (see `_UNENUMERABLE_SENTINEL_ORDER_ID`);
    `window_from`/`window_to` carry that kind's leaf bounds instead."""

    id: int
    order_id: Optional[int] = None
    kind: str
    field: Optional[str] = None
    ml_value: Optional[str] = None
    gbp_value: Optional[str] = None
    window_from: Optional[str] = None
    window_to: Optional[str] = None
    state: str
    assigned_to_id: Optional[int] = None
    note: Optional[str] = None
    detected_at: datetime = Field(
        description=(
            "When this divergence was FIRST detected, or first detected since it last "
            "reopened -- not when it was last seen. Detection skips a divergence whose "
            "values have not changed, so this timestamp does not advance while the same "
            "difference persists. `out_of_window_update` and `window_not_enumerable` "
            "come from a different write path and do mean last seen."
        )
    )
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: MlOpsDivergence) -> "DivergenceSummary":
        is_unenumerable = row.kind == UNENUMERABLE_KIND and row.order_id == _UNENUMERABLE_SENTINEL_ORDER_ID
        # Cost-sync give-up counters share the `order_id=0` sentinel but
        # not the `window_not_enumerable` kind, so they need their own
        # test: without it they render as ML order 0, an order that does
        # not exist. Their `field` (`cost_sync:<shipment_id>`) and
        # `ml_value` (the attempt count) ARE meaningful, so only the
        # sentinel order id is masked.
        is_cost_sync = (
            row.kind == COST_SYNC_KIND
            and row.order_id == COST_SYNC_SENTINEL_ORDER_ID
            and (row.field or "").startswith(COST_SYNC_FIELD_PREFIX)
        )
        return cls(
            id=row.id,
            order_id=None if (is_unenumerable or is_cost_sync) else row.order_id,
            kind=row.kind,
            field=None if is_unenumerable else row.field,
            ml_value=None if is_unenumerable else row.ml_value,
            gbp_value=None if is_unenumerable else row.gbp_value,
            window_from=row.ml_value if is_unenumerable else None,
            window_to=row.gbp_value if is_unenumerable else None,
            state=row.state,
            assigned_to_id=row.assigned_to_id,
            note=row.note,
            detected_at=row.detected_at,
            updated_at=row.updated_at,
        )


class DivergenceListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    divergences: List[DivergenceSummary]


class DivergenceUpdateRequest(BaseModel):
    state: Optional[str] = Field(default=None, description="One of: " + ", ".join(DIVERGENCE_STATES))
    assigned_to_id: Optional[int] = None
    note: Optional[str] = None


class SaleListItem(BaseModel):
    order_id: int
    pack_id: Optional[int] = None
    status: Optional[str] = None
    date_created: Optional[datetime] = None
    ml_last_updated: Optional[datetime] = None
    buyer_nickname: Optional[str] = None
    total_amount: Optional[float] = None
    paid_amount: Optional[float] = None
    currency_id: Optional[str] = None
    payment_status: Optional[str] = None
    shipping_status: Optional[str] = None
    operation_status: str
    goods_status: str
    neto: Optional[float] = None
    # Resolved cascade (design D1 of ml-ventas-modo-logistico): the real
    # shipment's `logistic_type` ALWAYS outranks the `no_shipping` tag --
    # see `resolve_modo_logistico`. Recomputed live here on every read; no
    # snapshot column exists for this, by design -- the shipment upsert can
    # land after the order's, so a stored mode would be wrong for exactly
    # as long as that gap lasts.
    modo_logistico: str
    # ml-ventas-modo-logistico PR5, design D2: ALWAYS recomputed live for
    # this row, NEVER read from `MlOrdersOps.total_gauss` (that column is a
    # sort/filter key only). `None` means unknown -- either `neto_sin_iva`
    # itself did not reconcile (design D12) or a chain deduction did not
    # resolve (design D7), never a partial number.
    total_gauss: Optional[float] = None
    # total-gauss-provisorio: same flag as `CadenaTotalGaussSummary`'s, so
    # the list row can carry the same badge the detail drawer shows -- the
    # product owner's decision was explicit that this is NOT drawer-only.
    total_gauss_provisional: bool = False
    total_gauss_provisional_falta: Optional[str] = None
    # ml-ventas-neto-iibb-varios PR1.T12 (decision b): what the listing's
    # Neto tooltip needs, sourced from the same bulk fields the drawer
    # uses -- `None` only when `neto` itself is `None`.
    neto_depositado: Optional[float] = None
    retenciones_recuperables: Optional[float] = None
    # ventas-ml-rediseno PR10.T2 (design D13, spec LISTING R28): the ERP
    # category of ONE of this order's items, resolved through the frozen
    # cost linkage (`ml_order_item_costos.producto_item_id` ->
    # `productos_erp.item_id`) -- the same linkage the D12a product facets
    # already join through. `None` when the order has no frozen cost row
    # yet (FE falls back to a generic icon, PR14). ML's own
    # `raw_item.category_id` is an opaque MLA id with no human mapping
    # stored anywhere, so it is never used here.
    item_category: Optional[str] = None
    # ventas-ml-rediseno PR10.T4 (design D13, spec LISTING R28): captured
    # from `MlShipmentOps.receiver_address` (real shape verified against
    # `ml_webhook_service.py`'s own parsing: `{"city": {"name": ...},
    # "state": {"name": ...}}`), null-safe on a missing key, a null value
    # or an unexpected (non-dict) type -- this is raw ML JSONB, never
    # assumed to have a fixed shape.
    city: Optional[str] = None
    province: Optional[str] = None
    shipping_substatus: Optional[str] = None
    # Sum of every relevant payment's `coupon_amount` for this order
    # (`MlPaymentOps.coupon_amount`, already ingested -- ml-ventas-neto-
    # iibb-varios's own `RELEVANT_PAYMENT_STATUSES`). `None` when the order
    # has no relevant payment synced yet, never a fabricated zero.
    coupon_amount: Optional[float] = None
    # ventas-ml-rediseno PR10.T8 (design D9/D13): the SAME precedence
    # `metrics_state_for_orders` already computes for the detail endpoint
    # (PR7) -- never re-derived here.
    metrics_state: Optional[str] = None
    # ventas-ml-rediseno PR10.T6 (design D13, spec LISTING R29): unified
    # alert level replacing ad-hoc per-field FE flags -- see
    # `_alert_level`'s docstring for the exact precedence.
    alert_level: str = "ok"
    # ventas-ml-rediseno PR10.T7 (design D13, spec LISTING R31): read from
    # `ml_order_metrics.markup_pct`, never a live recompute -- new field,
    # `neto`/`total_gauss` above are switched to the same stored source in
    # `listar_ventas` without changing their name/shape (additive-only).
    markup: Optional[float] = None
    # ventas-ml-producto-listado-pr10b (PR14.T5/T6 blocker): the SAME
    # `OrderItemOpsSummary` shape `GET /orders/{id}` already exposes for its
    # own `items` field -- reused rather than inventing a second per-item
    # vocabulary. A LIST because one order can carry several items (ML
    # never splits them into separate orders); a flat `title`/`seller_sku`
    # pair here would silently pick one and lie about the rest. Empty list
    # (never `None`) when the order has no synced item row yet.
    items: List[OrderItemOpsSummary] = Field(default_factory=list)


class SaleGroup(BaseModel):
    """One ROW of the listing: a pack, or a lone order.

    Mercado Libre splits a single purchase into one `order` per item and
    ties them together with `pack_id`. Rendered one-per-row, three orders
    from the same buyer at the same second with different amounts read as
    three unrelated sales -- the operator could not tell what they were
    looking at, and that is what this type exists to fix. Verified live on
    2000018230951686 / 2000018230945962: same `pack_id`, same shipment,
    one physical parcel.

    `group_key` is a STRING, never the bare numeric id. Pack ids and order
    ids are drawn from the same numeric range on ML (`2000014816536209`
    and `2000018230951686` are a pack and an order), so a bare
    `COALESCE(pack_id, order_id)` could collide and silently merge a pack
    with an unrelated order.

    A group's status is its members' only when they AGREE. `"mixed"` is
    not a status either axis defines -- it is this type saying the members
    disagree and the operator has to open the group. Collapsing a
    disagreement into one badge would hide exactly the case worth seeing.
    """

    group_key: str
    pack_id: Optional[int] = None
    date_created: Optional[datetime] = None
    # The MOST RECENT update across the group's orders: a pack is stale only
    # when every one of its parcels is, so `max` is the honest aggregate
    # here, unlike `date_created` which takes the earliest.
    ml_last_updated: Optional[datetime] = None
    buyer_nickname: Optional[str] = None
    total_amount: Optional[float] = None
    currency_id: Optional[str] = None
    operation_status: str
    goods_status: str
    orders: List[SaleListItem]
    neto: Optional[float] = None
    # The group's modo_logistico, collapsed like `operation_status`/
    # `goods_status`: `"mixed"` when the group's orders disagree, never a
    # silently-picked winner (same `_collapse` used by both status axes).
    modo_logistico: str
    # The pack's Total Gauss is the SUM of its orders', `None` if ANY
    # member's is unknown -- same all-or-nothing rule `neto` already
    # applies at group level (see `group_neto`).
    total_gauss: Optional[float] = None
    # `True` when ANY member order's `total_gauss` is provisional -- the
    # pack sum already includes that order's provisional figure, so the
    # badge must say so too, even if every other member resolved fully.
    total_gauss_provisional: bool = False
    total_gauss_provisional_falta: Optional[str] = None
    # ml-ventas-neto-iibb-varios PR1.T12: sums of the members', all-or-
    # nothing like `group_neto` -- `None` if any member's is `None`.
    neto_depositado: Optional[float] = None
    retenciones_recuperables: Optional[float] = None


class SaleFacetCounts(BaseModel):
    """Counts per value of one filter axis, computed WITHIN the scope the
    OTHER active filters leave standing (not the globally unfiltered
    total) -- see `listar_ventas`'s docstring."""

    operation_status: Dict[str, int]
    goods_status: Dict[str, int]
    # The number of ROWS in that axis's scope, which is NOT the sum of its
    # buckets: a pack whose orders disagree counts in two buckets, so the
    # sum double-counts it. The UI's "Todas" chip needs the count of rows
    # it would actually render, or it contradicts the table under it.
    operation_status_total: int = 0
    goods_status_total: int = 0


class SaleListResponse(BaseModel):
    """`total`/`limit`/`offset` count GROUPS, not orders: the listing
    paginates over what it renders, so a pack can never be split across
    two pages."""

    total: int
    limit: int
    offset: int
    sales: List[SaleGroup]
    facets: SaleFacetCounts


# ── Endpoints ────────────────────────────────────────────────────

# PR9.T1/T2 (design D12): the order-level status derivation, the group key
# expression and the group-level collapse rule used to live here inline.
# They now live in `app.services.ml_sales_query.filters` (moved verbatim,
# see that module's docstring): the expressions come back on `scope`, and
# `collapse` is aliased below so the call sites that used `_collapse` stay
# unchanged.
_collapse = collapse


def _parse_sold_month(sold_month: str) -> Tuple[datetime, datetime]:
    """Parses `YYYY-MM` into a tz-aware `[month_start, next_month_start)`
    range. Raises `HTTPException(422)` for anything else -- never a bare
    `ValueError` reaching the client as a 500."""
    try:
        year_str, month_str = sold_month.split("-", 1)
        year, month = int(year_str), int(month_str)
        if not (1 <= month <= 12):
            raise ValueError("month out of range")
        # Inside the try on purpose: `int("99999")` parses fine and the month
        # check passes, and only `datetime` rejects the year -- outside, that
        # ValueError reached the client as a 500, which is exactly what this
        # function's docstring says cannot happen.
        # Local midnights, for the same reason as `_parse_date_range`: a
        # month is a local idea too, and resolving its edges in UTC moved
        # the first and last evenings of every month into the wrong one.
        tz = ZoneInfo(BUSINESS_TIMEZONE)
        month_start = datetime.combine(date(year, month, 1), time.min, tzinfo=tz)
        days_in_month = calendar.monthrange(year, month)[1]
        next_month_start = datetime.combine(date(year, month, days_in_month) + timedelta(days=1), time.min, tzinfo=tz)
    except (ValueError, OverflowError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"sold_month inválido (esperado YYYY-MM): {sold_month!r}",
        ) from e

    return month_start, next_month_start


SORT_BY_SALE_DATE = "date_created"
SORT_BY_LAST_UPDATE = "ml_last_updated"
# ml-ventas-modo-logistico PR5, design D2: sorts/filters the MATERIALISED
# `total_gauss` column -- a SORT KEY only. The value shown for every row on
# the resulting page is still always recomputed live (see `listar_ventas`),
# never read from this column.
SORT_BY_TOTAL_GAUSS = "total_gauss"
SALE_SORTS = (SORT_BY_SALE_DATE, SORT_BY_LAST_UPDATE, SORT_BY_TOTAL_GAUSS)


def _parse_date_range(date_from: Optional[str], date_to: Optional[str]) -> Optional[Tuple[datetime, datetime]]:
    """Parses `YYYY-MM-DD` bounds into a tz-aware `[from 00:00, to+1d 00:00)`
    range, so `date_from == date_to` means that whole day rather than an
    empty set.

    Either bound may be omitted: only `date_from` is "from then on", only
    `date_to` is "up to and including that day". Raises `HTTPException(422)`
    for anything unparseable -- never a bare `ValueError` reaching the
    client as a 500, same discipline as `_parse_sold_month`.
    """
    if not date_from and not date_to:
        return None

    def _day(value: str, field: str) -> date:
        try:
            year_str, month_str, day_str = value.split("-")
            return date(int(year_str), int(month_str), int(day_str))
        except (ValueError, OverflowError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} inválido (esperado YYYY-MM-DD): {value!r}",
            ) from e

    def _local_midnight(day: date) -> datetime:
        """Midnight of `day` IN THE BUSINESS'S TIMEZONE.

        The column is `timestamptz` holding UTC, which is correct, but the
        day the operator typed is a local day. Resolving it at UTC midnight
        pushes every sale after 21:00 local into the next day -- three hours
        of business landing on the wrong side of the boundary, every day.
        Built from the calendar date and localised, rather than by adding 24
        hours to an instant, so a DST change shifts the boundary instead of
        splitting or duplicating an hour of sales.
        """
        return datetime.combine(day, time.min, tzinfo=ZoneInfo(BUSINESS_TIMEZONE))

    start = _local_midnight(_day(date_from, "date_from")) if date_from else datetime.min.replace(tzinfo=timezone.utc)
    # The exclusive upper bound is the NEXT local midnight, which is what
    # "up to 23:59:59.999" means without having to pick how many nines.
    end = (
        _local_midnight(_day(date_to, "date_to") + timedelta(days=1))
        if date_to
        else datetime.max.replace(tzinfo=timezone.utc)
    )

    if start >= end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"date_from ({date_from!r}) es posterior a date_to ({date_to!r})",
        )
    return start, end


def _parse_csv_strings(raw: Optional[str], field: str) -> Tuple[str, ...]:
    """PFILT R35/T16a: CSV of brand names, deduplicated (order preserved).
    An empty entry (e.g. `"epson,,lexmark"` or a lone `","`) is HTTP 422,
    never silently dropped."""
    if not raw:
        return ()
    values: "list[str]" = []
    seen: set = set()
    for part in raw.split(","):
        value = part.strip()
        if not value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} contiene un valor vacío: {raw!r}",
            )
        key = value.upper()
        if key not in seen:
            seen.add(key)
            values.append(value)
    return tuple(values)


_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1


def _parse_csv_ids(raw: Optional[str], field: str) -> Tuple[int, ...]:
    """PFILT R35/T16a: CSV of integer ids, deduplicated. A non-numeric id
    or an empty CSV entry is HTTP 422 (never treated as 'no filter')."""
    if not raw:
        return ()
    values: "list[int]" = []
    seen: set = set()
    for part in raw.split(","):
        value = part.strip()
        if not value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} contiene un valor vacío: {raw!r}",
            )
        try:
            parsed = int(value)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} inválido (esperado un entero): {value!r}",
            ) from e
        # An INT column raises a DataError on an out-of-range value, which
        # would surface as a 500 instead of the 422 the contract promises.
        if not (_INT32_MIN <= parsed <= _INT32_MAX):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} contiene un id fuera de rango: {value!r}",
            )
        if parsed not in seen:
            seen.add(parsed)
            values.append(parsed)
    return tuple(values)


def _receiver_address_field(receiver_address: Optional[Any], *nested_keys: str) -> Optional[str]:
    """Null-safe read of a `MlShipmentOps.receiver_address` JSONB field
    (PR10.T3/T4, spec LISTING R28). Real captured shape (verified against
    `ml_webhook_service.py`'s own parsing): `{"city": {"name": "..."},
    "state": {"name": "..."}}`. This is raw ML JSONB, so every hop is
    guarded -- a missing key, an explicit `null`, or an unexpected type
    (e.g. a string where a dict is expected) all resolve to `None`, never
    a raised exception or an invented value."""
    value: Any = receiver_address
    for key in nested_keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if not isinstance(value, str) or not value:
        return None
    return value


def _item_category_by_order(db: Session, order_ids: List[int]) -> Dict[int, str]:
    """PR10.T1/T2 (design D13, spec LISTING R28): ONE bulk query for the
    whole page, same join D12a's product facets already use
    (`ml_order_item_costos.producto_item_id` -> `productos_erp.item_id`).
    An order with several items keeps its FIRST item's category (ordered
    by `MlOrderItemCosto.id`, deterministic) -- the listing shows one
    category per row, never a list. An order with no frozen cost row is
    simply absent from the result (`None` at the call site)."""
    result: Dict[int, str] = {}
    if not order_ids:
        return result
    rows = (
        db.query(MlOrderItemCosto.order_id, MlOrderItemCosto.id, ProductoERP.categoria)
        .join(ProductoERP, ProductoERP.item_id == MlOrderItemCosto.producto_item_id)
        .filter(MlOrderItemCosto.order_id.in_(order_ids))
        .order_by(MlOrderItemCosto.order_id, MlOrderItemCosto.id)
        .all()
    )
    for order_id, _costo_id, categoria in rows:
        if order_id not in result and categoria:
            result[order_id] = categoria
    return result


def _coupon_amount_by_order(db: Session, order_ids: List[int]) -> Dict[int, Decimal]:
    """PR10.T3/T4 (design D13, spec LISTING R28): sum of `coupon_amount`
    across every RELEVANT payment of the order (same status filter
    `compute_neto_by_order_ids` applies) -- ONE bulk query for the whole
    page. An order with no relevant payment synced yet is absent from the
    result (`None` at the call site), never a fabricated zero."""
    result: Dict[int, Decimal] = {}
    if not order_ids:
        return result
    rows = (
        db.query(MlPaymentOps.order_id, MlPaymentOps.coupon_amount)
        .filter(MlPaymentOps.order_id.in_(order_ids), MlPaymentOps.status.in_(RELEVANT_PAYMENT_STATUSES))
        .all()
    )
    for order_id, coupon_amount in rows:
        if coupon_amount is None:
            continue
        result[order_id] = result.get(order_id, Decimal("0")) + coupon_amount
    return result


def _items_by_order(db: Session, order_ids: List[int]) -> Dict[int, List[MlOrderItemOps]]:
    """ventas-ml-producto-listado-pr10b: ONE bulk query for the whole page
    (same shape as `_item_category_by_order`/`_coupon_amount_by_order`
    above), grouped in Python -- an order can carry several items, so a
    per-row query here would be an N+1 defect. An order with no synced
    item row is simply absent (`[]` at the call site)."""
    result: Dict[int, List[MlOrderItemOps]] = {}
    if not order_ids:
        return result
    rows = (
        db.query(MlOrderItemOps)
        .filter(MlOrderItemOps.order_id.in_(order_ids))
        .order_by(MlOrderItemOps.order_id, MlOrderItemOps.id)
        .all()
    )
    for item in rows:
        result.setdefault(item.order_id, []).append(item)
    return result


def _alert_level(
    *,
    metrics_state: Optional[str],
    iva_reconcilia: Optional[bool],
    neto: Optional[Decimal],
    operation_status: str,
    goods_status: str,
) -> str:
    """Server-derived unified alert level (design D13, spec LISTING R29):
    `error` = the order's metrics are unresolved/failed/never computed, or
    its `neto` is unknown; `warning` = the metrics are provisional or
    mid-recompute, its IVA split does not reconcile, or either status axis
    is `unknown`; `ok` otherwise. Replaces every ad-hoc per-field flag the
    FE used to derive on its own (PR14 consumes this field only)."""
    if metrics_state in ("unresolved", "failed", "pending") or neto is None:
        return "error"
    if (
        metrics_state in ("provisional", "recalculating")
        or iva_reconcilia is False
        or operation_status == "unknown"
        or goods_status == "unknown"
    ):
        return "warning"
    return "ok"


@router.get("/sales", response_model=SaleListResponse)
def listar_ventas(
    operation_status_filter: Optional[str] = Query(default=None, alias="operation_status"),
    goods_status_filter: Optional[str] = Query(default=None, alias="goods_status"),
    sold_month: Optional[str] = Query(default=None, description="YYYY-MM (legacy, usar date_from/date_to)"),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD, inclusive"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD, inclusive"),
    sort: str = Query(default=SORT_BY_SALE_DATE, description=" | ".join(SALE_SORTS)),
    q: Optional[str] = Query(
        default=None, description="Búsqueda libre: order id, pack id, MLA, SKU, título o comprador (SEARCH R25)"
    ),
    marcas: Optional[str] = Query(default=None, description="CSV de marcas (PFILT R35, D12a)"),
    subcategorias: Optional[str] = Query(default=None, description="CSV de ids de subcategoría (PFILT R35, D12a)"),
    pms: Optional[str] = Query(default=None, description="CSV de ids de usuario PM (PFILT R35, D12a)"),
    # PR11.T1/T9 (design D12/D13, spec KPI R9-R12): the four doubtful-case
    # toggles, shared verbatim with `GET /sales/kpis` (KPI R7/R10). This
    # endpoint's OWN default is `True` (show everything) on EVERY switch --
    # deliberately NOT spec R11's KPI-screen defaults -- to keep `GET
    # /sales` backward compatible for any caller that omits them; the
    # SalesToolbar/useVentasMLFilters URL state (PR16, out of this PR's
    # scope) is what actually applies R11's default-OFF/ON combination on
    # first load, by sending these params explicitly.
    include_unknown: bool = Query(default=True, description='Incluir "A revisar" (KPI R9)'),
    include_in_dispute: bool = Query(default=True, description='Incluir "En disputa" (KPI R9)'),
    include_mixed: bool = Query(default=True, description='Incluir "Mixta" (KPI R9)'),
    include_provisional: bool = Query(default=True, description='Incluir "Provisorio" (KPI R9)'),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: Usuario = Depends(require_permission("ml_ops.ver")),
    db: Session = Depends(get_db),
) -> SaleListResponse:
    """The sales list (design: no read-model table -- `ml_orders_ops` is
    already one row per order, `operation_status`/`goods_status` are
    derived query-time via `op_status_expr`/`goods_status_expr` from `ml_sales_query.filters`,
    the single source of truth those mirror lives in `operation_status.py`).

    Paginated with a deterministic tiebreaker (`date_created` DESC, then
    `order_id` DESC) -- `date_created` alone is not unique across orders.

    Facet counts (`facets.operation_status`, `facets.goods_status`) are
    each computed WITHIN the scope the OTHER active filters leave
    standing: the `operation_status` facet applies `goods_status`/
    `sold_month` but NOT `operation_status` itself, and vice versa, so a
    facet count answers "how many if I also picked this value" rather than
    a meaningless global total.

    One row per GROUP -- a pack, or a lone order (see `SaleGroup`).
    Everything paginated and counted here is groups, never orders, so a
    pack cannot straddle a page boundary.

    A status filter selects GROUPS: a group is shown when ANY of its
    orders matches, and all of its orders come back regardless. The
    alternative -- filtering the members too -- would render a pack
    missing exactly the order that failed the filter, which is a lie about
    what is in the parcel.

    That also means a pack whose orders disagree counts in BOTH buckets of
    a facet, so the facets can add up to more than `total`. That is the
    honest arithmetic for "how many rows would I see if I picked this",
    which is what a facet count answers.

    Requires `ml_ops.ver`, checked BEFORE the feature flag (403 before
    503) -- same precedent as every other endpoint in this router.
    """
    _require_flag_enabled()

    if operation_status_filter is not None and operation_status_filter not in OPERATION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"operation_status inválido: {operation_status_filter}",
        )
    if goods_status_filter is not None and goods_status_filter not in GOODS_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"goods_status inválido: {goods_status_filter}",
        )

    if sort not in SALE_SORTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"sort inválido: {sort!r} (esperado uno de {', '.join(SALE_SORTS)})",
        )

    # `date_from`/`date_to` win over `sold_month`. The month filter is the
    # older, coarser shape of the same idea and is kept so a bookmarked URL
    # does not 422; sending both would be ambiguous, and silently ANDing
    # them can only ever return less than either asked for.
    sold_range: Optional[Tuple[datetime, datetime]] = _parse_date_range(date_from, date_to)
    if sold_range is None and sold_month:
        sold_range = _parse_sold_month(sold_month)

    # PFILT R35/T16a (design D12a): same value contract as
    # `productos_listing.py` -- `marcas` are brand NAMES (case-insensitive
    # compare done in `build_scope`), `subcategorias`/`pms` are integer ids.
    marcas_list = _parse_csv_strings(marcas, "marcas")
    subcategorias_list = _parse_csv_ids(subcategorias, "subcategorias")
    pms_list = _parse_csv_ids(pms, "pms")

    # PR9.T1/T2 (design D12): the seller/date scoping, status derivation,
    # status filters and free-text search all live in `build_scope` now.
    # `scope.members_base` is scoped to the SELLER only (never the date), so
    # a pack straddling a month boundary still returns every member.
    # `scope.facet_base` is the seller+date query PLUS the search, which is
    # what the facet counts must use. `scope.listing_query` is that plus the
    # status filters (SEARCH R26: search intersects with the active filters,
    # never replaces them).
    scope = build_scope(
        db,
        SalesFilter(
            date_range=sold_range,
            operation_status=operation_status_filter,
            goods_status=goods_status_filter,
            q=q,
            marcas=marcas_list,
            subcategorias=subcategorias_list,
            pms=pms_list,
            include_unknown=include_unknown,
            include_in_dispute=include_in_dispute,
            include_mixed=include_mixed,
            include_provisional=include_provisional,
        ),
    )
    op_status_expr = scope.op_status_expr
    goods_status_expr = scope.goods_status_expr
    facet_base = scope.facet_base
    members_base = scope.members_base
    listing_query = scope.listing_query

    # Pagination happens over GROUPS, so a pack can never be split across
    # two pages: page the keys first, then fetch every member of those keys.
    group_key = scope.group_key
    key_page_query = listing_query
    if sort == SORT_BY_TOTAL_GAUSS:
        # ventas-ml-rediseno PR7.T5/T6 (design D2, D1 rationale): the sort
        # key now joins the AUTHORITATIVE `ml_order_metrics` table, never
        # the legacy `MlOrdersOps.total_gauss*` mirror -- that column is
        # kept only for backward-compat until PR8's cleanup. One outer
        # join for the whole page, never a per-row query loop.
        key_page_query = key_page_query.outerjoin(MlOrderMetrics, MlOrderMetrics.order_id == MlOrdersOps.order_id)
    key_page = (
        key_page_query.with_entities(
            group_key.label("group_key"),
            func.min(MlOrdersOps.date_created).label("group_date"),
        )
        .group_by("group_key")
        # The tiebreaker is `max(order_id)`, NOT `group_key`: the key is TEXT,
        # and text ordering puts "o:9" after "o:10". Ordering groups by their
        # key would silently drop the deterministic numeric tiebreaker the
        # per-order listing had, which is what `TestPagination` pins.
        .order_by(
            (
                func.max(MlOrdersOps.ml_last_updated).desc()
                if sort == SORT_BY_LAST_UPDATE
                # `nullslast()`: a historical order with no stored metrics
                # row yet (design D7) has `total_gauss IS NULL` -- SQLite
                # and Postgres order NULLs differently by default, so an
                # explicit `nullslast()` is required or the sort disagrees
                # between the test suite and production.
                else func.max(MlOrderMetrics.total_gauss).desc().nullslast()
                if sort == SORT_BY_TOTAL_GAUSS
                # `ml_last_updated` is NOT NULL, so it needs no nullslast();
                # `date_created` is nullable and Postgres would otherwise put
                # its NULLs first on a DESC sort.
                else func.min(MlOrdersOps.date_created).desc().nullslast()
            ),
            func.max(MlOrdersOps.order_id).desc(),
        )
        .limit(limit)
        .offset(offset)
        .all()
    )
    page_keys = [row.group_key for row in key_page]

    total = listing_query.with_entities(func.count(func.distinct(group_key))).scalar() or 0

    members_by_key: Dict[str, List[SaleListItem]] = {}
    if page_keys:
        # Deliberately NOT `listing_query`, and NOT `base` either: a filter
        # -- status OR month -- selects which GROUPS to show, never which of
        # their orders to hide. `base` carries `sold_month`, so a pack whose
        # orders straddle midnight on the last day of a month came back
        # missing one: an incomplete parcel presented as a complete one,
        # which is exactly what this query exists to avoid.
        member_rows = (
            members_base.add_columns(
                group_key.label("group_key"),
                op_status_expr.label("operation_status"),
                goods_status_expr.label("goods_status"),
            )
            .filter(group_key.in_(page_keys))
            .order_by(MlOrdersOps.date_created.asc().nullslast(), MlOrdersOps.order_id.asc())
            .all()
        )
        page_order_ids = [order.order_id for order, _shipment, _key, _op, _goods in member_rows]
        # ml-ventas-neto-iibb-varios PR1.T12: same bulk shape, for the
        # listing's Neto tooltip -- zero new per-row queries.
        #
        # PR10 review N1 (corrected after initial review pass): this stays
        # LIVE and ungated by `order_metrics_state`, on purpose.
        # `compute_neto_desglose_by_order_ids` derives `neto_depositado`/
        # `retenciones_recuperables` ONLY from `MlPaymentOps` +
        # `MlPaymentCharge` (payments and their charges) -- see
        # `app/services/ml_ventas_desglose/breakdown_service.py`. It does
        # NOT read `costo_mercaderia`, the varios %, etiquetas, cordones,
        # or any other input of the stored Gauss chain. So a recompute
        # triggered by anything OTHER than a payment/charge change (a cost
        # update, a label reassignment, a varios % edit, a config table
        # touch) leaves this live figure byte-identical to what a settled
        # stored row would have shown -- there is no second clock to
        # reconcile in that overwhelming majority of cases. The two CAN
        # only genuinely diverge when the payments/charges themselves
        # changed, and that exact change is what marks the order dirty in
        # the first place -- so the divergence window is the drain
        # latency of that one dirty row, not a standing property of this
        # field. Gating it off `order_metrics_state` (as an earlier draft
        # of this fix did) would hide correct, useful information for
        # every non-payment recompute to guard against a mismatch that
        # does not occur there; reverted for that reason.
        neto_desglose_by_order = compute_neto_desglose_by_order_ids(db, page_order_ids)
        # ventas-ml-rediseno PR10.T7 (design D2/D13, spec LISTING R31):
        # `neto`, `total_gauss` and the new `markup` field are read from the
        # STORED `ml_order_metrics` row -- the SAME reader the detail
        # endpoint already switched to in PR7 -- never a live
        # `compute_neto_by_order_ids`/`calcular_total_gauss` call. An
        # order_id with no stored row is simply absent (`metrics_state`
        # 'pending'), never a fabricated number.
        stored_metrics_by_order = read_stored_metrics(db, page_order_ids)
        metrics_state_by_order = metrics_state_for_orders(db, page_order_ids)
        # PR10.T1/T2, PR10.T3/T4: additive fields, each resolved in ONE bulk
        # query for the whole page -- never one query per row.
        item_category_by_order = _item_category_by_order(db, page_order_ids)
        coupon_amount_by_order = _coupon_amount_by_order(db, page_order_ids)
        # ventas-ml-producto-listado-pr10b: same ONE-bulk-query-for-the-page
        # discipline as the two lookups above.
        items_by_order = _items_by_order(db, page_order_ids)
        for order, shipment, key, operation_status_value, goods_status_value in member_rows:
            stored = stored_metrics_by_order.get(order.order_id)
            order_neto = stored.neto if stored is not None else None
            order_total_gauss = stored.total_gauss if stored is not None else None
            order_markup = stored.markup_pct if stored is not None else None
            order_total_gauss_provisional = stored is not None and stored.gauss_status == GaussStatus.PROVISIONAL
            order_total_gauss_provisional_falta = stored.provisional_falta if stored is not None else None
            order_metrics_state = metrics_state_by_order.get(order.order_id, "pending")
            # See the invariant documented above `neto_desglose_by_order`:
            # deliberately NOT gated by `order_metrics_state` -- this field
            # only depends on payments/charges, not on the rest of the
            # stored Gauss chain.
            order_neto_depositado, order_retenciones_recuperables = neto_desglose_by_order.get(
                order.order_id, (None, None)
            )
            order_coupon_amount = coupon_amount_by_order.get(order.order_id)
            # The real shipment ALWAYS outranks the `no_shipping` tag (order
            # 2000016977234624: tagged `no_shipping` AND a delivered
            # `cross_docking` shipment -- the shipment wins). Recomputed
            # live from the already-joined `shipment` row, no new query.
            order_modo_logistico = resolve_modo_logistico(
                shipment_logistic_type=shipment.logistic_type if shipment is not None else None,
                has_shipment=shipment is not None,
                tagged_no_shipping=bool(order.has_no_shipping_tag),
            )
            order_alert_level = _alert_level(
                metrics_state=order_metrics_state,
                iva_reconcilia=stored.iva_reconcilia if stored is not None else None,
                neto=order_neto,
                operation_status=operation_status_value,
                goods_status=goods_status_value,
            )
            members_by_key.setdefault(key, []).append(
                SaleListItem(
                    order_id=order.order_id,
                    pack_id=order.pack_id,
                    status=order.status,
                    date_created=order.date_created,
                    ml_last_updated=order.ml_last_updated,
                    buyer_nickname=order.buyer_nickname,
                    total_amount=float(order.total_amount) if order.total_amount is not None else None,
                    paid_amount=float(order.paid_amount) if order.paid_amount is not None else None,
                    currency_id=order.currency_id,
                    payment_status=order.payment_status,
                    shipping_status=shipment.status if shipment is not None else None,
                    operation_status=operation_status_value,
                    goods_status=goods_status_value,
                    neto=float(order_neto) if order_neto is not None else None,
                    modo_logistico=order_modo_logistico,
                    total_gauss=float(order_total_gauss) if order_total_gauss is not None else None,
                    total_gauss_provisional=order_total_gauss_provisional,
                    total_gauss_provisional_falta=order_total_gauss_provisional_falta,
                    neto_depositado=(float(order_neto_depositado) if order_neto_depositado is not None else None),
                    retenciones_recuperables=(
                        float(order_retenciones_recuperables) if order_retenciones_recuperables is not None else None
                    ),
                    item_category=item_category_by_order.get(order.order_id),
                    city=_receiver_address_field(
                        shipment.receiver_address if shipment is not None else None, "city", "name"
                    ),
                    province=_receiver_address_field(
                        shipment.receiver_address if shipment is not None else None, "state", "name"
                    ),
                    shipping_substatus=shipment.substatus if shipment is not None else None,
                    coupon_amount=(float(order_coupon_amount) if order_coupon_amount is not None else None),
                    metrics_state=order_metrics_state,
                    alert_level=order_alert_level,
                    markup=float(order_markup) if order_markup is not None else None,
                    items=[OrderItemOpsSummary.model_validate(item) for item in items_by_order.get(order.order_id, [])],
                )
            )

    groups: List[SaleGroup] = []
    for key in page_keys:
        members = members_by_key.get(key, [])
        if not members:
            continue
        # The pack's own identity, not the first member's: every member of a
        # pack carries the same `pack_id`, and a lone order carries none.
        pack_id = members[0].pack_id
        dates = [m.date_created for m in members if m.date_created is not None]
        amounts = [m.total_amount for m in members if m.total_amount is not None]
        currencies = {m.currency_id for m in members if m.currency_id}
        # Resolved BEFORE the constructor: `currencies.pop()` mutates the set,
        # so reading `len(currencies)` in a later argument would depend on
        # argument evaluation order.
        single_currency = currencies.pop() if len(currencies) == 1 else None
        # The pack's neto is the SUM of its orders' -- `None` if ANY member
        # lacks synced payments, never a partial sum that quietly ignores
        # the missing one. Resolved before the constructor for the same
        # reason `single_currency` is: no mutation inside a call's arguments.
        #
        # `single_currency` gates it for the same reason `total_amount`
        # below is gated: adding ARS to USD produces a number that means
        # nothing. Worse here than there -- a mixed pack would render a
        # null amount beside a numeric net, and the row would read as MORE
        # trustworthy than the honest null next to it.
        member_netos = [m.neto for m in members]
        group_neto = None if (single_currency is None or any(n is None for n in member_netos)) else sum(member_netos)
        # Same all-or-nothing rule as `group_neto`: `total_gauss` is IVA-free
        # already, so it needs no currency gate, but ANY member unknown
        # still makes the pack's total unknown -- never a partial sum.
        member_total_gauss = [m.total_gauss for m in members]
        group_total_gauss = None if any(v is None for v in member_total_gauss) else sum(member_total_gauss)
        group_total_gauss_provisional = any(m.total_gauss_provisional for m in members)
        group_total_gauss_provisional_falta = next(
            (m.total_gauss_provisional_falta for m in members if m.total_gauss_provisional_falta), None
        )
        # ml-ventas-neto-iibb-varios PR1.T12: sum the members under the
        # same two gates as `group_neto` -- all-or-nothing on unknown
        # members AND `single_currency`. Without the currency gate a mixed
        # pack would show a null Neto beside a tooltip adding ARS to USD.
        member_neto_depositado = [m.neto_depositado for m in members]
        group_neto_depositado = (
            None
            if (single_currency is None or any(v is None for v in member_neto_depositado))
            else sum(member_neto_depositado)
        )
        member_retenciones_recuperables = [m.retenciones_recuperables for m in members]
        group_retenciones_recuperables = (
            None
            if (single_currency is None or any(v is None for v in member_retenciones_recuperables))
            else sum(member_retenciones_recuperables)
        )
        groups.append(
            SaleGroup(
                group_key=key,
                pack_id=pack_id,
                neto=group_neto,
                total_gauss=group_total_gauss,
                total_gauss_provisional=group_total_gauss_provisional,
                total_gauss_provisional_falta=group_total_gauss_provisional_falta,
                neto_depositado=group_neto_depositado,
                retenciones_recuperables=group_retenciones_recuperables,
                # The earliest member. NOTE this is not always the value the
                # row is sorted by: the sort uses `min` over the FILTERED
                # orders, this uses `min` over all of them. For the pack that
                # straddles a month boundary they differ -- filtering
                # `2026-09` shows `31/08` on a row sorted by `01/09`. Showing
                # the parcel's real date is the right trade; claiming the two
                # always agree was not.
                date_created=min(dates) if dates else None,
                ml_last_updated=(
                    max(u for m in members if (u := m.ml_last_updated) is not None)
                    if any(m.ml_last_updated is not None for m in members)
                    else None
                ),
                buyer_nickname=next((m.buyer_nickname for m in members if m.buyer_nickname), None),
                # A pack is one purchase: its worth is what the buyer paid
                # for all of it, which is why three rows of 27.868 / 27.299 /
                # 24.750 could not be read as the two parcels they were.
                # None across currencies, not a bare sum: adding ARS to USD
                # produces a number that means nothing, and dropping only the
                # currency label would render exactly that number.
                total_amount=float(sum(amounts)) if amounts and single_currency is not None else None,
                currency_id=single_currency,
                operation_status=_collapse([m.operation_status for m in members]),
                goods_status=_collapse([m.goods_status for m in members]),
                modo_logistico=_collapse([m.modo_logistico for m in members]),
                orders=members,
            )
        )

    # Facets: each axis scoped by the OTHER active filter(s), never by its
    # own -- see docstring above.
    op_facet_query = facet_base
    if goods_status_filter is not None:
        op_facet_query = op_facet_query.filter(goods_status_expr == goods_status_filter)
    op_facet_rows = (
        op_facet_query.with_entities(op_status_expr.label("bucket"), func.count(func.distinct(group_key)))
        .group_by("bucket")
        .all()
    )
    op_facet = {value: 0 for value in OPERATION_STATUSES}
    for bucket, count in op_facet_rows:
        op_facet[bucket] = count

    goods_facet_query = facet_base
    if operation_status_filter is not None:
        goods_facet_query = goods_facet_query.filter(op_status_expr == operation_status_filter)
    op_facet_total = op_facet_query.with_entities(func.count(func.distinct(group_key))).scalar() or 0

    goods_facet_rows = (
        goods_facet_query.with_entities(goods_status_expr.label("bucket"), func.count(func.distinct(group_key)))
        .group_by("bucket")
        .all()
    )
    goods_facet = {value: 0 for value in GOODS_STATUSES}
    for bucket, count in goods_facet_rows:
        goods_facet[bucket] = count

    goods_facet_total = goods_facet_query.with_entities(func.count(func.distinct(group_key))).scalar() or 0

    return SaleListResponse(
        total=total,
        limit=limit,
        offset=offset,
        sales=groups,
        facets=SaleFacetCounts(
            operation_status=op_facet,
            goods_status=goods_facet,
            operation_status_total=op_facet_total,
            goods_status_total=goods_facet_total,
        ),
    )


# ── PR11: KPI aggregation (design D12/D13, spec KPI R7-R15) ────────


class SalesKpiExcludedByToggle(BaseModel):
    """KPI R13: how many otherwise-matching GROUPS a currently-OFF toggle
    is hiding, holding every other active filter constant. Always `0` for a
    toggle that is currently ON (nothing of its class is being excluded by
    it)."""

    a_revisar: int = 0
    en_disputa: int = 0
    mixta: int = 0
    provisorio: int = 0


class SalesKpiResponse(BaseModel):
    """Design D12 `aggregate.py` measures (spec KPI R8) plus the D9/D10
    observability fields (spec KPI scenario re: SM R3 `worker_alive`
    surfacing) and the D12 "response echoes effective switches" contract."""

    groups_count: int
    orders_count: int
    gross_billed_ars: float
    gross_billed_other: Dict[str, float]
    neto_sum: float
    neto_unknown_count: int
    total_gauss_sum: float
    total_gauss_ok_count: int
    total_gauss_provisional_count: int
    total_gauss_unresolved_count: int
    markup_weighted_pct: Optional[float]
    # SM R2/R3, design D9: never summed as zero/NULL, always counted and
    # named separately from every other figure above.
    recalculating_count: int
    pending_count: int
    failed_count: int
    # K1: an order missing either `total_gauss` or `costo_mercaderia`
    # contributes to NEITHER side of `markup_weighted_pct` -- counted
    # here, never silently dropped.
    markup_skipped_count: int
    worker_alive: bool
    excluded_by_toggle: SalesKpiExcludedByToggle
    # Design D12 "explicit facet selection overrides its switch; response
    # echoes effective switches" -- PR11.T9's URL round-trip contract reads
    # this back, not just the accepted request params, so a caller can
    # confirm what was ACTUALLY applied (K2: this may differ from the raw
    # request params when an explicit facet overrode its switch).
    effective_switches: Dict[str, bool]


def _toggle_excluded_counts(db: Session, f: SalesFilter) -> SalesKpiExcludedByToggle:
    """KPI R13: thin wrapper around `filters.excluded_by_toggle_counts`
    (K3: computed in ONE aggregate query, not one `build_scope` re-run per
    toggle) -- kept as a router-local function only to adapt the shared
    layer's plain dict into this endpoint's own response model."""
    counts = excluded_by_toggle_counts(db, f)
    return SalesKpiExcludedByToggle(
        a_revisar=counts["a_revisar"],
        en_disputa=counts["en_disputa"],
        mixta=counts["mixta"],
        provisorio=counts["provisorio"],
    )


@router.get("/sales/kpis", response_model=SalesKpiResponse)
def sales_kpis(
    operation_status_filter: Optional[str] = Query(default=None, alias="operation_status"),
    goods_status_filter: Optional[str] = Query(default=None, alias="goods_status"),
    sold_month: Optional[str] = Query(default=None, description="YYYY-MM (legacy, usar date_from/date_to)"),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD, inclusive"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD, inclusive"),
    q: Optional[str] = Query(default=None, description="Búsqueda libre, idéntica a GET /sales (SEARCH R25)"),
    marcas: Optional[str] = Query(default=None, description="CSV de marcas (PFILT R35, D12a)"),
    subcategorias: Optional[str] = Query(default=None, description="CSV de ids de subcategoría (PFILT R35, D12a)"),
    pms: Optional[str] = Query(default=None, description="CSV de ids de usuario PM (PFILT R35, D12a)"),
    # PR11.T9/spec R11: THIS endpoint has no legacy caller, so its own
    # defaults ARE the spec R11 combination -- unlike `GET /sales`'s
    # backward-compatible `True` defaults (see that endpoint's own
    # docstring for why the two differ).
    include_unknown: bool = Query(default=False, description='"A revisar" (KPI R9, R11)'),
    include_in_dispute: bool = Query(default=False, description='"En disputa" (KPI R9, R11)'),
    include_mixed: bool = Query(default=True, description='"Mixta" (KPI R9, R11)'),
    include_provisional: bool = Query(default=True, description='"Provisorio" (KPI R9, R11)'),
    current_user: Usuario = Depends(require_permission("ml_ops.ver")),
    db: Session = Depends(get_db),
) -> SalesKpiResponse:
    """The KPI strip's data source (design D13, spec KPI R7-R15). Shares
    `SalesFilter`/`build_scope` verbatim with `GET /sales` (KPI R7): the
    SAME filter+toggle combination on both endpoints always agrees (KPI
    R14) -- proven by
    `tests/integration/test_ml_ventas_ops_sales_router.py::TestKpiParity`.

    Aggregates the WHOLE filtered set, never the current page (KPI R8) --
    this endpoint takes no `limit`/`offset`. Every measure comes from
    stored `ml_order_metrics` only (`aggregate_order_metrics`), never a
    live recompute.

    The four `include_*` query params are the REQUESTED switches; the
    `effective_switches` field of the response is what was actually
    applied, which can differ when an explicit `operation_status`/
    `goods_status` facet overrides its own switch (K2, design D12
    "explicit facet selection overrides its switch").
    `excluded_by_toggle` (KPI R13) is computed in one aggregate query, not
    one full scope re-run per toggle (K3).

    Requires `ml_ops.ver`, same precedent as `GET /sales`.
    """
    _require_flag_enabled()

    if operation_status_filter is not None and operation_status_filter not in OPERATION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"operation_status inválido: {operation_status_filter}",
        )
    if goods_status_filter is not None and goods_status_filter not in GOODS_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"goods_status inválido: {goods_status_filter}",
        )

    sold_range: Optional[Tuple[datetime, datetime]] = _parse_date_range(date_from, date_to)
    if sold_range is None and sold_month:
        sold_range = _parse_sold_month(sold_month)

    marcas_list = _parse_csv_strings(marcas, "marcas")
    subcategorias_list = _parse_csv_ids(subcategorias, "subcategorias")
    pms_list = _parse_csv_ids(pms, "pms")

    sales_filter = SalesFilter(
        date_range=sold_range,
        operation_status=operation_status_filter,
        goods_status=goods_status_filter,
        q=q,
        marcas=marcas_list,
        subcategorias=subcategorias_list,
        pms=pms_list,
        include_unknown=include_unknown,
        include_in_dispute=include_in_dispute,
        include_mixed=include_mixed,
        include_provisional=include_provisional,
    )
    scope = build_scope(db, sales_filter)
    result = aggregate_order_metrics(db, scope.listing_query, scope.group_key)
    excluded_by_toggle = _toggle_excluded_counts(db, sales_filter)
    # K2: the switches ACTUALLY applied by `build_scope` (an explicit
    # `operation_status`/`goods_status` facet selection may have overridden
    # one), never the raw accepted request params.
    applied_switches = effective_switches(sales_filter)

    return SalesKpiResponse(
        groups_count=result.groups_count,
        orders_count=result.orders_count,
        gross_billed_ars=float(result.gross_billed_ars),
        gross_billed_other={currency: float(amount) for currency, amount in result.gross_billed_other.items()},
        neto_sum=float(result.neto_sum),
        neto_unknown_count=result.neto_unknown_count,
        total_gauss_sum=float(result.total_gauss_sum),
        total_gauss_ok_count=result.total_gauss_ok_count,
        total_gauss_provisional_count=result.total_gauss_provisional_count,
        total_gauss_unresolved_count=result.total_gauss_unresolved_count,
        markup_weighted_pct=(float(result.markup_weighted_pct) if result.markup_weighted_pct is not None else None),
        recalculating_count=result.recalculating_count,
        pending_count=result.pending_count,
        failed_count=result.failed_count,
        markup_skipped_count=result.markup_skipped_count,
        worker_alive=order_metrics_health.worker_alive(db),
        excluded_by_toggle=excluded_by_toggle,
        effective_switches={
            "include_unknown": applied_switches.include_unknown,
            "include_in_dispute": applied_switches.include_in_dispute,
            "include_mixed": applied_switches.include_mixed,
            "include_provisional": applied_switches.include_provisional,
        },
    )


@router.get("/orders/{order_id}", response_model=SaleCentricOperation)
def obtener_operacion(
    order_id: int,
    current_user: Usuario = Depends(require_permission("ml_ops.ver")),
    db: Session = Depends(get_db),
) -> SaleCentricOperation:
    """Sale-centric view: the order plus everything `ml_operation_links`
    resolved to it (shipment, claim, questions, messages) as one operation.
    Requires `ml_ops.ver`. 503 while `ML_ORDERS_OPS_ENABLED` is false."""
    _require_flag_enabled()

    order = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orden no encontrada")

    items = db.query(MlOrderItemOps).filter(MlOrderItemOps.order_id == order_id).all()

    # PR12: THIS order's own payment method/installments -- same
    # "payments[0]" convention as `MlOrdersOps.payment_status` (first
    # synced payment, ordered by `payment_id` for determinism), read out
    # of the raw payload since no typed column carries them.
    first_payment = (
        db.query(MlPaymentOps).filter(MlPaymentOps.order_id == order_id).order_by(MlPaymentOps.payment_id).first()
    )
    payment_raw = first_payment.raw_payload if first_payment and isinstance(first_payment.raw_payload, dict) else {}
    payment_method_id = _as_str(payment_raw.get("payment_method_id"))
    installments = _as_int(payment_raw.get("installments"))

    shipment = None
    if order.shipping_id is not None:
        shipment = db.query(MlShipmentOps).filter(MlShipmentOps.shipment_id == order.shipping_id).first()

    links = db.query(MlOperationLink).filter(MlOperationLink.order_id == order_id).all()
    claim_ids = [link.entity_id for link in links if link.entity_type == "claim"]
    question_ids = [link.entity_id for link in links if link.entity_type == "question"]
    message_ids = [link.entity_id for link in links if link.entity_type == "message"]

    claim = None
    if claim_ids:
        claim = db.query(RmaClaimML).filter(RmaClaimML.id.in_(claim_ids)).first()

    questions = db.query(MlBotQuestion).filter(MlBotQuestion.id.in_(question_ids)).all() if question_ids else []
    messages = db.query(MlBotMessage).filter(MlBotMessage.id.in_(message_ids)).all() if message_ids else []

    # The breakdown is of the PACK, not just this order -- same grouping
    # `listar_ventas` uses (`_group_key_expr`): a lone order is its own
    # group, an order in a pack shares its breakdown with every sibling.
    if order.pack_id is not None:
        breakdown_order_ids = [
            row.order_id for row in db.query(MlOrdersOps.order_id).filter(MlOrdersOps.pack_id == order.pack_id).all()
        ]
    else:
        breakdown_order_ids = [order.order_id]
    breakdown = compute_breakdown(db, breakdown_order_ids)

    # Same D2 discipline as the listing: ALWAYS recomputed here, for the
    # whole pack this detail belongs to (design: "the breakdown is of the
    # PACK, not just this order" -- same grouping the listing uses).
    descomposicion_by_order = descomponer_neto(db, breakdown_order_ids)

    # ventas-ml-rediseno PR7 (design D2/D9/D13, spec SM R5/R6, BREAKDOWN
    # R33): `total_gauss`/`cadena_total_gauss` now read the STORED
    # `ml_order_metrics` row -- never `calcular_total_gauss` live -- for
    # every order of this pack, one bulk read. `metrics_state` for THIS
    # order tells the panel whether it can trust the invariant.
    stored_metrics_by_order = read_stored_metrics(db, breakdown_order_ids)
    order_metrics_state = metrics_state_for_orders(db, [order.order_id])[order.order_id]

    if len(stored_metrics_by_order) == len(breakdown_order_ids):
        member_total_gauss = [m.total_gauss for m in stored_metrics_by_order.values()]
        pack_total_gauss = None if any(v is None for v in member_total_gauss) else sum(member_total_gauss)
    else:
        # At least one member of the pack has no stored row yet (pending) --
        # the pack total is unknown, never a partial sum over the others.
        pack_total_gauss = None

    # THIS order's own split/chain -- the pack sum above answers "how much
    # in total", these answer "why", and summing componentes/lineas across
    # a pack would not be the honest per-order picture the drawer shows.
    order_descomposicion = descomposicion_by_order[order.order_id]
    order_stored_metrics = stored_metrics_by_order.get(order.order_id)

    # THIS order's items, deliberately NOT the whole pack's.
    #
    # The panel carries two scopes on purpose, and this list belongs to the
    # narrow one: it explains `cadena_total_gauss`, which is this order's
    # chain ("the pack sum answers how much, these answer why", above). The
    # products list higher up breaks down `monto_operacion`, which IS the
    # pack. So on a pack the two lists legitimately differ in length.
    #
    # An earlier pass widened this to the pack to make the lengths match.
    # That looked tidier and was wrong: it put the pack's items under this
    # order's cost figure, so the detail no longer explained the number it
    # sat beneath. Matching lengths is not the goal -- each list matching
    # the figure it explains is.
    costo_detalle_by_order = resolve_costo_mercaderia_detalle(db, breakdown_order_ids)
    order_costo_items = costo_detalle_by_order.get(order.order_id, [])

    return SaleCentricOperation(
        order=OrderOpsSummary.from_order(order, payment_method_id, installments),
        items=[OrderItemOpsSummary.model_validate(item) for item in items],
        shipment=ShipmentOpsSummary.model_validate(shipment) if shipment else None,
        claim=ClaimSummary.model_validate(claim) if claim else None,
        questions=[QuestionSummary.model_validate(q) for q in questions],
        messages=[MessageSummary.model_validate(m) for m in messages],
        breakdown=OperationBreakdownSummary.from_domain(breakdown),
        total_gauss=float(pack_total_gauss) if pack_total_gauss is not None else None,
        iva_decomposicion=DescomposicionIvaSummary.from_domain(order_descomposicion),
        cadena_total_gauss=CadenaTotalGaussSummary.from_stored(order_stored_metrics, order_costo_items),
        metrics_state=order_metrics_state,
    )


@router.get("/divergences", response_model=DivergenceListResponse)
def listar_divergencias(
    kind: Optional[str] = Query(default=None, description="Filter by kind"),
    state: Optional[str] = Query(default=None, description="Filter by state"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: Usuario = Depends(require_permission("ml_ops.ver")),
    db: Session = Depends(get_db),
) -> DivergenceListResponse:
    """Paginated (slice 4a precedent: every list endpoint MUST paginate).
    Requires `ml_ops.ver`. 503 while `ML_ORDERS_OPS_ENABLED` is false."""
    _require_flag_enabled()

    if kind is not None and kind not in DIVERGENCE_KINDS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"kind inválido: {kind}")
    if state is not None and state not in DIVERGENCE_STATES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"state inválido: {state}")

    query = db.query(MlOpsDivergence)
    if kind is not None:
        query = query.filter(MlOpsDivergence.kind == kind)
    if state is not None:
        query = query.filter(MlOpsDivergence.state == state)

    total = query.count()
    rows = (
        query.order_by(MlOpsDivergence.detected_at.desc(), MlOpsDivergence.id.desc()).limit(limit).offset(offset).all()
    )

    return DivergenceListResponse(
        total=total,
        limit=limit,
        offset=offset,
        divergences=[DivergenceSummary.from_row(row) for row in rows],
    )


@router.get("/divergences/{divergence_id}", response_model=DivergenceSummary)
def obtener_divergencia(
    divergence_id: int,
    current_user: Usuario = Depends(require_permission("ml_ops.ver")),
    db: Session = Depends(get_db),
) -> DivergenceSummary:
    """Requires `ml_ops.ver`. 503 while `ML_ORDERS_OPS_ENABLED` is false."""
    _require_flag_enabled()

    row = db.query(MlOpsDivergence).filter(MlOpsDivergence.id == divergence_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Divergencia no encontrada")
    return DivergenceSummary.from_row(row)


@router.patch("/divergences/{divergence_id}", response_model=DivergenceSummary)
def actualizar_divergencia(
    divergence_id: int,
    payload: DivergenceUpdateRequest,
    current_user: Usuario = Depends(require_permission("ml_ops.gestionar")),
    db: Session = Depends(get_db),
) -> DivergenceSummary:
    """State/assignee/note changes. Requires `ml_ops.gestionar`, distinct
    from the read-only `ml_ops.ver`. 503 while `ML_ORDERS_OPS_ENABLED` is
    false. Never touches the ML/GBP data the divergence describes -- only
    this row's own bookkeeping (`state`, `assigned_to_id`, `note`)."""
    _require_flag_enabled()

    row = db.query(MlOpsDivergence).filter(MlOpsDivergence.id == divergence_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Divergencia no encontrada")

    # `exclude_unset` via `model_fields_set` distinguishes an ABSENT field
    # (leave alone) from an EXPLICIT `null` (clear it) -- a plain
    # `is not None` check treated both the same, so `{"assigned_to_id":
    # null}` silently did nothing while still returning 200 with the old
    # assignee: the operator believes they released it, and they have not.
    fields_set = payload.model_fields_set

    if "state" in fields_set:
        # `state` is NOT NULL, so an explicit null has to be rejected here.
        # Before absent and null were distinguished, `None` meant "leave
        # alone" and never reached the column; now it does.
        if payload.state not in DIVERGENCE_STATES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"state inválido: {payload.state}"
            )
        row.state = payload.state
    if "assigned_to_id" in fields_set:
        if payload.assigned_to_id is not None:
            # The column is an FK to usuarios.id; a nonexistent id used to
            # reach `db.commit()` unvalidated and raise IntegrityError --
            # a 500 that also left the session broken. Validated the same
            # way `state` is: reject before touching the row.
            assignee_exists = db.query(Usuario.id).filter(Usuario.id == payload.assigned_to_id).first() is not None
            if not assignee_exists:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"assigned_to_id inválido: no existe el usuario {payload.assigned_to_id}",
                )
        row.assigned_to_id = payload.assigned_to_id
    if "note" in fields_set:
        row.note = payload.note
    # `updated_at` is NOT set here: the column already has
    # `onupdate=func.now()`, and setting it by hand overwrites the
    # database's clock with the app server's -- two different clocks for
    # one column.

    db.commit()
    db.refresh(row)
    return DivergenceSummary.from_row(row)


@router.post(
    "/activity/ping",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {"description": "Drain encolado en background; el resultado no vuelve por este request"},
        403: {"description": "Falta el permiso ml_ops.ingest"},
    },
)
def ping_activity(
    background_tasks: BackgroundTasks,
    current_user: Usuario = Depends(require_permission("ml_ops.ingest")),
) -> dict:
    """Ping liviano del bridge ml-webhook (ml-activity-receiver, slice 3):
    encola un drain de `/api/ml/activity` vía `BackgroundTasks` y responde
    202 de inmediato.

    Permiso `ml_ops.ingest` (distinto de `ml_ops.ver`/`ml_ops.gestionar`),
    exclusivo del service user del bridge (slice 1). NO chequea
    `ML_ORDERS_OPS_ENABLED` acá -- a diferencia del resto de este router,
    la bandera apagada es un no-op COMPLETO manejado dentro de
    `drain_activity` (mismo precedente que `backfill_payments_costs_service
    .run_backfill`): el ping sigue devolviendo 202 y el drain encolado no
    hace ningún HTTP ni ninguna escritura, en vez de un 503 que haría que
    un estado deliberadamente apagado se lea como una falla del bridge.

    El cuerpo del request se ignora por completo -- no se declara ningún
    modelo de body, así que FastAPI no lo parsea ni lo valida; este
    endpoint no confía en nada que el bridge le mande en el payload, solo
    en que llegó.

    Un segundo ping mientras un drain ya está en vuelo es inofensivo: el
    lock de corrida (`try_acquire_run_lock`, cursor `ml_activity`) es
    exclusivo por `cursor_name`, así que el segundo background task
    simplemente ve el lock tomado y vuelve sin hacer nada -- nunca dos
    drains concurrentes sobre el mismo cursor.

    `BackgroundTasks` + `get_background_db` (dentro de `drain_activity`),
    NUNCA una sesión de request (`Depends(get_db)`) sostenida durante el
    drain -- este proyecto ya tuvo un incidente de agotamiento del pool de
    conexiones por sostener una sesión de request en un trabajo de larga
    duración (obs `project_db_pool_exhaustion_incident`).
    """
    background_tasks.add_task(drain_activity)
    return {"accepted": True}

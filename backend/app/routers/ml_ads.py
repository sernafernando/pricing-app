"""Router: the Ads cost reads (`/ml-ads/...`, ml-billing-balance design D9, AR-1, AR-3, AR-4, AR-5).

Thin on purpose: it parses the query, checks `ml_metricas.ver_ganancia`, calls `services/ml_ads/read.py` and
serializes. Everything is computed at read time from the stored facts; nothing here calls Mercado Libre, and the only
writes are the brand contributions the team loads.

- `GET /ml-ads/by-mla`: Product Ads per MLA with any activity (cost 0 included) in `[date_from, date_to]`, with its single owner product
  (0 = "sin producto"), cost on the API basis and net of IVA, and the informational metrics. `mlas` narrows (CSV).
- `GET /ml-ads/by-product`: the read-time sum of those rows per owner, "sin producto" included. `product_ids` narrows.
- `GET /ml-ads/account-level`: Display per campaign (subtractable: its IVA basis is measured) and Brand Ads
  (informational only, no net cost). Never attributed to an MLA.
- `GET /ml-ads/campaigns`: every catalogued Product Ads campaign with its brand contributions, its cost in the range
  (ml-ads-brand-contribution S8) and what those contributions cover of it (ml-ads-contribution-redesign S6).
  `POST /ml-ads/contributions/preview` answers what a contribution body would cover, writing nothing.
  `POST /ml-ads/contributions`, `PUT|DELETE /ml-ads/contributions/{id}` load, edit and delete a contribution and also
  need `ml_metricas.gestionar_aportes_ads` (S7); they write only that table.

Every cost read above carries the `coverage` of the same range (ledger days not fetched, and mismatch days), so a gap is
never shown as zero spend. A range is `date_from <= date_to` and at most 366 days; `mlas` and `product_ids` take up
to 500 values; anything else is a 422 with the app's envelope and the offending `field`. A contribution body that
breaks its own shape (kind, value bounds, two decimals, date order) is FastAPI's standard 422 (`detail[].loc`); an
unknown campaign or an overlapping range is the app's envelope with `field`. Money is a float with two decimals,
rounded once here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permiso
from app.core.database import get_db
from app.core.exceptions import ErrorCode, api_error
from app.models.ml_ads import MlAdsCampaignContribution
from app.models.usuario import Usuario
from app.services.ml_ads import contributions, read

PERMISO_GANANCIA = "ml_metricas.ver_ganancia"
PERMISO_APORTES = "ml_metricas.gestionar_aportes_ads"
MAX_DAYS = 366
MAX_IDS = 500

router = APIRouter(
    prefix="/ml-ads",
    tags=["ML Ads"],
    dependencies=[Depends(require_permiso(PERMISO_GANANCIA))],  # first: who may ask comes before what is asked
)


# ── Schemas ──────────────────────────────────────────────────────


class CoverageDayOut(BaseModel):
    source: str
    advertiser_id: int
    day: date
    status: Optional[str] = None  # None: the day was never ledgered (not fetched, which is not zero spend)


class CoverageOut(BaseModel):
    data_through: Optional[date] = None
    missing_days: list[CoverageDayOut]
    mismatch_days: list[CoverageDayOut]


class AdsMetricsOut(BaseModel):
    """Money: `cost_api` is what the API returned, `cost_net` is net of IVA (the basis anything subtracted uses).
    Units and amounts are ML's attributed figures, informational only."""

    cost_api: float
    cost_net: float
    clicks: int
    prints: int
    direct_units: int
    indirect_units: int
    direct_amount: float
    indirect_amount: float
    organic_units: int
    organic_amount: float


class AdsMlaOut(AdsMetricsOut):
    mla: str
    owner_product_id: int


class AdsProductOut(AdsMetricsOut):
    product_id: int  # 0 = "sin producto"
    mlas_count: int


class ByMlaOut(BaseModel):
    coverage: CoverageOut
    items: list[AdsMlaOut]


class ByProductOut(BaseModel):
    coverage: CoverageOut
    products: list[AdsProductOut]


class DisplayCampaignOut(BaseModel):
    campaign_id: int
    cost_api: float
    cost_net: float
    prints: int
    clicks: int


class DisplayOut(BaseModel):
    subtractable: bool = True  # its IVA basis was measured and accepted (owner, Q10)
    cost_api: float
    cost_net: float
    prints: int
    clicks: int
    by_campaign: list[DisplayCampaignOut]


class BrandOut(BaseModel):
    subtractable: bool = False  # informational only (ADS-10): there is deliberately no net cost
    cost_informational: float
    prints: int
    clicks: int


class AccountLevelOut(BaseModel):
    coverage: CoverageOut
    display: DisplayOut
    brand: BrandOut


# ── Parsing ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Window:
    date_from: date
    date_to: date


def _unprocessable(field: str, message: str) -> Exception:
    error = api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_ERROR, message)
    error.detail["field"] = field
    return error


def window(date_from: date = Query(...), date_to: date = Query(...)) -> Window:
    if date_from > date_to:
        raise _unprocessable("date_from", "date_from must not be after date_to")
    if (date_to - date_from).days + 1 > MAX_DAYS:
        raise _unprocessable("date_to", f"the range is at most {MAX_DAYS} days")
    return Window(date_from, date_to)


def _csv(field: str, raw: Optional[str]) -> Optional[list[str]]:
    """`None` when the parameter is absent; otherwise its non-empty values. A filter that is present but empty is a
    422, never "no filter": it must not silently widen the answer."""
    if raw is None:
        return None
    values = [part.strip() for part in raw.split(",") if part.strip()]
    if not values:
        raise _unprocessable(field, f"{field} is present but has no values")
    if len(values) > MAX_IDS:
        raise _unprocessable(field, f"{field} takes at most {MAX_IDS} values")
    return values


# ── Serialization ────────────────────────────────────────────────


def _money(value: Decimal) -> float:
    return float(round(value, 2))


def _coverage(window_: Window, db: Session) -> CoverageOut:
    got = read.ads_coverage(db, window_.date_from, window_.date_to)

    def days(rows: list[read.CoverageDay]) -> list[CoverageDayOut]:
        return [
            CoverageDayOut(source=d.source, advertiser_id=d.advertiser_id, day=d.day, status=d.status) for d in rows
        ]

    return CoverageOut(
        data_through=got.data_through, missing_days=days(got.missing_days), mismatch_days=days(got.mismatch_days)
    )


def _metrics(row: read.AdsMlaRow | read.AdsProductRow) -> dict:
    return {
        "cost_api": _money(row.cost_api),
        "cost_net": _money(row.cost_net),
        "clicks": row.clicks,
        "prints": row.prints,
        "direct_units": row.direct_units,
        "indirect_units": row.indirect_units,
        "direct_amount": _money(row.direct_amount),
        "indirect_amount": _money(row.indirect_amount),
        "organic_units": row.organic_units,
        "organic_amount": _money(row.organic_amount),
    }


# ── Reads ────────────────────────────────────────────────────────


@router.get("/by-mla", response_model=ByMlaOut)
def get_by_mla(
    w: Window = Depends(window),
    mlas: Optional[str] = Query(None, description="CSV of MLA ids, at most 500"),
    db: Session = Depends(get_db),
) -> ByMlaOut:
    rows = read.ads_by_mla(db, w.date_from, w.date_to, _csv("mlas", mlas))
    return ByMlaOut(
        coverage=_coverage(w, db),
        items=[AdsMlaOut(mla=r.mla, owner_product_id=r.owner_product_id, **_metrics(r)) for r in rows],
    )


@router.get("/by-product", response_model=ByProductOut)
def get_by_product(
    w: Window = Depends(window),
    product_ids: Optional[str] = Query(None, description="CSV of product ids (0 = sin producto), at most 500"),
    db: Session = Depends(get_db),
) -> ByProductOut:
    raw = _csv("product_ids", product_ids)
    try:
        ids = None if raw is None else [int(value) for value in raw]
    except ValueError:
        raise _unprocessable("product_ids", "product_ids takes integers")
    rows = read.ads_by_product(db, w.date_from, w.date_to, ids)
    return ByProductOut(
        coverage=_coverage(w, db),
        products=[AdsProductOut(product_id=r.product_id, mlas_count=r.mlas_count, **_metrics(r)) for r in rows],
    )


@router.get("/account-level", response_model=AccountLevelOut)
def get_account_level(w: Window = Depends(window), db: Session = Depends(get_db)) -> AccountLevelOut:
    got = read.ads_account_level(db, w.date_from, w.date_to)
    display, brand = got.display, got.brand
    return AccountLevelOut(
        coverage=_coverage(w, db),
        display=DisplayOut(
            cost_api=_money(display.cost_api),
            cost_net=_money(display.cost_net),
            prints=display.prints,
            clicks=display.clicks,
            by_campaign=[
                DisplayCampaignOut(
                    campaign_id=c.campaign_id,
                    cost_api=_money(c.cost_api),
                    cost_net=_money(c.cost_net),
                    prints=c.prints,
                    clicks=c.clicks,
                )
                for c in display.by_campaign
            ],
        ),
        brand=BrandOut(cost_informational=_money(brand.cost_informational), prints=brand.prints, clicks=brand.clicks),
    )


# ── Brand contributions (ml-ads-brand-contribution) ─────────────


class ContributionIn(BaseModel):
    """`percentage`: 0 < value <= 100. `fixed_amount`: money > 0 with its `settlement` (S6). Both with at most two
    decimals (S4)."""

    advertiser_id: int
    campaign_id: int
    kind: Literal["percentage", "fixed_amount"]
    value: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    date_from: date
    date_to: date
    settlement: Optional[Literal["full", "refund_difference"]] = None
    brand: Optional[str] = Field(None, max_length=120)
    note: Optional[str] = Field(None, max_length=1000)

    @model_validator(mode="after")
    def _bounds(self) -> "ContributionIn":
        if self.kind == "percentage" and self.value > 100:
            raise ValueError("a percentage is at most 100")
        if (self.kind == "fixed_amount") != (self.settlement is not None):
            raise ValueError("a fixed amount says how it settles (full or refund_difference); a percentage does not")
        if self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self


class ContributionOut(BaseModel):
    id: int
    advertiser_id: int
    campaign_id: int
    kind: str
    value: float
    date_from: date
    date_to: date
    settlement: Optional[str] = None
    brand: Optional[str] = None
    note: Optional[str] = None
    created_by_id: int
    updated_by_id: int
    created_at: datetime
    updated_at: datetime


class CampaignOut(BaseModel):
    advertiser_id: int
    campaign_id: int
    advertiser_name: Optional[str] = None  # None: an advertiser without a known name
    name: Optional[str] = None
    status: Optional[str] = None
    cost: float  # `ml_ads_campaign_days.cost` summed over the requested range
    # What the contributions cover of the range: the Métricas ML board's rule over `ml_ads_item_days`, so it equals the
    # board's figure. `cost` keeps the campaign rows; both bases match unless a day's item rows are incomplete.
    contribution: float
    contributions: list[ContributionOut]


class PreviewOut(BaseModel):
    spend: float  # the campaign's cost over the contribution's range
    counted: float  # what Métricas ML would subtract less
    net: float  # spend - counted; negative when a `full` amount exceeds the spend


class CampaignsOut(BaseModel):
    campaigns: list[CampaignOut]


def _contribution_out(row: MlAdsCampaignContribution) -> ContributionOut:
    return ContributionOut(
        id=row.id,
        advertiser_id=row.advertiser_id,
        campaign_id=row.campaign_id,
        kind=row.kind,
        value=_money(row.value),
        date_from=row.date_from,
        date_to=row.date_to,
        settlement=row.settlement,
        brand=row.brand,
        note=row.note,
        created_by_id=row.created_by_id,
        updated_by_id=row.updated_by_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _data(body: ContributionIn) -> contributions.ContributionData:
    return contributions.ContributionData(**body.model_dump())


def _not_found(contribution_id: int) -> Exception:
    return api_error(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, f"contribution {contribution_id} does not exist")


_manage = [Depends(require_permiso(PERMISO_APORTES))]


@router.get("/campaigns", response_model=CampaignsOut)
def get_campaigns(w: Window = Depends(window), db: Session = Depends(get_db)) -> CampaignsOut:
    rows = contributions.list_campaigns(db, w.date_from, w.date_to)
    return CampaignsOut(
        campaigns=[
            CampaignOut(
                advertiser_id=r.campaign.advertiser_id,
                campaign_id=r.campaign.campaign_id,
                advertiser_name=contributions.ADVERTISER_NAMES.get(r.campaign.advertiser_id),
                name=r.campaign.name,
                status=r.campaign.status,
                cost=_money(r.cost),
                contribution=_money(r.contribution),
                contributions=[_contribution_out(c) for c in r.contributions],
            )
            for r in rows
        ]
    )


@router.post("/contributions/preview", response_model=PreviewOut)
def preview_contribution(body: ContributionIn, db: Session = Depends(get_db)) -> PreviewOut:
    result = contributions.preview(db, _data(body))
    return PreviewOut(
        spend=_money(result.spend), counted=_money(result.counted), net=_money(result.spend - result.counted)
    )


@router.post(
    "/contributions", response_model=ContributionOut, status_code=status.HTTP_201_CREATED, dependencies=_manage
)
def create_contribution(
    body: ContributionIn, user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)
) -> ContributionOut:
    try:
        return _contribution_out(contributions.create(db, _data(body), user.id))
    except contributions.ContributionError as exc:
        db.rollback()
        raise _unprocessable(exc.field, str(exc))


@router.put("/contributions/{contribution_id}", response_model=ContributionOut, dependencies=_manage)
def update_contribution(
    contribution_id: int,
    body: ContributionIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ContributionOut:
    try:
        row = contributions.update(db, contribution_id, _data(body), user.id)
    except contributions.ContributionError as exc:
        db.rollback()
        raise _unprocessable(exc.field, str(exc))
    if row is None:
        raise _not_found(contribution_id)
    return _contribution_out(row)


@router.delete("/contributions/{contribution_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_manage)
def delete_contribution(
    contribution_id: int, user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    if not contributions.delete(db, contribution_id, user.id):
        raise _not_found(contribution_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

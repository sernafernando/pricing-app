"""Brand contributions to ads campaigns: reads and writes (ml-ads-brand-contribution S4, S7, S8).

Only stores what the team loads (S2). How a contribution lowers the subtracted cost (S5, S6) is the Board's job; the
loading page's figures (`contribution_in`, `preview`, ml-ads-contribution-redesign S6) repeat the Board's rule over the
same item rows so both show the same amount.

A contribution has a `channel` (ml-ads-display-contributions S2): `product_ads` covers one campaign of
`ml_ads_campaigns` over its item rows (`ml_ads_item_days`); `display` covers one campaign of `ml_ads_display_campaigns`
or, with no campaign, the whole Display account of the advertiser, over its day rows
(`ml_ads_display_campaign_days.consumed_budget`). Both follow the same rules (`percentage` p% of each row,
`fixed_amount` spread by each row's share of the whole range's spend); `display_contributions` is the one place that
computes the Display figure, for the Display tab and for the Board alike.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import String, case, cast, func, or_, tuple_
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.ml_ads import (
    CONTRIBUTION_LIVE,
    MlAdsCampaign,
    MlAdsCampaignContribution,
    MlAdsDayLedger,
    MlAdsDisplayCampaign,
    MlAdsDisplayCampaignDay,
    MlAdsItemDay,
)
from app.models.producto import ProductoERP
from app.models.usuario import Usuario
from app.services.ml_ads.read import COVERED

logger = logging.getLogger(__name__)

# ponytail: advertiser names hardcoded (not stored); persist them from the Ads API when the catalogue sync gains them.
# These are the two advertisers the Ads API lists for the account; any other shows its id.
ADVERTISER_NAMES = {25713: "GAUSS", 714700: "TPLINK"}

PRODUCT_ADS, DISPLAY = "product_ads", "display"


class ContributionError(Exception):
    """A rule the API reports as 422 on `field`."""

    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(message)
        self.field = field_name


@dataclass(frozen=True)
class ContributionData:
    advertiser_id: int
    campaign_id: Optional[int]  # None: the whole Display account (channel `display` only)
    kind: str
    value: Decimal
    date_from: date
    date_to: date
    brand: Optional[str]
    note: Optional[str]
    settlement: Optional[str] = None
    channel: str = PRODUCT_ADS


@dataclass
class CampaignRow:
    campaign: MlAdsCampaign
    cost: Decimal
    contributions: list[MlAdsCampaignContribution] = field(default_factory=list)
    contribution: Decimal = Decimal(0)  # what the contributions cover of the range's cost


@dataclass(frozen=True)
class Preview:
    spend: Decimal  # the campaign's item-row cost over the contribution's range
    counted: Decimal  # what the Board subtracts of it


def list_campaigns(db: Session, date_from: date, date_to: date) -> list[CampaignRow]:
    """Every catalogued campaign with all its contributions (by start) and its cost in `[date_from, date_to]`: its
    item rows, the base the contributions and the Board use (ml-ads-aportes-robust S7), not the campaign report.

    All contributions, not only those touching the range: the loading screen lists them all. The catalogue is only
    ever upserted (nothing deletes from `ml_ads_campaigns`) and writes require a catalogued campaign, so no
    contribution is left without its campaign. Not paginated, like the other `/ml-ads` reads: two advertisers."""
    day = MlAdsItemDay
    sums = (
        db.query(day.advertiser_id, day.campaign_id, func.sum(day.cost))
        .filter(day.day.between(date_from, date_to))
        .group_by(day.advertiser_id, day.campaign_id)
    )
    costs = {(advertiser, campaign): total for advertiser, campaign, total in sums}
    rows = {
        (c.advertiser_id, c.campaign_id): CampaignRow(c, Decimal(costs.get((c.advertiser_id, c.campaign_id)) or 0))
        for c in db.query(MlAdsCampaign).order_by(MlAdsCampaign.advertiser_id, MlAdsCampaign.campaign_id)
    }
    # Product Ads only: a Display campaign id may equal a Product Ads one and must not land on it.
    contributions = (
        db.query(MlAdsCampaignContribution)
        .filter(MlAdsCampaignContribution.channel == PRODUCT_ADS, CONTRIBUTION_LIVE)
        .order_by(MlAdsCampaignContribution.date_from, MlAdsCampaignContribution.id)
        .all()
    )
    daily = _daily_spend(db, contributions)
    for contribution in contributions:
        row = rows.get((contribution.advertiser_id, contribution.campaign_id))
        if row is not None:
            row.contributions.append(contribution)
            row.contribution += contribution_in(daily, contribution, date_from, date_to)
    return list(rows.values())


@dataclass
class ContributionRow:
    """One aporte as the "Por aporte" view lists it (Stitch 55853ac1)."""

    contribution: MlAdsCampaignContribution
    campaign_name: Optional[str]  # None: a campaign the catalog does not name, or the whole Display account
    covered: Decimal  # what it covers of the window, on its channel's rule
    loaded_by: Optional[str]
    loaded_at: datetime
    edited_by: Optional[str] = None
    edited_at: Optional[datetime] = None


@dataclass(frozen=True)
class ContributionsView:
    rows: list[ContributionRow]
    product_ads_cost: Decimal  # every Product Ads item row of the window, with or without campaign
    display_cost: Decimal
    no_campaign_cost: Decimal  # item rows with no campaign (NULL or 0): no aporte can cover them


AUDIT_WRITES = (TipoAccion.ML_ADS_APORTE_CREADO, TipoAccion.ML_ADS_APORTE_EDITADO)


def list_contributions(db: Session, date_from: date, date_to: date) -> ContributionsView:
    """Every live aporte whose range touches `[date_from, date_to]`, by start, with what it covers of the window and
    "Cargado" from its `auditoria` rows (owner: names and dates come from the audit). An aporte loaded before aportes
    were audited has no creation row: its own `created_by_id` / `created_at` stand in."""
    C, item = MlAdsCampaignContribution, MlAdsItemDay
    rows = (
        db.query(C)
        .filter(CONTRIBUTION_LIVE, C.date_from <= date_to, C.date_to >= date_from)
        .order_by(C.date_from, C.id)
        .all()
    )
    product_ads = [r for r in rows if r.channel == PRODUCT_ADS]
    daily = _daily_spend(db, product_ads)
    covered = {r: contribution_in(daily, r, date_from, date_to) for r in product_ads}
    for row, shares in _display_shares(db, [r for r in rows if r.channel == DISPLAY], date_from, date_to).items():
        covered[row] = sum(shares.values(), Decimal(0))
    names = _campaign_names(db, rows)
    audit = _audit_trail(db, [r.id for r in rows])
    users = _user_names(
        db, {r.created_by_id for r in rows} | {uid for trail in audit.values() for _t, uid, _w in trail}
    )
    listed = []
    for row in rows:
        trail = audit.get(row.id, [])
        created = next(((uid, when) for tipo, uid, when in trail if tipo == TipoAccion.ML_ADS_APORTE_CREADO), None)
        edited = next(
            ((uid, when) for tipo, uid, when in reversed(trail) if tipo == TipoAccion.ML_ADS_APORTE_EDITADO), None
        )
        loaded_by, loaded_at = created or (row.created_by_id, row.created_at)
        listed.append(
            ContributionRow(
                contribution=row,
                campaign_name=names.get((row.channel, row.advertiser_id, row.campaign_id)),
                covered=covered.get(row, Decimal(0)),
                loaded_by=users.get(loaded_by),
                loaded_at=loaded_at,
                edited_by=users.get(edited[0]) if edited else None,
                edited_at=edited[1] if edited else None,
            )
        )
    in_window = item.day.between(date_from, date_to)
    no_campaign = or_(item.campaign_id.is_(None), item.campaign_id == 0)
    product_ads_cost, no_campaign_cost = (
        db.query(
            func.coalesce(func.sum(item.cost), 0),
            func.coalesce(func.sum(case((no_campaign, item.cost), else_=0)), 0),
        )
        .filter(in_window)
        .one()
    )
    D = MlAdsDisplayCampaignDay
    display_cost = db.query(func.coalesce(func.sum(D.consumed_budget), 0)).filter(D.day.between(date_from, date_to))
    return ContributionsView(
        rows=listed,
        product_ads_cost=Decimal(str(product_ads_cost)),
        display_cost=Decimal(str(display_cost.scalar())),
        no_campaign_cost=Decimal(str(no_campaign_cost)),
    )


def _campaign_names(db: Session, rows: list[MlAdsCampaignContribution]) -> dict[tuple[str, int, int], str]:
    """(channel, advertiser, campaign) -> catalog name, for the campaigns `rows` name."""
    names: dict[tuple[str, int, int], str] = {}
    for channel, model in ((PRODUCT_ADS, MlAdsCampaign), (DISPLAY, MlAdsDisplayCampaign)):
        keys = {(r.advertiser_id, r.campaign_id) for r in rows if r.channel == channel and r.campaign_id is not None}
        if not keys:
            continue
        found = db.query(model.advertiser_id, model.campaign_id, model.name).filter(
            tuple_(model.advertiser_id, model.campaign_id).in_(keys)
        )
        names.update({(channel, a, c): name for a, c, name in found if name})
    return names


def _audit_trail(db: Session, ids: list[int]) -> dict[int, list[tuple[TipoAccion, int, datetime]]]:
    """aporte id -> its creation and edit audit rows (type, user, when), oldest first. The aporte's id lives in the
    row's `valores_nuevos` (`_snapshot`), as `item_id` holds products."""
    if not ids:
        return {}
    # Compared as text: other audit types may carry a non-numeric "id", and Postgres does not promise to apply the
    # type filter before a cast would run on them.
    aporte_id = cast(Auditoria.valores_nuevos["id"].as_string(), String)
    found = (
        db.query(aporte_id, Auditoria.tipo_accion, Auditoria.usuario_id, Auditoria.fecha)
        .filter(Auditoria.tipo_accion.in_(AUDIT_WRITES), aporte_id.in_([str(i) for i in ids]))
        .order_by(Auditoria.fecha, Auditoria.id)
    )
    trail: dict[int, list[tuple[TipoAccion, int, datetime]]] = {}
    for row_id, tipo, user_id, when in found:
        trail.setdefault(int(row_id), []).append((tipo, user_id, when))
    return trail


HISTORY_ACTIONS = {
    TipoAccion.ML_ADS_APORTE_CREADO: "created",
    TipoAccion.ML_ADS_APORTE_EDITADO: "edited",
    TipoAccion.ML_ADS_APORTE_BORRADO: "deleted",
}


@dataclass(frozen=True)
class HistoryEvent:
    action: str  # created | edited | deleted
    user: Optional[str]
    at: datetime
    before: Optional[dict]
    after: Optional[dict]


def history(db: Session, contribution_id: int) -> Optional[list[HistoryEvent]]:
    """Every audit row of one aporte, deleted ones included, oldest first; None if no such aporte was ever loaded.
    The id sits in `valores_nuevos` (created, edited) or `valores_anteriores` (deleted), compared as text."""
    if db.get(MlAdsCampaignContribution, contribution_id) is None:
        return None
    key = str(contribution_id)
    found = (
        db.query(Auditoria)
        .filter(
            Auditoria.tipo_accion.in_(HISTORY_ACTIONS),
            or_(
                cast(Auditoria.valores_nuevos["id"].as_string(), String) == key,
                cast(Auditoria.valores_anteriores["id"].as_string(), String) == key,
            ),
        )
        .order_by(Auditoria.fecha, Auditoria.id)
        .all()
    )
    users = _user_names(db, {row.usuario_id for row in found})
    return [
        HistoryEvent(
            action=HISTORY_ACTIONS[row.tipo_accion],
            user=users.get(row.usuario_id),
            at=row.fecha,
            before=row.valores_anteriores,
            after=row.valores_nuevos,
        )
        for row in found
    ]


def _user_names(db: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return dict(db.query(Usuario.id, Usuario.nombre).filter(Usuario.id.in_(ids)))


DailySpend = dict[tuple[int, int], dict[date, Decimal]]


def _daily_spend(db: Session, contributions: list[MlAdsCampaignContribution]) -> DailySpend:
    """In one query, the item-row cost per (advertiser, campaign) and day of every campaign with a contribution,
    over the span its contributions cover."""
    if not contributions:
        return {}
    item = MlAdsItemDay
    keys = {(c.advertiser_id, c.campaign_id) for c in contributions}
    rows = (
        db.query(item.advertiser_id, item.campaign_id, item.day, func.sum(item.cost))
        .filter(
            tuple_(item.advertiser_id, item.campaign_id).in_(keys),
            item.day.between(min(c.date_from for c in contributions), max(c.date_to for c in contributions)),
        )
        .group_by(item.advertiser_id, item.campaign_id, item.day)
    )
    daily: DailySpend = {}
    for advertiser, campaign, day, total in rows:
        daily.setdefault((advertiser, campaign), {})[day] = Decimal(total or 0)
    return daily


def _sum_spend(daily: DailySpend, row: MlAdsCampaignContribution, start: date, end: date) -> Decimal:
    days = daily.get((row.advertiser_id, row.campaign_id), {})
    return sum((cost for day, cost in days.items() if start <= day <= end), Decimal(0))


def _spend(db: Session, advertiser_id: int, campaign_id: int, start: date, end: date) -> Decimal:
    """The campaign's Product Ads cost over `[start, end]` on the Board's basis: its item rows."""
    item = MlAdsItemDay
    total = (
        db.query(func.sum(item.cost))
        .filter(item.advertiser_id == advertiser_id, item.campaign_id == campaign_id, item.day.between(start, end))
        .scalar()
    )
    return Decimal(total or 0)


def _counted(kind: str, value: Decimal, settlement: Optional[str], spend: Decimal) -> Decimal:
    """What a contribution covers of a range that spent `spend` (S5, S6): p% of it, or the fixed amount (`full`: all of
    it; `refund_difference`: at most `spend`). A fixed amount needs spend to spread over, as on the Board."""
    if kind == "percentage":
        return spend * value / 100
    if spend <= 0:
        return Decimal(0)
    return value if settlement == "full" else min(value, spend)


def contribution_in(daily: DailySpend, row: MlAdsCampaignContribution, date_from: date, date_to: date) -> Decimal:
    """The part of `row` that falls on `[date_from, date_to]`: a fixed amount reaches the window by the window's share
    of the WHOLE range's spend, like the Board's per-row spread. `daily` comes from `_daily_spend`."""
    start, end = max(row.date_from, date_from), min(row.date_to, date_to)
    if start > end:
        return Decimal(0)
    window = _sum_spend(daily, row, start, end)
    if row.kind == "percentage":
        return _counted(row.kind, Decimal(row.value), None, window)
    spend = _sum_spend(daily, row, row.date_from, row.date_to)
    if spend <= 0:
        return Decimal(0)
    return _counted(row.kind, Decimal(row.value), row.settlement, spend) * window / spend


def _display_spend(db: Session, advertiser_id: int, campaign_id: Optional[int], start: date, end: date) -> Decimal:
    """The Display cost over `[start, end]` of one campaign, or of every campaign of the advertiser (None)."""
    D = MlAdsDisplayCampaignDay
    query = db.query(func.sum(D.consumed_budget)).filter(D.advertiser_id == advertiser_id, D.day.between(start, end))
    if campaign_id is not None:
        query = query.filter(D.campaign_id == campaign_id)
    return Decimal(query.scalar() or 0)


def preview(db: Session, data: ContributionData) -> Preview:
    """What `data` would cover if saved, over its whole range, on its channel's spend. Writes nothing."""
    if data.channel == DISPLAY:
        spend = _display_spend(db, data.advertiser_id, data.campaign_id, data.date_from, data.date_to)
    else:
        spend = _spend(db, data.advertiser_id, data.campaign_id, data.date_from, data.date_to)
    return Preview(spend, _counted(data.kind, data.value, data.settlement, spend))


def display_contributions(db: Session, date_from: date, date_to: date) -> dict[tuple[int, int], Decimal]:
    """What the Display contributions cover of `[date_from, date_to]`, per (advertiser, Display campaign).

    The Board's Product Ads rule over the Display day rows: a contribution matches the rows of its advertiser in its
    range, of its campaign or (whole account) of every campaign. `percentage` covers p% of each row; `fixed_amount`
    spreads its counted amount (`full`: all of it; `refund_difference`: at most the range's spend) by each row's share
    of the WHOLE range's spend, which may reach past the window; a range that spent nothing has nothing to spread
    over. The write API keeps a row from meeting two contributions. Campaigns nothing covers are absent."""
    C = MlAdsCampaignContribution
    rows = (
        db.query(C)
        .filter(C.channel == DISPLAY, CONTRIBUTION_LIVE, C.date_from <= date_to, C.date_to >= date_from)
        .order_by(C.id)
        .all()
    )
    covered: dict[tuple[int, int], Decimal] = {}
    for row, shares in _display_shares(db, rows, date_from, date_to).items():
        for campaign, share in shares.items():
            key = (row.advertiser_id, campaign)
            covered[key] = covered.get(key, Decimal(0)) + share
    return covered


def _display_shares(
    db: Session, rows: list[MlAdsCampaignContribution], date_from: date, date_to: date
) -> dict[MlAdsCampaignContribution, dict[int, Decimal]]:
    """What each Display contribution of `rows` covers of `[date_from, date_to]`, per Display campaign (the rule of
    `display_contributions`). A contribution that covers nothing is absent."""
    if not rows:
        return {}
    D = MlAdsDisplayCampaignDay
    days = (
        db.query(D.advertiser_id, D.campaign_id, D.day, D.consumed_budget)
        .filter(
            D.advertiser_id.in_({r.advertiser_id for r in rows}),
            D.day.between(min(r.date_from for r in rows), max(r.date_to for r in rows)),
        )
        .all()
    )
    result: dict[MlAdsCampaignContribution, dict[int, Decimal]] = {}
    for row in rows:
        matching = [
            (campaign, day, Decimal(cost))
            for advertiser, campaign, day, cost in days
            if advertiser == row.advertiser_id
            and (row.campaign_id is None or campaign == row.campaign_id)
            and row.date_from <= day <= row.date_to
        ]
        window: dict[int, Decimal] = {}
        for campaign, day, cost in matching:
            if date_from <= day <= date_to:
                window[campaign] = window.get(campaign, Decimal(0)) + cost
        value = Decimal(row.value)
        if row.kind == "percentage":
            result[row] = {campaign: _counted(row.kind, value, None, cost) for campaign, cost in window.items()}
            continue
        spend = sum((cost for _campaign, _day, cost in matching), Decimal(0))
        if spend <= 0:
            continue
        counted = _counted(row.kind, value, row.settlement, spend)
        result[row] = {campaign: counted * cost / spend for campaign, cost in window.items()}
    return result


def _lock_product_ads_campaign(db: Session, data: ContributionData) -> None:
    """The Product Ads campaign is catalogued; its row is locked so two writes on one campaign serialize."""
    campaign = None
    if data.campaign_id is not None:
        campaign = (
            db.query(MlAdsCampaign)
            .filter(MlAdsCampaign.advertiser_id == data.advertiser_id, MlAdsCampaign.campaign_id == data.campaign_id)
            .with_for_update()
            .first()
        )
    if campaign is None:
        raise ContributionError(
            "campaign_id", f"campaign {data.campaign_id} of advertiser {data.advertiser_id} is unknown"
        )


def _lock_display_account(db: Session, data: ContributionData) -> None:
    """The Display campaign (or, without one, the advertiser's Display account) is catalogued.

    Every Display write of an advertiser locks ALL of that advertiser's `ml_ads_display_campaigns` rows, in
    campaign order (no deadlock between two writers), whether it covers one campaign or the whole account: a
    whole-account write and a campaign write of the same advertiser must serialize, and locking only the campaign row
    would not stop a concurrent whole-account one. The catalog is only ever upserted (never deleted), so the rows an
    earlier write locked are among those any later write locks: two writes always share a locked row. The catalog of
    one advertiser holds a handful of campaigns."""
    catalog = (
        db.query(MlAdsDisplayCampaign.campaign_id)
        .filter(MlAdsDisplayCampaign.advertiser_id == data.advertiser_id)
        .order_by(MlAdsDisplayCampaign.campaign_id)
        .with_for_update()
        .all()
    )
    ids = {campaign_id for (campaign_id,) in catalog}
    if data.campaign_id is None and not ids:
        raise ContributionError("campaign_id", f"advertiser {data.advertiser_id} has no Display campaigns")
    if data.campaign_id is not None and data.campaign_id not in ids:
        raise ContributionError(
            "campaign_id", f"Display campaign {data.campaign_id} of advertiser {data.advertiser_id} is unknown"
        )


def _check(db: Session, data: ContributionData, exclude_id: Optional[int] = None) -> None:
    """The campaign is in its channel's catalog (locked, see the `_lock_*` helpers) and no other contribution that
    covers the same spend shares a day with `[date_from, date_to]` (both ends inclusive).

    The same spend: on Product Ads, the same campaign. On Display, the same campaign or the advertiser's whole
    account: a whole-account range clashes with every Display range of the advertiser, a campaign range with that
    campaign's and with the whole-account ones. Channels never clash with each other (a Display campaign id may
    equal a Product Ads one)."""
    C = MlAdsCampaignContribution
    clash = db.query(C.id).filter(
        CONTRIBUTION_LIVE,
        C.advertiser_id == data.advertiser_id,
        C.channel == data.channel,
        C.date_from <= data.date_to,
        C.date_to >= data.date_from,
    )
    if data.channel == DISPLAY:
        _lock_display_account(db, data)
        if data.campaign_id is not None:
            clash = clash.filter(or_(C.campaign_id == data.campaign_id, C.campaign_id.is_(None)))
        message = "the range overlaps another Display contribution covering the same spend (the campaign or the whole account)"
    else:
        _lock_product_ads_campaign(db, data)
        clash = clash.filter(C.campaign_id == data.campaign_id)
        message = "the range overlaps another contribution of the same campaign"
    if exclude_id is not None:
        clash = clash.filter(C.id != exclude_id)
    if clash.first() is not None:
        raise ContributionError("date_from", message)


def _catalog_brand(db: Session, brand: Optional[str]) -> str:
    """The brand as the marcas catalog spells it (ml-ads-aportes-robust S1): mandatory, matched without case or
    surrounding spaces against the distinct `ProductoERP.marca` (what `GET /marcas` lists), as sell-in bonuses do."""
    typed = (brand or "").strip()
    if not typed:
        raise ContributionError("brand", "the brand is mandatory; pick it from the brand list")
    found = (
        db.query(ProductoERP.marca)
        .filter(func.upper(func.trim(ProductoERP.marca)) == typed.upper())
        .order_by(ProductoERP.marca)
        .limit(1)
        .scalar()
    )
    if found is None:
        raise ContributionError("brand", f"there are no products of the brand {typed}; pick it from the brand list")
    return found.strip()


def exceeds_spend(data: ContributionData, spend: Decimal) -> bool:
    """A `full` amount above its range's spend (none spent yet included) leaves a negative net (S3)."""
    return data.kind == "fixed_amount" and data.settlement == "full" and data.value > spend


def _check_spend(db: Session, data: ContributionData, confirmed: bool) -> None:
    """Such an amount is saved only when confirmed, and the 422 says the spend."""
    if confirmed:
        return
    spend = preview(db, data).spend
    if not exceeds_spend(data, spend):
        return
    raise ContributionError(
        "value",
        f"the amount is above the range spend of {spend:.2f}, so the net goes negative; confirm to load it anyway",
    )


def data_through(db: Session, channel: str, advertiser_id: int) -> Optional[date]:
    """The last day D such that the advertiser's ledger of `channel` is closed (or mismatch) every day from its oldest
    ledgered day through D; None while nothing is closed."""
    L = MlAdsDayLedger
    days = {
        day
        for (day,) in db.query(L.day).filter(
            L.source == channel, L.advertiser_id == advertiser_id, L.status.in_(COVERED)
        )
    }
    if not days:
        return None
    through = min(days)
    while through + timedelta(days=1) in days:
        through += timedelta(days=1)
    return through


def save_warnings(db: Session, data: ContributionData, through: Optional[date] = None) -> list[str]:
    """What to tell whoever saves `data` without stopping them (S4): a range ending after the ads data loaded so far.
    `through` is `data_through` when the caller already has it; otherwise it is read here."""
    through = through or data_through(db, data.channel, data.advertiser_id)
    if through is None or data.date_to <= through:
        return []
    return [
        f"the range ends after {through.isoformat()}, the last day with ads data: its figures will change as the "
        "missing days arrive"
    ]


def _locked(db: Session, contribution_id: int) -> Optional[MlAdsCampaignContribution]:
    """The live contribution row under FOR UPDATE, taken before the campaign lock so edit and delete serialize. A
    soft-deleted one is `None`, as if it did not exist."""
    return (
        db.query(MlAdsCampaignContribution)
        .filter(MlAdsCampaignContribution.id == contribution_id, CONTRIBUTION_LIVE)
        .with_for_update()
        .one_or_none()
    )


def _snapshot(row: MlAdsCampaignContribution) -> dict:
    """What an audit row keeps of an aporte (S5): every field a person loads, JSON-safe."""
    return {
        "id": row.id,
        "channel": row.channel,
        "advertiser_id": row.advertiser_id,
        "campaign_id": row.campaign_id,
        "kind": row.kind,
        "value": f"{Decimal(row.value):.2f}",
        "date_from": row.date_from.isoformat(),
        "date_to": row.date_to.isoformat(),
        "settlement": row.settlement,
        "brand": row.brand,
        "note": row.note,
    }


def _audit(db: Session, tipo: TipoAccion, user_id: int, before: Optional[dict], after: Optional[dict]) -> None:
    """One `auditoria` row in the caller's transaction (as sell-in bonuses do: `registrar_auditoria` commits on its
    own, which would split the change from its record)."""
    db.add(
        Auditoria(
            item_id=None,
            usuario_id=user_id,
            tipo_accion=tipo,
            valores_anteriores=before,
            valores_nuevos=after,
            fecha=datetime.now(timezone.utc).replace(tzinfo=None),  # naive UTC, like the column's default
        )
    )


def _apply(row: MlAdsCampaignContribution, data: ContributionData, user_id: int) -> None:
    for name, value in vars(data).items():
        setattr(row, name, value)
    row.updated_by_id = user_id


def _validated(db: Session, data: ContributionData, confirmed: bool) -> ContributionData:
    data = dataclasses.replace(data, brand=_catalog_brand(db, data.brand))
    _check_spend(db, data, confirmed)
    return data


def create(
    db: Session, data: ContributionData, user_id: int, *, confirm_over_spend: bool = False
) -> MlAdsCampaignContribution:
    data = _validated(db, data, confirm_over_spend)
    _check(db, data)
    row = MlAdsCampaignContribution(created_by_id=user_id)
    _apply(row, data, user_id)
    db.add(row)
    db.flush()  # the id the audit row names
    _audit(db, TipoAccion.ML_ADS_APORTE_CREADO, user_id, None, _snapshot(row))
    db.commit()
    db.refresh(row)
    return row


def update(
    db: Session, contribution_id: int, data: ContributionData, user_id: int, *, confirm_over_spend: bool = False
) -> Optional[MlAdsCampaignContribution]:
    """`None` when the contribution does not exist (also when a concurrent delete wins the row lock)."""
    row = _locked(db, contribution_id)
    if row is None:
        return None
    if row.channel != data.channel:
        raise ContributionError("channel", "a contribution cannot move to another channel; delete it and load it again")
    if (row.advertiser_id, row.campaign_id) != (data.advertiser_id, data.campaign_id):
        raise ContributionError(
            "campaign_id", "a contribution cannot move to another campaign; delete it and load it again"
        )
    data = _validated(db, data, confirm_over_spend)
    _check(db, data, exclude_id=contribution_id)
    before = _snapshot(row)
    _apply(row, data, user_id)
    _audit(db, TipoAccion.ML_ADS_APORTE_EDITADO, user_id, before, _snapshot(row))
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, contribution_id: int, user_id: int) -> bool:
    """A soft delete (S6): the row stays, marked with who removed it and when, and every read ignores it from then
    on; its `auditoria` row (S5) and the log line keep what it was."""
    row = _locked(db, contribution_id)
    if row is None:
        return False
    logger.info(
        "ml-ads contribution %s deleted by user %s: %s advertiser %s campaign %s %s %s %s..%s",
        row.id,
        user_id,
        row.channel,
        row.advertiser_id,
        row.campaign_id,
        row.kind,
        row.value,
        row.date_from,
        row.date_to,
    )
    _audit(db, TipoAccion.ML_ADS_APORTE_BORRADO, user_id, _snapshot(row), None)
    # An explicit UPDATE that sets `updated_at` to itself: the model's `onupdate` would otherwise stamp the deletion
    # time on it, and `updated_at` / `updated_by_id` must keep describing the last edit.
    C = MlAdsCampaignContribution
    db.query(C).filter(C.id == row.id).update(
        {C.deleted_at: datetime.now(timezone.utc), C.deleted_by_id: user_id, C.updated_at: C.updated_at},
        synchronize_session=False,
    )
    db.commit()
    return True

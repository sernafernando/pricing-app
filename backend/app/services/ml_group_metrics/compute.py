"""Group-level Gauss metrics compute (ventas-ml-rediseno PR20.T7/T8, design
D7, spec `ml-order-stored-metrics` R9/R10, `ml-sales-kpi-aggregation` R18-R20).

`recompute_group_metrics` is the SINGLE producer of `GroupMetrics`: for
each `group_key` it reads the group's CURRENT membership from
`ml_orders_ops` (never a cached member list -- a member can have changed
pack since the group was last computed), sums the per-member stored values
all-or-nothing (reusing `aggregate_pack_metrics`'s core --
`ml_ventas_desglose/pack_aggregation.py` -- so there is only ONE summation
formula), and derives `gauss_status` via `group_gauss_status`.

A group with any member that is not resolved (no stored row yet, a dirty
row pending recompute, or parked) is STORED as `gauss_status='unresolved'`
with every numeric field `None` -- NEVER a partial sum over the members
that happen to be ready (SM R10, KPI R19). `group_gauss_status` has a wider
per-member vocabulary (`recalculating`, `failed`), but the stored column is
CHECK-constrained to ('ok', 'provisional', 'unresolved'), so those collapse
to `unresolved` here; the WHY stays derivable from the per-member queue
state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.ml_orders_ops import MlOrdersOps
from app.services.ml_group_metrics.state import group_gauss_status
from app.services.ml_sales_query.accreditation import member_accreditation_dates
from app.services.ml_ventas_desglose.pack_aggregation import sum_all_or_nothing
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION
from app.services.order_metrics.read import metrics_state_for_orders, read_stored_metrics


@dataclass(frozen=True)
class GroupMetrics:
    """One group's computed Gauss metrics -- the return value of
    `recompute_group_metrics`, consumed by `store.store_group_metrics`."""

    group_key: str
    neto: Optional[Decimal]
    neto_sin_iva: Optional[Decimal]
    costo_mercaderia: Optional[Decimal]
    total_gauss: Optional[Decimal]
    markup_pct: Optional[Decimal]
    gauss_status: str
    gross_amount: Optional[Decimal] = None
    currency_id: Optional[str] = None
    member_order_ids: List[int] = field(default_factory=list)
    group_date: Optional[datetime] = None
    formula_version: int = CURRENT_FORMULA_VERSION
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _parse_group_key(group_key: str) -> tuple[str, int]:
    """`"p:<pack_id>"` / `"o:<order_id>"` -- the exact format
    `_group_key_expr()` produces (`ml_sales_query/filters.py`)."""
    kind, _, raw_id = group_key.partition(":")
    if kind not in ("p", "o") or not raw_id:
        raise ValueError(f"malformed group_key: {group_key!r}")
    return kind, int(raw_id)


def _members_by_group(db: Session, group_keys: Sequence[str]) -> Dict[str, List[int]]:
    """Current membership of EVERY requested group, in two queries total.

    Deliberately not one query per group: the hook in `store_order_metrics`
    almost always passes a single group, but `backfill_ml_group_metrics`
    passes 500 at a time, and a per-group read there is a textbook N+1 --
    around 3,500 round trips per batch.

    A `"o:<id>"` group whose order has since JOINED a pack comes back empty,
    exactly as before: that order is no longer this group's member (the
    caller's orphan cleanup handles the transition), and
    `recompute_group_metrics` only ever reports what is CURRENTLY true.
    """
    pack_ids: List[int] = []
    standalone_ids: List[int] = []
    for group_key in group_keys:
        kind, group_id = _parse_group_key(group_key)
        (pack_ids if kind == "p" else standalone_ids).append(group_id)

    result: Dict[str, List[int]] = {key: [] for key in group_keys}

    if pack_ids:
        filas = db.query(MlOrdersOps.pack_id, MlOrdersOps.order_id).filter(MlOrdersOps.pack_id.in_(pack_ids)).all()
        for pack_id, order_id in filas:
            result["p:" + str(pack_id)].append(order_id)

    if standalone_ids:
        filas = (
            db.query(MlOrdersOps.order_id)
            .filter(MlOrdersOps.order_id.in_(standalone_ids), MlOrdersOps.pack_id.is_(None))
            .all()
        )
        for (order_id,) in filas:
            result["o:" + str(order_id)].append(order_id)

    for miembros in result.values():
        miembros.sort()
    return result


@dataclass(frozen=True)
class _OrderFacts:
    """The `ml_orders_ops` columns the group-level fields are derived from."""

    total_amount: Optional[Decimal]
    currency_id: Optional[str]
    date_created: Optional[datetime]


def _order_facts(db: Session, order_ids: Sequence[int]) -> Dict[int, _OrderFacts]:
    """One query for every member of every group in the batch -- see
    `_members_by_group` for why this is not done per group."""
    if not order_ids:
        return {}
    filas = (
        db.query(
            MlOrdersOps.order_id,
            MlOrdersOps.total_amount,
            MlOrdersOps.currency_id,
            MlOrdersOps.date_created,
        )
        .filter(MlOrdersOps.order_id.in_(list(order_ids)))
        .all()
    )
    return {
        row.order_id: _OrderFacts(
            total_amount=row.total_amount,
            currency_id=row.currency_id,
            date_created=row.date_created,
        )
        for row in filas
    }


def _group_date(accreditation_by_order: Dict[int, datetime], member_order_ids: Sequence[int]) -> Optional[datetime]:
    """Group-level date (ODD `ventas-ml-dia-por-acreditacion`, 2026-09-30):
    the MAX accreditation date across the group's current members -- the
    LAST payment to land, because that is when the whole pack can ship
    (a pack cannot ship until every member is paid). A pack straddling a
    date-filter boundary is included/excluded as ONE whole pack, never
    split (unchanged from the old PR20.T24/T25 contract; only the basis
    changed from `date_created` MIN to accreditation MAX -- see
    `ml_sales_query/accreditation.py`'s module docstring for why MIN there
    and MAX here are NOT the same question).

    `accreditation_by_order` comes from `member_accreditation_dates` (the
    single resolver, bulk-fetched once for the whole batch by the caller).
    A member with NO relevant accredited payment is simply absent from that
    dict and skipped here -- never treated as the maximum, and a group
    where EVERY member is absent gets `None` (no day), matching "a sale
    with no accredited money is in no day".
    """
    fechas = [accreditation_by_order[order_id] for order_id in member_order_ids if order_id in accreditation_by_order]
    return max(fechas) if fechas else None


def _gross_amount(
    facts: Dict[int, _OrderFacts], member_order_ids: Sequence[int]
) -> tuple[Optional[Decimal], Optional[str]]:
    """The group's gross billed and the currency it is expressed in.

    BOTH are `None` unless every member shares ONE currency and every
    member's `total_amount` is known. That is the same rule `listar_ventas`
    applies to a pack row, and its comment gives the reason better than this
    one could: adding ARS to USD produces a number that means nothing, and a
    mixed pack rendering a numeric amount beside an honest null would read as
    MORE trustworthy than the null, not less.

    Returning the pair together is deliberate: an amount without its currency
    is exactly the misleading value the gate exists to prevent, so there is no
    way to get one without the other.
    """
    if not member_order_ids or any(order_id not in facts for order_id in member_order_ids):
        return None, None

    monedas = {facts[order_id].currency_id for order_id in member_order_ids}
    if len(monedas) != 1 or None in monedas:
        return None, None

    montos = [facts[order_id].total_amount for order_id in member_order_ids]
    if any(monto is None for monto in montos):
        return None, None

    return sum(Decimal(str(monto)) for monto in montos), monedas.pop()


# Namespace for `pg_advisory_xact_lock`'s two-argument form, so these locks
# cannot collide with any other advisory lock in the application. Arbitrary
# but FIXED: changing it while workers are running would let an old and a new
# process hold what they each think is the same group's lock.
_ADVISORY_LOCK_NAMESPACE = 0x6D676D74  # "mgmt" -- ml_group_metrics


def _lock_group(db: Session, group_key: str) -> None:
    """Serializes concurrent recomputes of ONE group, for the duration of the
    caller's transaction.

    THE RACE IT CLOSES: two workers storing two members of the same pack in
    overlapping transactions each read the OTHER member as still dirty --
    true in its own snapshot, since the other has not committed -- so both
    write the group as `unresolved`. Both then commit and NOTHING is left
    dirty: no sibling to enqueue, no retry, no reconcile pass that covers a
    group row. The pedido keeps a null amount forever although both its
    members resolved fine, until some unrelated future write to one of them
    happens to fix it by accident.

    `pg_advisory_xact_lock` makes the second transaction wait for the first
    to COMMIT. Its next statement then reads at a fresh snapshot (READ
    COMMITTED), sees the sibling's stored row and its deleted dirty row, and
    computes `ok`. The lock is released by the commit or rollback itself, so
    there is nothing to leak on a crash.

    Taken in SORTED `group_key` order by the caller's loop, so two
    transactions covering overlapping sets of groups queue instead of
    deadlocking -- the same rule `store_order_metrics` already follows for
    its row upserts.

    SQLite has no advisory locks and no concurrent writers to protect
    against (single-writer), so there it is a no-op rather than an error.
    """
    # `get_bind()`, like every other dialect check in this package
    # (`ml_group_metrics/store.py`, `order_metrics/store.py`). `db.bind` is
    # only set when the session was built with an explicit bind; on any other
    # session it is None, and this function would then return WITHOUT taking
    # the lock and without saying so -- quietly reopening the race it exists
    # to close.
    if db.get_bind().dialect.name != "postgresql":
        return
    # Two-argument form, NOT `pg_advisory_xact_lock(hashtext(...))`. The
    # single-argument form shares one 64-bit keyspace with every other
    # advisory lock in the application, so an unrelated lock that happens to
    # hash to the same number would make these transactions wait on each
    # other for no reason. The first argument namespaces this lock to group
    # metrics; only the second varies per group.
    db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, hashtext(:k))"),
        {"ns": _ADVISORY_LOCK_NAMESPACE, "k": group_key},
    )


def recompute_group_metrics(
    db: Session,
    group_keys: Sequence[str],
    *,
    just_stored_order_ids: Optional[Sequence[int]] = None,
) -> Dict[str, GroupMetrics]:
    """Computes `GroupMetrics` for every `group_key` in `group_keys`. A
    `group_key` whose current membership is empty (the group no longer
    exists -- SM R14) is simply ABSENT from the result, never a fabricated
    empty-group record; the caller (T22e's orphan cleanup) is responsible
    for deleting any existing stored row in that case.

    `just_stored_order_ids` names members whose metrics THIS TRANSACTION has
    already written and whose dirty row has not been deleted yet -- see
    `metrics_state_for_orders`. Only the group hook in `store_order_metrics`
    passes it; every other caller leaves it empty and reads the queue as is."""
    result: Dict[str, GroupMetrics] = {}
    recien_guardados = set(just_stored_order_ids or ())
    now = datetime.now(timezone.utc)

    # Sorted here, not trusted from the caller: the lock below only prevents
    # deadlocks if every transaction takes its group locks in one order.
    claves = sorted(set(group_keys))
    for group_key in claves:
        _lock_group(db, group_key)

    # Everything the loop below needs, read ONCE for the whole batch. The
    # locks above are already held, so nothing can change underneath between
    # this prefetch and the rows it produces.
    members_by_group = _members_by_group(db, claves)
    todos_los_miembros = sorted({oid for miembros in members_by_group.values() for oid in miembros})
    facts = _order_facts(db, todos_los_miembros)
    accreditation_by_order = member_accreditation_dates(db, todos_los_miembros)
    estados = metrics_state_for_orders(db, todos_los_miembros, ignore_dirty_order_ids=recien_guardados)
    almacenados = read_stored_metrics(db, todos_los_miembros)

    for group_key in claves:
        member_order_ids = members_by_group.get(group_key) or []
        if not member_order_ids:
            continue

        # `estados` only carries entries for order_ids resolvable by
        # `metrics_state_for_orders` (it defaults every requested id to
        # 'pending' when it has neither a dirty nor a stored row -- see
        # its own loop) -- request every member explicitly so a truly
        # unseen member still resolves to 'pending', not a KeyError.
        member_states = [estados.get(order_id, "pending") for order_id in member_order_ids]
        gauss_status = group_gauss_status(member_states)

        if gauss_status in ("unresolved", "recalculating", "failed"):
            # `ml_group_metrics.gauss_status` is CHECK-constrained to
            # ('ok', 'provisional', 'unresolved') -- the SAME narrower
            # vocabulary as `ml_order_metrics.gauss_status`. `recalculating`
            # and `failed` are `group_gauss_status`'s own (wider) return
            # values, mirroring `metrics_state_for_orders`'s per-order
            # vocabulary; they collapse to the stored column's 'unresolved'
            # here -- the WHY a group is not resolvable lives in the
            # per-member dirty-queue state a future reader can still derive
            # on demand, never a fabricated numeric value either way.
            result[group_key] = GroupMetrics(
                group_key=group_key,
                neto=None,
                neto_sin_iva=None,
                costo_mercaderia=None,
                total_gauss=None,
                markup_pct=None,
                gauss_status="unresolved",
                member_order_ids=member_order_ids,
                group_date=_group_date(accreditation_by_order, member_order_ids),
                computed_at=now,
            )
            continue

        stored_by_order = {oid: almacenados[oid] for oid in member_order_ids if oid in almacenados}
        total_gauss = sum_all_or_nothing([m.total_gauss for m in stored_by_order.values()])
        costo_mercaderia = sum_all_or_nothing([m.costo_mercaderia for m in stored_by_order.values()])
        neto = sum_all_or_nothing([m.neto for m in stored_by_order.values()])
        neto_sin_iva = sum_all_or_nothing([m.neto_sin_iva for m in stored_by_order.values()])

        gross_amount, currency_id = _gross_amount(facts, member_order_ids)

        markup_pct: Optional[Decimal] = None
        if total_gauss is not None and costo_mercaderia is not None and costo_mercaderia != 0:
            markup_pct = (total_gauss / costo_mercaderia) * Decimal("100")

        result[group_key] = GroupMetrics(
            group_key=group_key,
            neto=neto,
            neto_sin_iva=neto_sin_iva,
            costo_mercaderia=costo_mercaderia,
            total_gauss=total_gauss,
            markup_pct=markup_pct,
            gauss_status=gauss_status,
            gross_amount=gross_amount,
            currency_id=currency_id,
            member_order_ids=member_order_ids,
            group_date=_group_date(accreditation_by_order, member_order_ids),
            computed_at=now,
        )

    return result

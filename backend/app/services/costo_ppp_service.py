"""
PPP (precio ponderado promedio / ERP weighted-average cost) resolver and
per-product markup accumulator for the Productos listing.

This module is display-only: it never touches selling prices, stored
`ProductoPricing` columns, SQL filters, or sort keys. It surfaces
`it_priceofcostpp` (already expressed in ARS) as informational data, plus
markups derived from it via the existing `calcular_markup(limpio, costo)`
formula.

Row selection rule (see openspec/changes/productos-costo-ppp/specs.md):
    it_priceofcostpp > 0
    AND it_cancelled = false
    AND it_exchangetobranchcurrency IS NOT NULL
    AND rmah_id IS NULL
    AND it_isrmasuppliercreditnote = false
    ORDER BY it_cd DESC
    LIMIT 1 per item_id

Performance note (production EXPLAIN ANALYZE, 2026-07-27, with the
`ix_tit_item_cd_desc ON tb_item_transactions (item_id, it_cd DESC)` index in
place — see the migration in this same PR):
    ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY it_cd DESC), filtered to
    rn = 1 (the original implementation), forces PostgreSQL to materialise
    every row of every item_id before discarding all but one:
        900 item_ids -> 158 ms, `Sort Method: external merge  Disk: 3832kB`,
                         112,809 rows read to return 316
        50  item_ids ->  47 ms
    A `LATERAL` join with `ORDER BY it_cd DESC LIMIT 1` per item_id lets the
    planner stop at the first qualifying row per item_id via an index scan,
    with no sort step at all:
        900 item_ids -> 2.2 ms (Nested Loop + Index Scan on
                         `ix_tit_item_cd_desc`, no sort)
        50  item_ids -> 0.3 ms
    ~70x faster, and the difference is structural, not incidental: no index
    fixes ROW_NUMBER, because it must still materialise+discard every row
    before it can pick the winner. This resolver therefore uses LATERAL when
    running against PostgreSQL.

Portability note: LATERAL joins with per-row `ORDER BY ... LIMIT 1` are not
supported by SQLite, which the broader backend test suite still uses as its
default in-memory test DB (`ENVIRONMENT=testing
DATABASE_URL=sqlite:///./test.db`, see `backend/tests/conftest.py`). To avoid
forcing the entire ~3700-test suite onto PostgreSQL, this resolver detects the
bound engine's dialect and falls back to the previous portable
`ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY it_cd DESC)` window
function (filtered to `rn = 1`) on any non-PostgreSQL dialect. Both paths
implement the exact same "latest qualifying row per item_id" semantics; only
PostgreSQL — the real production engine — gets the LATERAL fast path. The
resolver's own tests that must prove the LATERAL path exercises the intended
plan run against a real PostgreSQL instance (`@pytest.mark.postgres`, see
`backend/tests/unit/test_costo_ppp_service.py` and the `postgres` service in
`.github/workflows/ci.yml`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy import and_, func, select, true
from sqlalchemy.orm import Session

from app.models.item_transaction import ItemTransaction
from app.schemas.costo_ppp import PppPayload
from app.services.pricing_calculator import calcular_markup

# SQLite's default `SQLITE_MAX_VARIABLE_NUMBER` is 999; PostgreSQL's parameter
# limit is 65535. `batch_colores` (app/api/endpoints/productos_shared.py) chunks
# at the same size for the same reason — keep both in sync if this changes.
_IN_CHUNK_SIZE = 900


@dataclass(frozen=True)
class PppSource:
    """One resolved PPP source row for a single item_id."""

    costo_ppp: float
    costo_ppp_fecha: date


def resolver_ppp_batch(db: Session, item_ids: list[int]) -> dict[int, PppSource]:
    """Resolve the latest qualifying PPP row per item_id, in ONE query.

    Args:
        db: Active SQLAlchemy session (main application DB).
        item_ids: item_ids to resolve for (typically the current page).

    Returns:
        {item_id: PppSource(costo_ppp, costo_ppp_fecha)}. Items with no
        qualifying row are ABSENT from the dict — callers MUST treat a
        missing key as "no PPP data" and MUST NEVER fall back to the list
        cost. This function never raises for empty input; it returns {}.
    """
    if not item_ids:
        return {}

    result: dict[int, PppSource] = {}
    is_postgres = db.bind is not None and db.bind.dialect.name == "postgresql"

    # Chunk item_ids to stay under SQLite's 999-variable limit / PostgreSQL's
    # 65535-param limit (same pattern as `batch_colores` in productos_shared.py).
    for start in range(0, len(item_ids), _IN_CHUNK_SIZE):
        chunk = item_ids[start : start + _IN_CHUNK_SIZE]

        stmt = _build_lateral_stmt(chunk) if is_postgres else _build_row_number_stmt(chunk)

        for item_id, it_priceofcostpp, it_cd in db.execute(stmt).all():
            if it_priceofcostpp is None or it_cd is None:
                continue
            fecha = it_cd.date() if isinstance(it_cd, datetime) else it_cd
            result[item_id] = PppSource(costo_ppp=float(it_priceofcostpp), costo_ppp_fecha=fecha)

    return result


def _qualifying_predicate(item_id_col):
    """Shared row-selection predicate, parameterised over the item_id column."""
    return and_(
        item_id_col,
        ItemTransaction.it_priceofcostpp > 0,
        ItemTransaction.it_cancelled.is_(False),
        ItemTransaction.it_exchangetobranchcurrency.isnot(None),
        ItemTransaction.rmah_id.is_(None),
        ItemTransaction.it_isrmasuppliercreditnote.is_(False),
    )


def _build_lateral_stmt(chunk: list[int]):
    """PostgreSQL fast path: one LATERAL "latest qualifying row" join per item_id.

    `unnest(:chunk)` produces one row per requested item_id; the LATERAL
    subquery is correlated to that row's item_id and picks the single
    qualifying transaction with the highest `it_cd` via `ORDER BY ... LIMIT
    1`, letting the planner use `ix_tit_item_cd_desc` as an index scan instead
    of materialising and ranking every row (see module docstring).
    """
    item_id_seq = func.unnest(chunk).table_valued("item_id", name="ids").render_derived()

    latest = (
        select(
            ItemTransaction.it_priceofcostpp.label("it_priceofcostpp"),
            ItemTransaction.it_cd.label("it_cd"),
        )
        .where(_qualifying_predicate(ItemTransaction.item_id == item_id_seq.c.item_id))
        .order_by(ItemTransaction.it_cd.desc())
        .limit(1)
        .lateral()
    )

    return select(item_id_seq.c.item_id, latest.c.it_priceofcostpp, latest.c.it_cd).select_from(
        item_id_seq.join(latest, true())
    )


def _build_row_number_stmt(chunk: list[int]):
    """Portable fallback (SQLite and any other non-PostgreSQL dialect).

    Uses `ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY it_cd DESC)`,
    filtered to `rn = 1` in the outer query. Same "latest qualifying row per
    item_id" semantics as `_build_lateral_stmt`, just without the LATERAL
    fast path (see module docstring's portability note).
    """
    row_number_col = (
        func.row_number()
        .over(
            partition_by=ItemTransaction.item_id,
            order_by=ItemTransaction.it_cd.desc(),
        )
        .label("rn")
    )

    ranked = (
        select(
            ItemTransaction.item_id.label("item_id"),
            ItemTransaction.it_priceofcostpp.label("it_priceofcostpp"),
            ItemTransaction.it_cd.label("it_cd"),
            row_number_col,
        )
        .where(_qualifying_predicate(ItemTransaction.item_id.in_(chunk)))
        .subquery()
    )

    return select(ranked.c.item_id, ranked.c.it_priceofcostpp, ranked.c.it_cd).where(ranked.c.rn == 1)


class PppMarkups:
    """Per-product accumulator turning `limpio` values into PPP markups.

    One instance per product. The PPP source (and its date) are fixed at
    construction from a single `Optional[PppSource]` — this makes "no
    qualifying PPP row" and "a qualifying row with a fecha" the only two
    reachable states; `costo_ppp` set with `costo_ppp_fecha=None` is not
    representable, so `payload()` can never attempt to build a `PppPayload`
    with a `None` `fecha` (which is non-optional and would raise a
    `ValidationError`/500). `.record(...)` is called once per existing markup
    site with that site's already-computed `limpio`. `.payload()` returns
    `None` for the WHOLE object when there is no source, so no call site can
    ever construct a partial payload for a product with no qualifying PPP row.
    """

    def __init__(self, source: Optional["PppSource"]) -> None:
        self._costo_ppp = source.costo_ppp if source else None
        self._costo_ppp_fecha = source.costo_ppp_fecha if source else None
        self._markups: dict[str, float] = {}

    def record(self, key: str, limpio: float, *, percent: bool = True) -> None:
        """Record one PPP markup. No-op when there is no qualifying PPP cost.

        Args:
            key: markup key (mirrors the frontend `markupKey`).
            limpio: the already-computed `limpio` value from the shadowed
                    list-cost markup site.
            percent: when True (default), scale/round like the majority of
                     existing sites (`* 100`, rounded to 2 decimals). Pass
                     `percent=False` for sites that keep the raw decimal
                     ratio (e.g. `mejor_oferta_markup`), to match the site
                     it shadows.
        """
        if self._costo_ppp is None:
            return
        raw = calcular_markup(limpio, self._costo_ppp)
        self._markups[key] = round(raw * 100, 2) if percent else raw

    def payload(self) -> Optional[PppPayload]:
        if self._costo_ppp is None:
            return None
        return PppPayload(
            costo=self._costo_ppp,
            fecha=self._costo_ppp_fecha,
            markups=dict(self._markups),
        )

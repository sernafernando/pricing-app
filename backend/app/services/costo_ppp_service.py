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

Portability note: the original design considered PostgreSQL's `DISTINCT ON
(item_id)`. That construct is PostgreSQL-only and fails under the SQLite test
DB used by CI (`ENVIRONMENT=testing DATABASE_URL=sqlite:///./test.db`). This
resolver instead uses a portable `ROW_NUMBER() OVER (PARTITION BY item_id
ORDER BY it_cd DESC)` window function, which both PostgreSQL and SQLite
(>= 3.25) support, filtering to `rn = 1` in the outer query. This produces
the exact same "latest qualifying row per item_id" semantics on both engines
and does not change the row-selection contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy import and_, func, select
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

    row_number_col = (
        func.row_number()
        .over(
            partition_by=ItemTransaction.item_id,
            order_by=ItemTransaction.it_cd.desc(),
        )
        .label("rn")
    )

    result: dict[int, PppSource] = {}

    # Chunk item_ids to stay under SQLite's 999-variable limit / PostgreSQL's
    # 65535-param limit (same pattern as `batch_colores` in productos_shared.py).
    for start in range(0, len(item_ids), _IN_CHUNK_SIZE):
        chunk = item_ids[start : start + _IN_CHUNK_SIZE]

        ranked = (
            select(
                ItemTransaction.item_id.label("item_id"),
                ItemTransaction.it_priceofcostpp.label("it_priceofcostpp"),
                ItemTransaction.it_cd.label("it_cd"),
                row_number_col,
            )
            .where(
                and_(
                    ItemTransaction.item_id.in_(chunk),
                    ItemTransaction.it_priceofcostpp > 0,
                    ItemTransaction.it_cancelled.is_(False),
                    ItemTransaction.it_exchangetobranchcurrency.isnot(None),
                    ItemTransaction.rmah_id.is_(None),
                    ItemTransaction.it_isrmasuppliercreditnote.is_(False),
                )
            )
            .subquery()
        )

        stmt = select(ranked.c.item_id, ranked.c.it_priceofcostpp, ranked.c.it_cd).where(ranked.c.rn == 1)

        for item_id, it_priceofcostpp, it_cd in db.execute(stmt).all():
            if it_priceofcostpp is None or it_cd is None:
                continue
            fecha = it_cd.date() if isinstance(it_cd, datetime) else it_cd
            result[item_id] = PppSource(costo_ppp=float(it_priceofcostpp), costo_ppp_fecha=fecha)

    return result


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

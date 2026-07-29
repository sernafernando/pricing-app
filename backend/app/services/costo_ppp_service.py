"""
PPP (precio ponderado promedio / ERP weighted-average cost) resolver and
per-product markup accumulator for the Productos listing.

This module is display-only: it never touches selling prices, stored
`ProductoPricing` columns, SQL filters, or sort keys. It surfaces
`iclh_price_aw` as informational data, plus markups derived from it via the
existing `calcular_markup(limpio, costo)` formula.

=== Source correction (2026-07-29) ===

The original implementation of this feature read `ItemTransaction.it_priceofcostpp`.
That field is NOT the number the GBP ERP screen shows in its "Costo PPP"
column. Verified against production data and the ERP screen itself
(item 1169, ROUTER TP LINK OMADA ER605): GBP shows 38.00, `it_priceofcostpp`
yields 47.16 (a ~24% inflation), while `ItemCostListHistory.iclh_price_aw` —
whose own model comment already reads "Costo promedio ponderado" — yields
38.402760, matching the ERP screen. Across 2108 comparable products,
`iclh_price_aw` matched `it_priceofcostpp` in only 83 cases.

**What went wrong**: the original field was identified by NAME plausibility
plus internal consistency (order of magnitude, `pp > bpp` statistics across
the dataset) — never checked against a live ERP screen value, which is the
only check that would have caught the mismatch. See
`TestPinnedAgainstKnownErpValue` below for the regression test that would
have caught this had it existed from the start.

Row selection rule (see openspec/changes/productos-costo-ppp/specs.md):
    coslis_id = 1  (the main cost list — the one `productos_sync.py` reads
                    `producto_erp.costo`/`moneda_costo` from; see the
                    currency note below for why its CURRENCY can still
                    differ from `producto_erp.moneda_costo` at read time)
    AND iclh_price_aw IS NOT NULL AND iclh_price_aw > 0
    ORDER BY iclh_cd DESC, iclh_id DESC
    LIMIT 1 per item_id

Tiebreak note: `iclh_cd` (a `DateTime`) is not guaranteed unique per item_id —
two qualifying rows for the same item_id can share the exact same `iclh_cd`.
The tiebreak on `iclh_id DESC` (the highest surrogate PK — a real, always-
unique, monotonically-increasing column) makes the "latest qualifying row"
pick fully deterministic, reproducing the same real bug class the previous
implementation's `it_transaction DESC` tiebreak fixed for `tb_item_transactions`.

Currency (bugfix, 2026-07-29): `iclh_price_aw` is expressed in the cost
list's OWN currency (`curr_id`; ERP convention 1=ARS, 2=USD — same convention
used elsewhere in this codebase, e.g. `pedidos_service._curr_id_a_moneda`).

**This currency is INDEPENDENT of `producto_erp.moneda_costo` and CAN
differ from it** — a product costed in ARS can have a USD-denominated PPP
row in the ERP's main cost list, and vice versa; nothing in the ERP data
keeps the two in sync. This is not a hypothetical: an earlier revision of
this very fix wrote `PppMarkups(..., tipo_cambio=obtener_tipo_cambio_actual(db,
"USD") if producto_erp.moneda_costo == "USD" else None)` at the detail
endpoint call site — gating the exchange-rate lookup on the PRODUCT's
currency instead of the PPP SOURCE's — which left `tipo_cambio=None` (and
therefore the markup computed against an unconverted, ~1000x-too-small ARS
figure) for exactly the ARS-product/USD-PPP-row combination this paragraph
warns about. Every call site MUST resolve the USD rate unconditionally
(as the listing/tienda call sites already do) and let `PppMarkups` decide
whether to apply it, based on the SOURCE's `moneda`, never the product's.

There is NO currency conversion for DISPLAY: the previous implementation
converted an ARS value to USD using TODAY's exchange rate, which is not
just a wrong number but conceptually invalid — a historical weighted
average built from purchases at many different historical rates cannot be
reconstructed by dividing by today's rate. The resolved cost is shown in
its own currency (`payload().moneda`), which the frontend must label
correctly — it will not always match the list cost's currency.

Conversion IS needed for the MARKUP computation, though: `calcular_markup(limpio,
costo_ppp)` needs the cost in ARS, because `limpio` (from `calcular_limpio`) is
always in ARS. `PppMarkups` therefore converts the resolved cost to ARS via
`convertir_a_pesos`, using the SOURCE's own `costo_ppp_moneda` — exactly like
every other call site in `productos_listing.py` already converts the list
cost — purely as an internal input to `.record()`; the value returned in
`payload().costo` (and shown to the user) is NEVER this converted figure.

Coverage: ~77.5% of products (3215/4150) have a qualifying `coslis_id=1`
`iclh_price_aw` row, up from ~50% under the old `it_priceofcostpp`-based
selection.

Index/dialect note: `tb_item_transactions` needed a `LATERAL`-vs-`ROW_NUMBER()`
dialect branch (see git history) because a composite
`(item_id, it_cd DESC)` index (`ix_tit_item_cd_desc`) let PostgreSQL's
planner use an index scan with LATERAL instead of materialising and sorting
every row for every requested item_id — a real ~70x win on that much larger
table. `tb_item_cost_list_history` has no equivalent composite index (only
single-column indexes on `iclh_id` (PK), `coslis_id`, `item_id`, `iclh_cd`)
and is a much smaller table (historial de costos, not de transacciones), so
that optimisation does not carry over here as-is, and a LATERAL fast path
would need a new composite index to actually pay for itself. Given that,
this resolver uses the SIMPLEST portable formulation —
`ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY iclh_cd DESC, iclh_id DESC)`
filtered to `rn = 1` — on every dialect (including PostgreSQL), with no
dialect branching at all. If production EXPLAIN ANALYZE later shows this to
be a real bottleneck, the fix is a dedicated
`(item_id, coslis_id, iclh_cd DESC)` index plus a LATERAL fast path mirroring
the `tb_item_transactions` one — not carried here pre-emptively.

`ix_tit_item_cd_desc` on `tb_item_transactions` itself is UNCHANGED by this
fix and likely becomes unused by this specific feature (nothing here queries
`tb_item_transactions` anymore) — flagged, not dropped, since other code may
still rely on it (that index's removal is a separate decision).

PPP markup key vocabulary (contract consumed by PR2's frontend `markupKey`
props — see `openspec/changes/productos-costo-ppp/tasks.md` T3.11):

`PppMarkups.record(key, ...)` keys used to be free-form strings invented
independently at each of the 11 call sites across
`app/api/endpoints/productos_listing.py` (listing, listing's second/PVP-variant
pass, tienda, detail), which had already produced one confirmed bug
(`calculado_pvp_pvp_3_cuotas` — a doubled "pvp" segment) and three unrelated
names for the same conceptual classic-instalment markup (`calculado_{n}_cuotas`,
`cuota_ml_{n}`). The vocabulary below is now the single source of truth; call
sites build keys via the constants/helpers below instead of ad-hoc f-strings,
so a typo can no longer silently mint an orphan key:

  - `PPP_KEY_MEJOR_OFERTA` = `"mejor_oferta"` — best active ML offer markup.
  - `PPP_KEY_REBATE` = `"rebate"` — rebate-price markup.
  - `PPP_KEY_CLASICA` = `"clasica"` — clásica (list-cost) markup, the plain
    `markup`/`markup_calculado` field. Unlike every other key above, the
    DISPLAYED value (`ProductoPricing.markup_calculado`) is a stored column
    written by a separate batch (`recalcular_markups_service.py`), not
    computed in-request — there is no `limpio` naturally available for it at
    any existing call site. This key's `limpio` is instead RECOMPUTED
    in-request, reusing the exact same inputs the batch uses for the SAME
    product: pricelist 4 commission (`_lookup_comision(4, grupo_id)` /
    `obtener_comision_base(db, 4, grupo_id)`), the already-resolved shipping
    cost (`_resolve_envio`/`costo_envio_producto`), and the product's IVA —
    see `recalcular_markups_service.py:55-83`. This is a deliberate, narrow
    exception to "only reuse an existing `limpio`": every other key still
    reuses a `limpio` already computed at its shadowed markup site; this one
    reuses the batch's FORMULA and INPUTS instead, because the site itself
    does not compute one.
    CAVEAT: because the displayed `markup` comes from a stored column
    refreshed asynchronously while this PPP value is computed live, the two
    figures on the same row can be momentarily inconsistent if the batch has
    not run since the last price/commission/shipping change. This is a
    staleness window in the stored column, not a calculation error.
  - `ppp_key_cuota_clasica(n)` -> `"cuota_clasica_{n}"` (n in `"3"/"6"/"9"/"12"`)
    — classic-list instalment markup (pricelists 17/14/13/23). Same name in
    both the listing and tienda endpoints: it is the same conceptual markup
    in both places.
  - `PPP_KEY_PVP_CLASICA` = `"pvp_clasica"` — PVP list markup (pricelist 12,
    from `ProductoPricing.precio_pvp`). Same name in both the listing and
    detail endpoints.
  - `ppp_key_pvp_cuota(n)` -> `"pvp_cuota_{n}"` — PVP instalment markup
    (pricelists 18/19/20/21, from `ProductoPricing.precio_pvp_{n}_cuotas`).
    Same name in both the listing and detail endpoints. This is the fixed
    replacement for the doubled-segment bug above.

Two-source correspondence rule (bugfix, 2026-07-28): the listing endpoint's
PVP markups (`markup_pvp`/`markup_pvp_{n}_cuotas`) are computed TWICE — once
from `ProductoPricing.precio_pvp*` (first pass), then AGAIN from the
`PrecioML` table (second pass, a genuinely different source), and the second
pass's result is what the response actually returns (it overwrites the
first-pass value on the `producto` object). A `_variant`-suffixed key used
to exist so the second pass could record its own PPP companion without
"losing" the first-pass one — but that reasoning was backwards: the
first-pass VALUE is already discarded by the overwrite, so keeping its PPP
entry under the base key while a totally different (PrecioML-sourced) value
was displayed right next to it produced two real bugs: (1) a product with a
PrecioML price but no `ProductoPricing.precio_pvp` showed a real markup with
"sin PPP" below it — indistinguishable from genuine no-data; (2) a product
with both showed a markup from PrecioML with a PPP line derived from
`ProductoPricing.precio_pvp` — two different sources rendered adjacent with
no signal they didn't correspond. The fix: the second pass now records under
the SAME base key (`PPP_KEY_PVP_CLASICA` / `ppp_key_pvp_cuota(n)`) instead of
a `_variant` one. Since `PppMarkups.record()` overwrites on key collision,
the PPP entry follows the same source as the displayed value, by
construction — the PPP line must always describe the number it sits under.
The same principle applies to `PPP_KEY_MEJOR_OFERTA`: when a rebate override
replaces the displayed `mejor_oferta_markup` (out_of_cards + participa_rebate),
the PPP entry is re-recorded from the rebate's `limpio` too, instead of
keeping the pre-override value (or omitting it) for a value the response no
longer shows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.item_cost_list_history import ItemCostListHistory
from app.schemas.costo_ppp import PppPayload
from app.services.pricing_calculator import calcular_markup, convertir_a_pesos

# SQLite's default `SQLITE_MAX_VARIABLE_NUMBER` is 999; PostgreSQL's parameter
# limit is 65535. `batch_colores` (app/api/endpoints/productos_shared.py) chunks
# at the same size for the same reason — keep both in sync if this changes.
_IN_CHUNK_SIZE = 900

# Main cost list: the one whose `coslis_price` equals `productos_erp.costo`.
_COSLIS_ID_PRINCIPAL = 1


def _moneda_from_curr_id(curr_id: Optional[int]) -> str:
    """Maps the ERP's `curr_id` to the currency code used across this
    codebase. Convention: 1=ARS, 2=USD (same convention as
    `pedidos_service._curr_id_a_moneda`). Unmapped/unknown values default to
    "ARS" — the ERP's local currency — rather than raising or silently
    mislabelling a converted figure.
    """
    return "USD" if curr_id == 2 else "ARS"


@dataclass(frozen=True)
class PppSource:
    """One resolved PPP source row for a single item_id."""

    costo_ppp: float
    costo_ppp_fecha: date
    costo_ppp_moneda: str = "ARS"


def resolver_ppp_batch(db: Session, item_ids: list[int]) -> dict[int, PppSource]:
    """Resolve the latest qualifying PPP row per item_id, in ONE query.

    Args:
        db: Active SQLAlchemy session (main application DB).
        item_ids: item_ids to resolve for (typically the current page).

    Returns:
        {item_id: PppSource(costo_ppp, costo_ppp_fecha, costo_ppp_moneda)}.
        Items with no qualifying row are ABSENT from the dict — callers MUST
        treat a missing key as "no PPP data" and MUST NEVER fall back to the
        list cost. This function never raises for empty input; it returns {}.
    """
    if not item_ids:
        return {}

    result: dict[int, PppSource] = {}

    # Chunk item_ids to stay under SQLite's 999-variable limit / PostgreSQL's
    # 65535-param limit (same pattern as `batch_colores` in productos_shared.py).
    for start in range(0, len(item_ids), _IN_CHUNK_SIZE):
        chunk = item_ids[start : start + _IN_CHUNK_SIZE]

        stmt = _build_ranked_stmt(chunk)

        for item_id, iclh_price_aw, curr_id, iclh_cd in db.execute(stmt).all():
            if iclh_price_aw is None or iclh_cd is None:
                continue
            fecha = iclh_cd.date() if isinstance(iclh_cd, datetime) else iclh_cd
            result[item_id] = PppSource(
                costo_ppp=float(iclh_price_aw),
                costo_ppp_fecha=fecha,
                costo_ppp_moneda=_moneda_from_curr_id(curr_id),
            )

    return result


def _qualifying_predicate(item_id_col):
    """Shared row-selection predicate, parameterised over the item_id column."""
    return and_(
        item_id_col,
        ItemCostListHistory.coslis_id == _COSLIS_ID_PRINCIPAL,
        ItemCostListHistory.iclh_price_aw.isnot(None),
        ItemCostListHistory.iclh_price_aw > 0,
    )


def _build_ranked_stmt(chunk: list[int]):
    """Portable "latest qualifying row per item_id" query (see module
    docstring's index/dialect note for why no LATERAL fast path is used here).

    Uses `ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY iclh_cd DESC,
    iclh_id DESC)`, filtered to `rn = 1` in the outer query. The `iclh_id
    DESC` tiebreak makes the pick deterministic even when two qualifying rows
    share the exact same `iclh_cd`.
    """
    row_number_col = (
        func.row_number()
        .over(
            partition_by=ItemCostListHistory.item_id,
            order_by=[ItemCostListHistory.iclh_cd.desc(), ItemCostListHistory.iclh_id.desc()],
        )
        .label("rn")
    )

    ranked = (
        select(
            ItemCostListHistory.item_id.label("item_id"),
            ItemCostListHistory.iclh_price_aw.label("iclh_price_aw"),
            ItemCostListHistory.curr_id.label("curr_id"),
            ItemCostListHistory.iclh_cd.label("iclh_cd"),
            row_number_col,
        )
        .where(_qualifying_predicate(ItemCostListHistory.item_id.in_(chunk)))
        .subquery()
    )

    return select(ranked.c.item_id, ranked.c.iclh_price_aw, ranked.c.curr_id, ranked.c.iclh_cd).where(ranked.c.rn == 1)


# --- Canonical PPP markup key vocabulary (see module docstring) -------------

PPP_KEY_MEJOR_OFERTA = "mejor_oferta"
PPP_KEY_REBATE = "rebate"
PPP_KEY_CLASICA = "clasica"
PPP_KEY_PVP_CLASICA = "pvp_clasica"


def ppp_key_cuota_clasica(n: str) -> str:
    """Classic-list instalment markup key, e.g. `ppp_key_cuota_clasica("3")` -> `"cuota_clasica_3"`."""
    return f"cuota_clasica_{n}"


def ppp_key_pvp_cuota(n: str) -> str:
    """PVP instalment markup key, e.g. `ppp_key_pvp_cuota("3")` -> `"pvp_cuota_3"`."""
    return f"pvp_cuota_{n}"


class PppMarkups:
    """Per-product accumulator turning `limpio` values into PPP markups.

    One instance per product. The PPP source (and its date/currency) are
    fixed at construction from a single `Optional[PppSource]` — this makes
    "no qualifying PPP row" and "a qualifying row with a fecha" the only two
    reachable states; `costo_ppp` set with `costo_ppp_fecha=None` is not
    representable, so `payload()` can never attempt to build a `PppPayload`
    with a `None` `fecha` (which is non-optional and would raise a
    `ValidationError`/500). `.record(...)` is called once per existing markup
    site with that site's already-computed `limpio`. `.payload()` returns
    `None` for the WHOLE object when there is no source, so no call site can
    ever construct a partial payload for a product with no qualifying PPP row.

    Currency handling (see module docstring): the DISPLAYED cost
    (`payload().costo`) is NEVER converted — it stays in the aw's own
    currency (`payload().moneda`), because a historical weighted-average
    cost cannot be meaningfully reconstructed by dividing by today's
    exchange rate. Markup computation, however, needs the cost in ARS
    (`limpio` is always ARS), so `.record()` uses an ARS-converted mirror
    (`_costo_ppp_ars`, via `convertir_a_pesos`) purely as `calcular_markup`'s
    second argument — this conversion never leaks into `payload().costo`.
    """

    def __init__(
        self,
        source: Optional["PppSource"],
        *,
        tipo_cambio: Optional[float] = None,
    ) -> None:
        self._costo_ppp = source.costo_ppp if source else None
        self._costo_ppp_fecha = source.costo_ppp_fecha if source else None
        self._costo_ppp_moneda = source.costo_ppp_moneda if source else None
        self._markups: dict[str, float] = {}

        # ARS mirror used ONLY as calcular_markup's cost input — never
        # exposed via payload().costo (see class docstring).
        self._costo_ppp_ars = (
            convertir_a_pesos(self._costo_ppp, self._costo_ppp_moneda, tipo_cambio)
            if self._costo_ppp is not None
            else None
        )

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
        if self._costo_ppp_ars is None:
            return
        raw = calcular_markup(limpio, self._costo_ppp_ars)
        self._markups[key] = round(raw * 100, 2) if percent else raw

    def payload(self) -> Optional[PppPayload]:
        if self._costo_ppp is None:
            return None
        return PppPayload(
            costo=self._costo_ppp,
            moneda=self._costo_ppp_moneda,
            fecha=self._costo_ppp_fecha,
            markups=dict(self._markups),
        )

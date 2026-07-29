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
                    currency note below)
    AND iclh_price_aw IS NOT NULL AND iclh_price_aw > 0
    ORDER BY iclh_cd DESC, iclh_id DESC
    LIMIT 1 per item_id

Tiebreak note: `iclh_cd` (a `DateTime`) is not guaranteed unique per item_id —
two qualifying rows for the same item_id can share the exact same `iclh_cd`.
The tiebreak on `iclh_id DESC` (the highest surrogate PK — a real, always-
unique, monotonically-increasing column) makes the "latest qualifying row"
pick fully deterministic, reproducing the same real bug class the previous
implementation's `it_transaction DESC` tiebreak fixed for `tb_item_transactions`.

Currency (verified against production data, 2026-07-29): `iclh_price_aw`'s
currency matches `producto_erp.moneda_costo` BY CONSTRUCTION, not by
coincidence — both are read from the SAME row of the SAME cost list
(`coslis_id = 1`; `productos_sync.py` populates `producto_erp.costo`/
`moneda_costo` from that exact list's `coslis_price`/`curr_id`). This was
checked directly, not assumed: across all 3215 products with a qualifying
PPP row, ZERO have a currency mismatch between the resolved `iclh_price_aw`
and `producto_erp.moneda_costo` (3150 USD, 65 ARS). A separate cross-check
on the full `coslis_id = 1` table (not just the ones with a PPP row) found
`coslis_price` matches `producto_erp.costo` in 4149/4150 rows and the
CURRENCY matches in 4150/4150 — reinforcing that this is the same
underlying data, not two independently-sourced figures that merely tend to
agree.

**Do not reintroduce a currency derived independently from the PPP source
row** (e.g. from `curr_id` on `tb_item_cost_list_history`) "just in case" —
an earlier revision of this fix did exactly that (treating the two
currencies as independent, `PppSource.costo_ppp_moneda` derived from
`curr_id`) after a real bug in a THIRD, DIFFERENT feature round (a call site
that gated its exchange-rate lookup incorrectly) was mistaken for evidence
of a currency mismatch that does not exist in the data. `payload().moneda`
is `producto_erp.moneda_costo`, passed in by the caller — the same value
every other call site already uses to convert the list cost — not a second,
independently-derived currency.

There is NO currency conversion for DISPLAY: the previous implementation
converted an ARS value to USD using TODAY's exchange rate, which is not
just a wrong number but conceptually invalid — a historical weighted
average built from purchases at many different historical rates cannot be
reconstructed by dividing by today's rate. The resolved cost is shown in
`producto_erp.moneda_costo` (the SAME currency as the list cost, by
construction — see above), which is already correct without any
conversion.

Conversion IS needed for the MARKUP computation, though: `calcular_markup(limpio,
costo_ppp)` needs the cost in ARS, because `limpio` (from `calcular_limpio`) is
always in ARS. `PppMarkups` therefore converts the resolved cost to ARS via
`convertir_a_pesos(costo_ppp, moneda_costo, tipo_cambio)` — the exact same
`moneda_costo`/`tipo_cambio` every other call site in `productos_listing.py`
already uses to convert the list cost, no separate lookup — purely as an
internal input to `.record()`; the value returned in `payload().costo` (and
shown to the user) is NEVER this converted figure.

Fail-closed on a missing exchange rate: even though the two currencies match
by construction, `moneda_costo` can still be USD with no `TipoCambio` row
resolved for today — `convertir_a_pesos(x, "USD", None)` (see
`pricing_calculator.py`) silently returns `x` UNCONVERTED in that case, and a
markup computed against that raw figure as if it were ARS is off by roughly
the exchange rate itself (a ~38 cost read as ~38 ARS instead of ~38,000 ARS
produces a ~149,900% markup — silently, no exception, no log, no flag on the
payload). `PppMarkups` guards against this: whenever a real conversion is
needed but no rate is resolvable, NO markup is emitted at all (`.record()`
becomes a no-op) — `payload().costo`/`.moneda` stay unaffected, since the PPP
cost itself does not depend on today's rate. This failure mode is
independent of the currency-matching fact above (it only needs "non-ARS
`moneda_costo`, no rate today") and is guarded regardless of it.

Null-safety: `ProductoERP.moneda_costo` (`app/models/producto.py`) has a
Python-side default but no `nullable=False`, so a raw upsert/sync can leave
it `NULL`. `PppMarkups` normalizes a falsy `moneda_costo` to `"ARS"` at
construction — this must happen before it reaches `PppPayload.moneda`
(non-optional `str`) or `convertir_a_pesos`.

=== Scale sanity guard (2026-07-29) ===

THIRD data-trust failure in this feature (after the wrong-field bug above
and the fictitious-currency-layer revert): for a minority of products the
ERP left `iclh_price_aw` STALE at a different currency scale than
`iclh_price` in its OWN row. Witness — item 2780 (RESMA AUTOR CARTA), reported
by a user who saw "2.91" next to a cost of 3178.25:

    2025-03-26 | coslis_id 1 | iclh_price 2.911820    | iclh_price_aw 2.911820 | curr_id 2 (USD)
    2025-07-28 | coslis_id 1 | iclh_price 3178.250000 | iclh_price_aw 2.911820 | curr_id 1 (ARS)

The product moved from USD to ARS: `iclh_price`/`curr_id` were updated,
`iclh_price_aw` was NOT recalculated. Ratio price/aw = 1091 — an exchange
rate of that period, not a costing difference. This is NOT a
currency-label divergence: `curr_id` (1 = ARS) matches
`producto_erp.moneda_costo` (ARS) — no currency-matching logic (see above)
could ever catch this, because the broken value is the NUMBER itself, not
its label.

Measured on production (2026-07-29), on the row the resolver picks for each
of the 3215 products with a PPP: ratio `iclh_price / iclh_price_aw` is
"normal" (0.5-2.0) for 3137, "suspicious" (2x-20x, plausibly a real cost
swing — KEPT) for 50, and unambiguously BROKEN for 42 (23 with aw ~1000x too
small, ratio 27.5 up to 53,249,815; 20 with aw ~1000x too large, ratio
0.001-0.040). Cross-checked against `producto_erp.costo` instead of
`iclh_price`: same 42 broken, 3172 coherent — confirming the guard does not
need to join out to `producto_erp` (see `_is_scale_sane`'s docstring for why
it validates against the SAME row's `iclh_price` instead).

`resolver_ppp_batch` rejects a row whenever `iclh_price` is missing/`<= 0`,
or `iclh_price / iclh_price_aw` falls outside `[_PPP_RATIO_MIN,
_PPP_RATIO_MAX]` = `[0.05, 20]` (bounds INCLUSIVE — see the constants'
comment for why 20 and not something tighter). A rejected row means the item
gets NO PPP — the resolver does NOT fall back to an older row: if the
current (latest) row's `aw` is broken, an older row is even less
trustworthy, and by construction there IS no older candidate available at
the rejection site anyway (the ranking already picked the single rn=1 row
per item_id before this guard runs).

**Pattern across all three failures in this feature**: an ERP value can
never be trusted on its own — it must be validated against a reference IN
THE SAME ROW (first the field itself against a live ERP screen value, now
`iclh_price_aw` against `iclh_price`). "Looks like a plausible number" is
not evidence of correctness.

Coverage: ~76.5% of products (3173/4150) have a qualifying `coslis_id=1`
`iclh_price_aw` row that ALSO passes the scale sanity guard (measured
2026-07-29) — down from ~77.5% (3215/4150) before the guard rejected the 42
broken rows above; up from ~50% under the old `it_priceofcostpp`-based
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

# Main cost list: the one whose `coslis_price`/`curr_id` populate
# `producto_erp.costo`/`moneda_costo` (see module docstring's currency note).
_COSLIS_ID_PRINCIPAL = 1

# Sanity-guard bounds for `iclh_price / iclh_price_aw` on the SAME row
# (2026-07-29 — see module docstring's "Scale sanity guard" section).
# Measured on the 3215 products with a qualifying PPP row: 3137 are "normal"
# (0.5-2.0), 50 are "suspicious" (2x-20x, plausibly a real cost swing — a
# product's cost CAN legitimately move that much), and 42 are unambiguously
# BROKEN (23 with a ratio of ~1000x-and-up, 20 with a ratio of ~0.001-0.040 —
# an order-of-magnitude-1000 currency-scale mismatch, not a costing
# difference). 20/0.05 is deliberately loose: it is chosen to sit just above
# the legitimate 2x-20x band so it never rejects a real cost movement, while
# still catching every observed scale error (the closest broken ratio, 27.5,
# is already >1000x further out than this bound). A tighter bound would risk
# false positives on the 50 legitimate outliers; a looser one would let a
# broken row through.
_PPP_RATIO_MIN = 0.05
_PPP_RATIO_MAX = 20.0


@dataclass(frozen=True)
class PppSource:
    """One resolved PPP source row for a single item_id.

    Deliberately carries NO currency of its own — see module docstring's
    "Currency" section for why.
    """

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

    # Chunk item_ids to stay under SQLite's 999-variable limit / PostgreSQL's
    # 65535-param limit (same pattern as `batch_colores` in productos_shared.py).
    for start in range(0, len(item_ids), _IN_CHUNK_SIZE):
        chunk = item_ids[start : start + _IN_CHUNK_SIZE]

        stmt = _build_ranked_stmt(chunk)

        for item_id, iclh_price, iclh_price_aw, iclh_cd in db.execute(stmt).all():
            if iclh_price_aw is None or iclh_cd is None:
                continue
            if not _is_scale_sane(iclh_price, iclh_price_aw):
                # The row FAILED the sanity guard: iclh_price_aw is stale at a
                # different currency scale than iclh_price in its OWN row (see
                # module docstring's "Scale sanity guard" section). Do NOT
                # fall back to an older row for this item_id — an older row
                # is even less trustworthy than the current (latest) one, and
                # this loop only ever sees the single already-ranked (rn=1)
                # row per item_id, so there is no older candidate to try
                # anyway. The item simply gets no PPP (absent from `result`).
                continue
            fecha = iclh_cd.date() if isinstance(iclh_cd, datetime) else iclh_cd
            result[item_id] = PppSource(costo_ppp=float(iclh_price_aw), costo_ppp_fecha=fecha)

    return result


def _is_scale_sane(iclh_price: Optional[float], iclh_price_aw: float) -> bool:
    """Reject a row whose `iclh_price_aw` is stale at a different currency
    scale than `iclh_price` IN THE SAME ROW (2026-07-29 — see module
    docstring's "Scale sanity guard" section for the witness item and
    measured counts).

    Self-contained by design: validated against `iclh_price` from the SAME
    row, never against `producto_erp.costo` — measurement showed both give
    the same 42 broken rows, so joining out would add a dependency for no
    gain.
    """
    if iclh_price is None or iclh_price <= 0:
        return False  # no reference in this row to validate iclh_price_aw against
    # Cast explicitly: both columns are `Numeric(18, 6)` (see
    # ItemCostListHistory), so the DB driver can return `Decimal`. Comparing a
    # `Decimal` ratio against the float bounds below can misfire at the exact
    # boundary (`Decimal("0.05") >= 0.05` is `False` — 0.05 has no exact
    # binary float representation) — force both operands to `float` first so
    # the boundary tests (ratio exactly 20 / exactly 0.05) are inclusive as
    # documented.
    ratio = float(iclh_price) / float(iclh_price_aw)
    return _PPP_RATIO_MIN <= ratio <= _PPP_RATIO_MAX


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
            ItemCostListHistory.iclh_price.label("iclh_price"),
            ItemCostListHistory.iclh_price_aw.label("iclh_price_aw"),
            ItemCostListHistory.iclh_cd.label("iclh_cd"),
            row_number_col,
        )
        .where(_qualifying_predicate(ItemCostListHistory.item_id.in_(chunk)))
        .subquery()
    )

    return select(ranked.c.item_id, ranked.c.iclh_price, ranked.c.iclh_price_aw, ranked.c.iclh_cd).where(
        ranked.c.rn == 1
    )


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

    Currency handling and the fail-closed guard on a missing exchange rate
    are both documented in full in the module docstring's "Currency" section
    — read that before changing `moneda_costo`/`tipo_cambio` handling here.
    Short version: `payload().costo` is never converted (shown as-is in
    `moneda_costo`); `_costo_ppp_ars` (an internal ARS mirror, via
    `convertir_a_pesos`) is the ONLY input `calcular_markup` sees, and it is
    `None` — making `.record()` a no-op — whenever a real conversion was
    needed but no rate could be resolved, or `moneda_costo` was falsy
    (`None`/empty), normalized to `"ARS"` at construction.
    """

    def __init__(
        self,
        source: Optional["PppSource"],
        *,
        moneda_costo: Optional[str] = "ARS",
        tipo_cambio: Optional[float] = None,
    ) -> None:
        self._costo_ppp = source.costo_ppp if source else None
        self._costo_ppp_fecha = source.costo_ppp_fecha if source else None
        # Null-safety (2026-07-29): `ProductoERP.moneda_costo` has a
        # Python-side default (`TipoMoneda.ARS`) but no `nullable=False` —
        # a raw upsert/sync can insert `moneda_costo IS NULL`. Normalize here
        # (once, at the boundary) instead of assuming callers already did,
        # so a NULL never reaches `PppPayload.moneda` (non-optional `str` —
        # would raise `ValidationError`/500) nor `convertir_a_pesos`.
        self._moneda_costo = moneda_costo or "ARS"
        self._markups: dict[str, float] = {}

        # ARS mirror used ONLY as calcular_markup's cost input — never
        # exposed via payload().costo (see class docstring). Fail-closed:
        # a non-ARS `moneda_costo` with no resolvable `tipo_cambio` must NOT
        # fall through to convertir_a_pesos's silent "return unconverted"
        # behaviour here — that would compute every markup against a figure
        # off by roughly the exchange rate, with no error. None here makes
        # .record() a no-op instead (see class docstring).
        self._costo_ppp_ars = (
            convertir_a_pesos(self._costo_ppp, self._moneda_costo, tipo_cambio)
            if self._costo_ppp is not None and (self._moneda_costo == "ARS" or tipo_cambio)
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
            moneda=self._moneda_costo,
            fecha=self._costo_ppp_fecha,
            markups=dict(self._markups),
        )

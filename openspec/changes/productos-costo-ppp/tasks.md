# Tasks: productos-costo-ppp

Ordered, PR-sliced checklist. Each item traces to a spec requirement or design decision.
Anchors verified against current `feat/productos-ajustes` branch on 2026-07-27; line numbers
in the proposal/design were off by several lines (branch drift) — the numbers below are current
and each carries a variable-name anchor as a stable secondary reference.

## PR0 — Anchor verification (prerequisite, no code change)

- [x] T0.1 Re-run this verification immediately before starting PR1 if any commit touched
      `productos_listing.py` or `Productos.jsx` since 2026-07-27, and correct the checklists below
      if line numbers drifted again.

## PR1 — Backend: costo_ppp resolver, PPP markups, tests, conditional index

Traces to: Requirement "PPP row selection per item", "PPP is already in ARS", "PPP source date
always displayed", "Explicit no-data state", "No change to selling prices, stored markups, or
filters". Design: `costo_ppp_service.py`, `PppPayload`, conditional index.

### Service layer

- [x] T1.1 Create `backend/app/services/costo_ppp_service.py`:
  - `PppSource` dataclass (`costo_ppp: float`, `costo_ppp_fecha: date`)
  - `resolver_ppp_batch(db, item_ids: list[int]) -> dict[int, PppSource]` — ONE `DISTINCT ON
    (item_id)` query over `tb_item_transactions` filtered by `it_priceofcostpp > 0 AND
    it_cancelled = false AND it_exchangetobranchcurrency IS NOT NULL AND rmah_id IS NULL AND
    it_isrmasuppliercreditnote = false`, ordered by `item_id, it_cd DESC`
  - `PppMarkups` accumulator: `__init__(self, costo_ppp: Optional[float])`, `.record(key: str,
    limpio: float) -> None`, `.payload() -> Optional[PppPayload]` returning `None` whole-object
    when `costo_ppp` is `None` (never a partial payload)
- [x] T1.2 Add `PppPayload` model to `backend/app/api/endpoints/productos_shared.py`:
  `costo: float`, `fecha: date`, `markups: dict[str, float]`; add `ppp: Optional[PppPayload] =
  None` to `ProductoResponse` and `ProductoTiendaResponse`.

### Prefetch + per-block wiring in productos_listing.py

- [x] T1.3 Add one `resolver_ppp_batch(db, item_ids)` prefetch call per response-building block
  (mirrors the existing `pubs_by_item`/`resolver_costos_envio_batch` prefetch pattern), and
  instantiate `PppMarkups(ppp_source.costo_ppp if ppp_source else None)` per product before its
  markup sites run.
- [x] T1.4 Attach `ppp=ppp.payload()` in each of the three response builders (verify exact
  assignment points during implementation — the three blocks around lines ~900-1210,
  ~2098-2280, ~2442-2560 per design.md).

### Backend markup call sites — one checkbox per site (11 total)

Each item: add exactly ONE line `ppp.record("<key>", <limpio var>)` immediately after the
existing `calcular_markup(<limpio var>, <costo var>)` call at that line. Do NOT touch the
existing list-cost line.

- [x] T1.5 Line 972 — `mejor_oferta_markup = calcular_markup(limpio, costo_calc)` → `ppp.record("mejor_oferta", limpio)`
- [x] T1.6 Line 1003 — `markup_rebate = calcular_markup(limpio_rebate, costo_rebate) * 100` → `ppp.record("rebate", limpio_rebate)`
- [x] T1.7 Line 1056 — `markup_calculado = calcular_markup(limpio_cuota, costo_cuota) * 100` → `ppp.record("calculado", limpio_cuota)`
- [x] T1.8 Line 1099 — `markup_pvp = round(calcular_markup(limpio_pvp, costo_pvp) * 100, 2)` → `ppp.record("pvp", limpio_pvp)`
- [x] T1.9 Line 1134 — `markup_calculado_pvp = round(calcular_markup(limpio_cuota_pvp, costo_cuota_pvp) * 100, 2)` → `ppp.record("calculado_pvp", limpio_cuota_pvp)`
- [x] T1.10 Line 1397 — `markup_calculado = calcular_markup(limpio_pvp, costo_pvp) * 100` (second block variant) → `ppp.record("calculado_variant", limpio_pvp)`
- [x] T1.11 Line 2145 — `mejor_oferta_markup = calcular_markup(limpio, costo_calc)` (third block) → `ppp.record("mejor_oferta", limpio)`
- [x] T1.12 Line 2171 — `markup_rebate = calcular_markup(limpio_rebate, costo_rebate) * 100` (third block) → `ppp.record("rebate", limpio_rebate)`
- [x] T1.13 Line 2259 — `mc = calcular_markup(lim, cc) * 100` (cuotas ML loop, anchor vars `lim`/`cc` inside the `precio_cuota` loop) → `ppp.record("cuota_ml", lim)`
- [x] T1.14 Line 2501 — `markup_pvp = round(calcular_markup(limpio_pvp, costo_pvp) * 100, 2)` (third block) → `ppp.record("pvp", limpio_pvp)`
- [x] T1.15 Line 2538 — `markup_calculado_pvp = round(calcular_markup(limpio_cuota_pvp, costo_cuota_pvp) * 100, 2)` (third block) → `ppp.record("calculado_pvp", limpio_cuota_pvp)`

### Index gate (evidence-conditional, NOT assumed)

- [x] T1.16 Run `EXPLAIN (ANALYZE, BUFFERS)` on the resolver query against production, with the
      composite index manually created via `CREATE INDEX CONCURRENTLY` ahead of the decision.
      Result: ROW_NUMBER() forces `Sort Method: external merge Disk: 3832kB` and reads 112,809
      rows to return 316 (900 item_ids -> 158ms; 50 item_ids -> 47ms).
- [x] T1.17 Decision gate: index IS needed AND the query shape itself must change — a LATERAL
      join (900 item_ids -> 2.2ms, Nested Loop + Index Scan, no sort; ~70x faster) replaces
      ROW_NUMBER on PostgreSQL. See PR1b below.
- [x] T1.18 `alembic heads` re-checked at PR1b time and returns exactly ONE head
      (`20260727_fix_llm_ids`) — migration chained from it.
- [x] T1.19 Migration generated in PR1b (`20260727_ppp_lateral_index.py`), idempotent
      (`IF NOT EXISTS`/`DROP ... IF EXISTS`, both in `autocommit_block()`), since production
      already has the index live from the manual `CREATE INDEX CONCURRENTLY`.

**Deviation note (environment constraint, not in the original design)**: the design's
`resolver_ppp_batch` was specified around PostgreSQL's `DISTINCT ON (item_id)`. Backend CI runs
against SQLite (`DATABASE_URL=sqlite:///./test.db`), and `DISTINCT ON` is PostgreSQL-only — it
would fail every CI run. `costo_ppp_service.py` implements the identical "one row per item_id,
latest `it_cd` wins" semantics using a portable `ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY
it_cd DESC)` window function filtered to `rn = 1`, which both PostgreSQL and SQLite (>= 3.25)
support. This does not change the row-selection contract (still the same 5-predicate filter, same
tiebreak) and produces the same plan shape as `DISTINCT ON` on PostgreSQL (both need an index on
`(item_id, it_cd)` to avoid a sort — the T1.16 EXPLAIN gate above is still the right way to decide
on the composite index). Verified via 8 real-SQLite unit tests exercising the actual
`ItemTransaction` ORM model (`tests/unit/test_costo_ppp_service.py`).

### Backend tests

- [x] T1.20 Unit: row-selection exclusion tests — cancelled row, `it_exchangetobranchcurrency
      IS NULL` row, `rmah_id` not null row, `it_isrmasuppliercreditnote = true` row,
      `it_priceofcostpp <= 0` row — each individually excluded; latest `it_cd` wins among
      multiple qualifying rows.
- [x] T1.21 Unit: no-data contract — item with zero qualifying rows ⇒ `resolver_ppp_batch`
      omits it / `PppMarkups(None).payload() is None`, AND assert no key in any response equals
      `costo` (assert identity/value inequality, not just nullness, per design.md testing
      strategy).
- [x] T1.22 Unit: `PppMarkups.record` scaling/rounding parity test against each existing
      markup site's own scaling (some sites use `* 100` raw, others `round(..., 2)` — the
      accumulator must match the site it shadows).
- [x] T1.23 Integration: golden no-regression — snapshot `/productos` response for a fixed
      fixture page before this change; diff after change must be empty except for the new `ppp`
      key(s). Wire into existing golden-snapshot test infra if present, else create one.
- [x] T1.24 Integration: query-count assertion — SQLAlchemy event-counter test asserting exactly
      1 PPP-resolver query fires for `page_size=1` and exactly 1 for `page_size=100` (structurally
      proves no N+1).
- [x] T1.25 Run `ruff format app/` in the venv before pushing (CI "Backend Lint" enforces this;
      local pre-commit hook additionally covers `tests/` and `alembic/` — run it too).

### Fix round — Guardian Angel pre-push review (commit 3a1336e7)

- [x] T1.26 Fix CRITICAL silent-data-loss bug: `ppp.record()` used a fixed key inside every
      3/6/9/12-cuotas loop, so 3 of every 4 instalment markups silently overwrote each other.
      Fixed at all 5 physical sites (classic cuotas, PVP cuotas x2 — `listar_productos` and
      `obtener_producto` — tienda cuotas, and the listing's second-pass PVP-variant loop) with
      per-instalment keys. Final key vocabulary documented in `app/schemas/costo_ppp.py`.
- [x] T1.27 `PppMarkups.__init__` now takes a single `Optional[PppSource]` instead of two
      independent optional params, making "costo_ppp set, fecha=None" (which 500ed via a
      Pydantic `ValidationError`) unrepresentable at the type level.
- [x] T1.28 `resolver_ppp_batch`'s `item_id.in_(item_ids)` now chunks at 900, matching
      `batch_colores`' existing SQLite/PostgreSQL param-limit pattern.
- [x] T1.29 Moved `PppPayload` to `app/schemas/costo_ppp.py`; `costo_ppp_service.py` no longer
      imports from an endpoints module (layering fix). `productos_shared.py` re-exports it.
- [x] T1.30 Replaced the Python-call-counting query-count test with a real SQL-statement
      counter (`query_counter` fixture, `before_cursor_execute`) exercised against the paginated
      `/api/productos` list endpoint at page_size=1 and page_size=100 — this is the test T1.24
      always intended; the original version only proved it against the single-item detail
      endpoint, which cannot reveal an N+1 by construction.
- [x] T1.31 Hoisted `producto.ppp = _ppp_acc.payload()` out of the 5-iteration `pvp_configs`
      loop in `listar_productos` (was rebuilt up to 5x per product).

## PR1b — Perf round: LATERAL resolver, Postgres CI, index migration (commit 7bf0c4ff)

Triggered by production EXPLAIN ANALYZE evidence (see T1.16/T1.17 above) gathered after PR1
merged with the manually-created `ix_tit_item_cd_desc` index in place.

- [x] TP.1 `resolver_ppp_batch` now branches on `db.bind.dialect.name`: PostgreSQL uses a new
      LATERAL join (`_build_lateral_stmt`, `func.unnest(...).table_valued(...).lateral()`) with
      `ORDER BY it_cd DESC LIMIT 1` per item_id; every other dialect (SQLite, used by ~3700 of
      the suite's tests) keeps the previous `ROW_NUMBER()` fallback (`_build_row_number_stmt`),
      unchanged in semantics. Both share one `_qualifying_predicate` helper — the 5-predicate
      filter is defined once, not duplicated across the two query shapes. 900-item chunking
      preserved unchanged.
- [x] TP.2 Rewrote the module docstring: replaced the obsolete "portability" framing (which
      justified ROW_NUMBER as the ONLY implementation) with the measured LATERAL vs. ROW_NUMBER
      numbers and an explicit note on why the SQLite fallback still exists (avoid moving ~3700
      tests onto PostgreSQL for this round).
- [x] TP.3 Added `postgres` service (`postgres:16`) to the `backend-smoke` CI job
      (`.github/workflows/ci.yml`), wired via `POSTGRES_TEST_URL` env var. Chose option (b) —
      only `@pytest.mark.postgres`-marked tests run against it; the rest of the suite (~3700
      tests) stays on SQLite, avoiding disruption while still guaranteeing the LATERAL path runs
      in CI, not just the fallback.
- [x] TP.4 `tests/conftest.py`: added `pg_engine` (session-scoped, creates only
      `tb_item_transactions`, not the full `Base.metadata`) and `pg_db` (function-scoped,
      transactional rollback) fixtures. `pg_engine` calls `pytest.skip(...)` with a clear message
      when PostgreSQL is unreachable, so a developer without local PostgreSQL still runs the rest
      of the suite cleanly. Registered the `postgres` marker in new `backend/pytest.ini`.
- [x] TP.5 Added `TestResolverAgainstRealPostgres` (5 tests, `@pytest.mark.postgres`) to
      `tests/unit/test_costo_ppp_service.py`: latest-row-wins under LATERAL, full row-selection
      predicate under LATERAL, exactly-one-query at page_size 1 and 100 (SQL-statement counter),
      and >900-item chunking under PostgreSQL. Verified locally against a real PostgreSQL 16
      instance (all 5 pass) and verified the skip path (bad `POSTGRES_TEST_URL` -> 5 skipped,
      clear message, rest of suite unaffected).
- [x] TP.6 Added migration `20260727_ppp_lateral_index.py` (revises `20260727_fix_llm_ids`,
      single head confirmed) versioning `ix_tit_item_cd_desc ON tb_item_transactions (item_id,
      it_cd DESC)`: `CREATE INDEX CONCURRENTLY IF NOT EXISTS` / `DROP INDEX CONCURRENTLY IF
      EXISTS`, both inside `op.get_context().autocommit_block()`, both dialect-guarded to
      PostgreSQL only. Verified idempotent (`CREATE ... IF NOT EXISTS` run twice locally, second
      run is a no-op notice) and reversible against a real PostgreSQL instance.
- [x] TP.7 Full backend suite: 3711 passed, 16 skipped, 0 failed (3706 baseline + 5 new
      `@pytest.mark.postgres` tests). `ruff format`/`ruff check app/` clean; pre-existing
      unrelated `app/tickets/SISTEMA_TICKETS_README.md` reformat reverted per instructions.
      Committed as `7bf0c4ff` on `feat/productos-costo-ppp-backend`, on top of `37912dc8`. NOT
      pushed, PR NOT marked ready, per explicit instruction.
- [x] TP.8 **Coordinator-mandated risk closure**: added `TestResolverDialectEquivalence`
      (`tests/unit/test_costo_ppp_service.py`) — a single shared dataset (every exclusion
      predicate, multi-row-per-item, an absent item, and an EXACT `it_cd` tie) seeded into both
      SQLite and a real PostgreSQL instance, asserting `_build_lateral_stmt` and
      `_build_row_number_stmt` return byte-identical `{item_id: PppSource}` dicts.
      **Real divergence found and fixed, not silenced**: on an exact `it_cd` tie, neither
      LATERAL's `LIMIT 1` nor `ROW_NUMBER()` had a deterministic winner — verified empirically by
      temporarily removing the secondary sort and re-running (failed 3/3 times). Fixed by adding
      a stable tiebreak, `ORDER BY it_cd DESC, it_transaction DESC`, to BOTH branches (a real,
      always-unique, indexed column). Row-selection rule and module docstring updated. Committed
      as `4cc393a4`. Full suite re-verified: 3712 passed, 16 skipped, 0 failed.

## PR2 — Frontend base: cost line + first markup group + shared formatter

Traces to: Requirement "PPP markups render at all display sites" (cost cell + first group),
"Explicit no-data state, never a cost fallback", "PPP source date always displayed".

- [x] T2.1 Add `formatPppMonto` / `formatPppFecha` (dd/mm/aa, no relative wording, no staleness
      styling) to `frontend/src/hooks/useProductosOffsets.js`, alongside
      `calcularMarkupConOffset`/`getMarkupColor`. `formatPppMonto(value, markupKey)` centralises
      the raw-ratio-vs-percent distinction via a `PPP_RATIO_KEYS` set (`mejor_oferta` only, per
      `ppp.record(PPP_KEY_MEJOR_OFERTA, limpio, percent=False)` in the backend).
- [x] T2.2 Create `frontend/src/components/PppLine.jsx` — `<PppLine ppp={p.ppp} markupKey="..."
      />`; renders "sin PPP" marker when `ppp` is `null`/`undefined` OR when `markupKey` is not
      found in `ppp.markups`; never reads `p.costo` or any list-cost markup as a substitute.
- [x] T2.3 No CRLF/whitespace renormalization was needed — `git diff --stat` confirmed the diff
      matches exactly the lines touched (50 insertions / 1 deletion across 3 files).
- [x] T2.4 Cost cell — line 1715 `<td>{p.moneda_costo} ${p.costo?.toFixed(2)}</td>` → added
      `<PppLine ppp={p.ppp} />` companion line below it (no `markupKey`, renders `ppp.costo`).
- [x] T2.5 Markup site — line 1765 (`getMarkupColor(p.markup_pvp)`) → added companion
      `<PppLine ppp={p.ppp} markupKey="pvp_clasica" />`. **Key corrected from the stale `"pvp"`
      recorded here before T3.11's rename** — verified `p.markup_pvp` is fed by
      `ppp.record(PPP_KEY_PVP_CLASICA, limpio_pvp)` (`productos_listing.py:1123`), i.e. the
      canonical key is `pvp_clasica`, not `pvp`.
- [x] T2.6 Markup site — line ~1777 (`getMarkupColor(p.markup)`, plain non-cuotas `markup` field)
      — **REOPENED and IMPLEMENTED (2026-07-28)**. Previously closed as "intentionally not
      applicable" because `p.markup` is fed from `producto_pricing.markup_calculado`, a column
      written by an entirely separate batch process
      (`app/services/recalcular_markups_service.py`), and no `limpio` was available in-request to
      reuse. Re-inspection showed this WAS feasible without changing that displayed value: the
      batch computes its `limpio` from inputs that are already resolved (or trivially resolvable
      via the existing batch/prefetch helpers) at every `PppMarkups` call site in
      `productos_listing.py` — pricelist-4 commission (`_lookup_comision(4, grupo_id)` /
      `_lookup_comision_t(4, grupo_id)` in the listing/tienda blocks, `obtener_comision_base(db, 4,
      grupo_id)` in the single-item detail block), the resolved shipping cost
      (`_resolve_envio`/`_resolve_envio_t`/`costo_envio_producto`), and the product's IVA — see
      `recalcular_markups_service.py:55-83`.
      **What changed**: added `PPP_KEY_CLASICA = "clasica"` to `costo_ppp_service.py`'s key
      vocabulary (with the same docstring caveat below), and one `ppp.record(PPP_KEY_CLASICA,
      limpio_clasica)` call in each of the 3 `PppMarkups` accumulator blocks in
      `productos_listing.py` (listing ~line 1027, tienda ~line 2201, detail ~line 2500), each
      REUSING the already-resolved commission/shipping in that scope — the pricelist-4 commission
      lookup in listing/tienda is a pure dict lookup (`_lookup_comision`/`_lookup_comision_t`, no
      extra query), and the detail endpoint's extra `obtener_comision_base` query is a single-item
      endpoint so it is not an N+1 concern. Guarded on `producto_pricing.precio_lista_ml` truthy AND
      the commission being resolvable; when either is absent the key is simply never recorded (the
      frontend shows "sin PPP" for that site, which is correct — never a fabricated value). The
      displayed `markup=producto_pricing.markup_calculado` field itself was NOT touched anywhere.
      Frontend: wired `<PppLine ppp={p.ppp} markupKey="clasica" />` under this site in
      `Productos.jsx`.
      **CAVEAT** (documented in `costo_ppp_service.py`'s module docstring): the displayed clásica
      markup comes from a stored column refreshed by a batch, while its PPP counterpart is computed
      in-request. If the batch has not run since the last price/commission/shipping change, the two
      figures on the same row may be momentarily inconsistent. This is a staleness window in the
      stored column, not a calculation error.
      Tests: `tests/integration/test_productos_ppp.py::TestClasicaMarkupPpp` (matches
      `calcular_markup(limpio, costo_ppp)` for known inputs; key absent when `precio_lista_ml` is
      null) and an added assertion in `TestDistinctInstalmentKeys` (listing endpoint surfaces the
      `clasica` key). Query-count invariant re-asserted unchanged (`TestQueryCount`, still exactly
      ONE `tb_item_transactions` query per request/page). Frontend:
      `PppLine.test.jsx` extended with 2 cases (`clasica` percent render + absent-key "sin PPP").
- [x] T2.7 Frontend unit tests added: `frontend/src/components/PppLine.test.jsx` (7 cases: null
      ppp, undefined ppp, costo+date render, percent-key render, ratio-key `x100` scaling, unknown
      key renders "sin PPP" not a crash, never substitutes `costo` for a missing markup; +2 more
      added with T2.6's reopening — `clasica` percent render and absent-key "sin PPP") and
      `frontend/src/hooks/useProductosOffsets.ppp.test.js` (8 cases for `formatPppMonto` /
      `formatPppFecha`, incl. `0` treated as a real value and dd/mm/aa with no staleness gate).

### Pulled forward from PR3 (per explicit apply-scope instruction)

- [x] T3.1 Line 1933 — `mejor_oferta_markup` group → added companion
      `<PppLine ppp={p.ppp} markupKey="mejor_oferta" />`. Verified `p.mejor_oferta_markup` is fed
      by `ppp.record(PPP_KEY_MEJOR_OFERTA, limpio, percent=False)`
      (`productos_listing.py:993`) — raw-ratio key, handled by `PPP_RATIO_KEYS`.

## PR3 — Frontend: remaining 10 markup variants

Traces to: Requirement "PPP markups render at all display sites" (remaining spots).

One checkbox per remaining site — add companion `<PppLine ppp={p.ppp} markupKey="..." />` under
each:

- [x] T3.1 Line 1933 — `mejor_oferta_markup` group → `markupKey="mejor_oferta"` — DONE in PR2,
      see PR2 section above (pulled forward per explicit apply-scope instruction).
- [x] T3.2 Line ~2050 — `markup_web_real` — **DEVIATION, left undone on purpose (same pattern
      as T2.6)**: `p.markup_web_real` is fed straight from `ProductoPricing.markup_web_real`
      (`producto_pricing.markup_web_real` at `productos_listing.py:1206`/`2368`/`2648`), a stored
      column — verified NO `ppp.record(...)` call site anywhere in `productos_listing.py` feeds
      it. There is no canonical PPP key for this markup. Attaching any `markupKey` here would
      always render "sin PPP", indistinguishable from genuine no-data. Left without a PPP line.
- [x] T3.3 Line 2101 — `markup_3_cuotas` → `markupKey="cuota_clasica_3"` — verified fed by
      `ppp.record(ppp_key_cuota_clasica("3"), limpio_cuota)` (`productos_listing.py:1079`,
      `nombre_cuota.replace("_cuotas", "")` → `"3"`).
- [x] T3.4 Line 2134 — `markup_6_cuotas` → `markupKey="cuota_clasica_6"` — same call site, `"6"`.
- [x] T3.5 Line 2167 — `markup_9_cuotas` → `markupKey="cuota_clasica_9"` — same call site, `"9"`.
- [x] T3.6 Line 2200 — `markup_12_cuotas` → `markupKey="cuota_clasica_12"` — same call site, `"12"`.
- [x] T3.7 Line 2240 — `markup_pvp_3_cuotas` → `markupKey="pvp_cuota_3"` — verified fed by
      `ppp.record(ppp_key_pvp_cuota("3"), limpio_cuota_pvp)` (`productos_listing.py:1159-1160`).
- [x] T3.8 Line 2275 — `markup_pvp_6_cuotas` → `markupKey="pvp_cuota_6"` — same call site, `"6"`.
- [x] T3.9 Line 2310 — `markup_pvp_9_cuotas` → `markupKey="pvp_cuota_9"` — same call site, `"9"`.
- [x] T3.10 Line 2345 — `markup_pvp_12_cuotas` → `markupKey="pvp_cuota_12"` — same call site, `"12"`.
- [x] T3.11 Unified the backend `record()` key vocabulary ahead of PR2/PR3 (backend-only
      commit on PR1): fixed the `calculado_pvp_pvp_3_cuotas` doubled-segment bug and merged
      the 3 divergent names for the same conceptual classic-instalment markup
      (`calculado_{n}_cuotas` / `calculado_pvp_{n}_cuotas` / `cuota_ml_{n}`) into one scheme —
      `mejor_oferta`, `rebate`, `cuota_clasica_{n}`, `pvp_clasica`, `pvp_cuota_{n}`,
      `pvp_clasica_variant`, `pvp_cuota_variant_{n}` (n = 3/6/9/12) — centralised as
      constants/helpers in `costo_ppp_service.py` (module docstring is the single source of
      truth PR2 must consume for its 12 `markupKey` props).
- [ ] T3.12 Full manual pass: with a product that has `costo_ppp` populated, verify all 12
      spots + cost cell show correct PPP lines; with a product that has `costo_ppp = null`,
      verify all 13 spots show "sin PPP" and none silently show a `costo`-derived value.
- [x] T3.13 BUGFIX (2026-07-28): the listing endpoint (`GET /api/productos`) computed the PVP
      markups (`markup_pvp`/`markup_pvp_{n}_cuotas`) TWICE — first pass from
      `ProductoPricing.precio_pvp*` (recorded under `pvp_clasica`/`pvp_cuota_{n}`), then a SECOND
      pass from `PrecioML` (a genuinely different source) that OVERWRITES the displayed
      `markup_pvp*` fields but used to record its PPP companion under the now-removed
      `pvp_clasica_variant`/`pvp_cuota_variant_{n}` keys. Result: the frontend's base-key PppLine
      either showed "sin PPP" for a real displayed value (no `ProductoPricing.precio_pvp`, only
      `PrecioML`), or showed a PPP line derived from a DIFFERENT source than the value on screen
      (both present). Fixed by recording the second pass under the SAME base key
      (`PPP_KEY_PVP_CLASICA` / `ppp_key_pvp_cuota(n)`); `PppMarkups.record()` overwrites on key
      collision so the PPP entry now always describes the number it sits under. Removed the dead
      `PPP_KEY_PVP_CLASICA_VARIANT` / `ppp_key_pvp_cuota_variant()` vocabulary and its docstring
      entries — replaced with a "two-source correspondence rule" note explaining the fix.
      Verified the tienda (`listar_productos_tienda`) and detail (`obtener_producto`) response
      builders do NOT share this two-pass shape: tienda has no PVP markup block at all; detail
      computes PVP markups in a single pass directly from `ProductoPricing.precio_pvp*` (no
      `PrecioML` overwrite) — no change needed in either.
      Same-shape bug also found and fixed at the `mejor_oferta` site (both listing and tienda):
      when a product is `out_of_cards` with an active rebate, `mejor_oferta_markup` gets
      OVERWRITTEN to the rebate markup, but `PPP_KEY_MEJOR_OFERTA` kept the ORIGINAL
      mejor_oferta-derived value (or was never recorded if there was no real ML offer at all) —
      now re-recorded from the rebate's `limpio` at the point of the override, in both endpoints.
      Confirmed `mejor_oferta_markup`'s frontend site (`Productos.jsx` `markupKey="mejor_oferta"`)
      renders the field directly with no separate override, so this backend fix alone closes the
      gap. Confirmed the keyless `<PppLine ppp={p.ppp} />` under the cost cell is intentional (it
      shows the PPP cost itself, not a markup — no key needed).
      Tests: `backend/tests/integration/test_productos_ppp.py`
      `TestPvpKeyCorrespondsToDisplayedValue` (2 cases) and
      `TestMejorOfertaKeyCorrespondsToDisplayedValue` (1 case), TDD red-then-green. Full backend
      suite: 3750 passed, 16 skipped (baseline 3747/16 + 3 new). Frontend: 424 passed, unchanged
      (PppLine contract untouched).

## Cross-cutting / final gate

- [ ] TF.1 Before final backend push of each PR touching `productos_listing.py`: run
      `ruff format app/` in the venv (repeat of T1.25 — CI blocks on drift).
- [ ] TF.2 Confirm golden snapshot diff (T1.23) is empty except the new `ppp` key(s) as the last
      step before requesting review on PR1.
- [ ] TF.3 Update `openspec/changes/productos-costo-ppp/design.md` Open Questions — check off
      "whether the composite index is needed" with the EXPLAIN evidence link once T1.17 resolves.

## Source correction round (2026-07-29, branch `fix/productos-ppp-fuente-aw`)

- [x] TC.1 Verified (against production data + the live GBP ERP "Costo PPP" screen, item 1169) that
      the shipped source `ItemTransaction.it_priceofcostpp` is WRONG — systematically inflated
      (~24%+ on the pinned example). Corrected source: `ItemCostListHistory.iclh_price_aw`,
      `coslis_id=1`, latest `iclh_cd`, tiebreak `iclh_id DESC`.
- [x] TC.2 Removed the invalid ARS→USD-via-today's-rate "display conversion"
      (`costo_display`/`costo_display_moneda`, added 2026-07-28) — display now always shows the
      aw's OWN currency (`moneda`, curr_id-derived), never converted. Conversion to ARS still
      happens, but only internally as `calcular_markup`'s cost input.
- [x] TC.3 Dropped the LATERAL/`ROW_NUMBER()` dialect branching entirely — single portable
      `ROW_NUMBER()` formulation for every dialect; `tb_item_cost_list_history` has no equivalent
      composite index and is much smaller than `tb_item_transactions`, so the LATERAL fast path's
      rationale doesn't carry over. `ix_tit_item_cd_desc` flagged as likely unused by this feature
      now, intentionally NOT dropped (separate decision).
- [x] TC.4 Rewrote `backend/tests/unit/test_costo_ppp_service.py` (23 tests) and
      `backend/tests/integration/test_productos_ppp.py` fixtures (`ItemTransaction` →
      `ItemCostListHistory`) for the new source; added `TestPinnedAgainstKnownErpValue` regression
      test pinning an item-1169-modelled fixture to 38.402760 USD (decoys in other cost lists must
      never win).
- [x] TC.5 Updated `frontend/src/components/PppLine.jsx` + `.test.jsx` for the new payload shape
      (`costo`/`moneda`/`fecha`/`markups`, no `costo_display*`).
- [x] TC.6 Verified sync cadence: `tb_item_cost_list_history` is synced by
      `sync_item_cost_history.n_incremental` every 5 minutes
      (`backend/RELEVAMIENTO_GBP_PARSER_COMPLETO.md`) — not stale.
- [x] TC.7 Appended "SOURCE CORRECTION" sections to `exploration.md` and `design.md` (historical
      content preserved, not deleted) documenting the wrong field, why it looked plausible, and what
      check would have caught it.
- [x] TC.8 Full backend suite: 3756 passed / 16 skipped (baseline on this branch: 3761/16 — the -5
      is fully explained by intentionally deleting 6 now-inapplicable postgres dialect-equivalence
      tests, net +1 new test). Frontend: 436 passed. `ruff format`/`check` clean.

## Data-sanity guard: stale `iclh_price_aw` scale mismatch (2026-07-29)

- [x] TG.1 Added `_is_scale_sane`/`_PPP_RATIO_MIN`/`_PPP_RATIO_MAX` to
      `costo_ppp_service.py`: rejects a row when `iclh_price` is missing/`<=0`, or when
      `iclh_price / iclh_price_aw` (both from the SAME row) falls outside `[0.05, 20]`
      (inclusive). THIRD data-trust failure in this feature — witness item 2780, ratio 1091.
      No fallback to an older row on rejection (documented rationale in code + docstring).
- [x] TG.2 `resolver_ppp_batch`/`_build_ranked_stmt` now also select `iclh_price` (previously
      only `iclh_price_aw`/`iclh_cd`) to validate the guard self-contained, without joining
      `producto_erp` (measurement showed both give the same 42 broken rows).
- [x] TG.3 Added `TestScaleSanityGuard` (9 tests) to `test_costo_ppp_service.py`: witness item
      2780 (aw 1000x too small), inverse item 623 shape (aw 1000x too large), boundary tests at
      exactly 20 and 0.05 (inclusive) plus just-outside each, normal ratio unchanged, and
      `iclh_price` null/zero rejected. Verified `TestPinnedAgainstKnownErpValue` (item 1169,
      ratio 1.12) still passes unaffected.
- [x] TG.4 Updated `costo_ppp_service.py` module docstring ("Scale sanity guard" section) and
      `exploration.md` ("SCALE SANITY GUARD" section) with the witness, measured counts, and the
      explicit "validate an ERP value against a reference in the same row" pattern (third
      instance in this feature).
- [x] TG.5 Coverage note updated: ~77.5% (3215/4150) -> ~76.5% (3173/4150), 42 rows discarded,
      measured 2026-07-29.

## Review Workload Forecast

| Slice | Est. changed lines | Rationale |
|---|---|---|
| PR1 (backend) | ~350-450 | New service file (~120-150 loc incl. `PppSource`/`PppMarkups`/query), `PppPayload` + wiring in `productos_shared.py` (~20), 11 one-line `ppp.record()` insertions + 3 payload-assembly edits (~30), unit+integration tests (~150-200), optional migration (~30-40 if index needed) |
| PR2 (frontend base) | ~150-200 | `useProductosOffsets.js` additions (~30-40), new `PppLine.jsx` (~40-60), 3 render-site insertions + wiring (~30), tests (~40-60) |
| PR3 (remaining markups) | ~150-200 | 10 render-site insertions (~10-15 lines each incl. JSX formatting) + reconciliation pass + manual QA notes |

- **Chained PRs recommended: YES.** PR2 and PR3 both depend on PR1's `ppp` payload shape merging
  first (frontend renders a field that does not exist until PR1 ships); PR3 depends on PR2's
  `PppLine` component and formatter existing. Sequential merge order: PR1 → PR2 → PR3.
- **400-line budget risk**: PR1 is at risk of exceeding 400 lines IF the composite index is
  needed (T1.18-19) AND golden-snapshot fixture setup is non-trivial (new fixture data can easily
  add 100+ lines by itself). Mitigation: if PR1 threatens to exceed budget, split the migration
  (T1.16-1.19) into its own follow-up PR1b, since it is evidence-conditional and independently
  revertible per the design's rollback plan. PR2 and PR3 are comfortably under budget individually.
- **Decision needed before apply**: YES — confirm with the requester (a) whether PR1b split-off
  for the conditional index is acceptable if EXPLAIN shows it's needed, and (b) the exact
  `markupKey` naming convention (T3.11) so frontend and backend don't need a follow-up
  reconciliation commit. `delivery_strategy: ask-on-risk` is satisfied by flagging this now rather
  than mid-apply.

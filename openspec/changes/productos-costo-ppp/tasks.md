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

- [ ] T1.16 **BLOCKED (environment)**: Run `EXPLAIN (ANALYZE, BUFFERS)` on the resolver query
      against a representative page of `item_ids` (staging DB). No staging/Postgres DB is
      reachable from this apply environment — this step MUST be run by someone with staging
      access before the index decision (T1.17) can be made. NOT run in this batch.
- [ ] T1.17 Decision gate: deferred — depends on T1.16 evidence, not yet available.
- [ ] T1.18 (Conditional) `alembic heads` was checked in this environment and returns exactly ONE
      head (`20260724_add_marca_sub_pm`) — safe to generate a migration once T1.17 requires one.
- [ ] T1.19 (Conditional) NOT generated in this PR. Per the explicit sizing decision, if T1.17
      shows the index is needed, it MUST ship as its own separate small PR, not bundled into PR1.
      PR1 as delivered contains NO alembic migration.

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

## PR2 — Frontend base: cost line + first markup group + shared formatter

Traces to: Requirement "PPP markups render at all display sites" (cost cell + first group),
"Explicit no-data state, never a cost fallback", "PPP source date always displayed".

- [ ] T2.1 Add `formatPppMonto` / `formatPppFecha` (dd/mm/aa, no relative wording, no staleness
      styling) to `frontend/src/hooks/useProductosOffsets.js`, alongside
      `calcularMarkupConOffset`/`getMarkupColor`.
- [ ] T2.2 Create `frontend/src/components/PppLine.jsx` — `<PppLine ppp={p.ppp} markupKey="..."
      />`; renders "sin PPP" marker when `ppp` is `null`/`undefined`; never reads `p.costo` or any
      list-cost markup as a substitute.
- [ ] T2.3 If any CRLF/whitespace renormalization is needed on the touched region of
      `Productos.jsx`, commit it SEPARATELY (its own commit, no feature code) before the feature
      commit — do not mix.
- [ ] T2.4 Cost cell — line 1715 `<td>{p.moneda_costo} ${p.costo?.toFixed(2)}</td>` → add
      `<PppLine ppp={p.ppp} />` companion line below it.
- [ ] T2.5 Markup site — line 1765 (`getMarkupColor(p.markup_pvp)`, classica pvp group) → add
      companion `<PppLine ppp={p.ppp} markupKey="pvp" />`.
- [ ] T2.6 Markup site — line 1772 (`getMarkupColor(p.markup)`, classica group) → add companion
      `<PppLine ppp={p.ppp} markupKey="calculado" />`.
- [ ] T2.7 Frontend unit test: `PppLine` renders "sin PPP" when `ppp` is `null`, renders
      `formatPppMonto`/`formatPppFecha` output when populated, and never reads `costo`/list-cost
      markup props.

## PR3 — Frontend: remaining 10 markup variants

Traces to: Requirement "PPP markups render at all display sites" (remaining spots).

One checkbox per remaining site — add companion `<PppLine ppp={p.ppp} markupKey="..." />` under
each:

- [ ] T3.1 Line 1933 — `mejor_oferta_markup` group → `markupKey="mejor_oferta"`
- [ ] T3.2 Line 2044 — `markup_web_real` → `markupKey="web_real"`
- [ ] T3.3 Line 2096 — `markup_3_cuotas` → `markupKey="cuota_ml"` (or the matching 3-cuotas key
      recorded in T1.13/backend)
- [ ] T3.4 Line 2129 — `markup_6_cuotas` → matching key
- [ ] T3.5 Line 2162 — `markup_9_cuotas` → matching key
- [ ] T3.6 Line 2195 — `markup_12_cuotas` → matching key
- [ ] T3.7 Line 2235 — `markup_pvp_3_cuotas` → matching key
- [ ] T3.8 Line 2270 — `markup_pvp_6_cuotas` → matching key
- [ ] T3.9 Line 2305 — `markup_pvp_9_cuotas` → matching key
- [ ] T3.10 Line 2340 — `markup_pvp_12_cuotas` → matching key
- [ ] T3.11 Reconcile backend markup `record()` keys (T1.5-T1.15) against the 12 frontend
      `markupKey` values used in T2.5-T2.6 and T3.1-T3.10 — every frontend key must have a
      matching backend-recorded key; fix any naming drift as part of this PR.
- [ ] T3.12 Full manual pass: with a product that has `costo_ppp` populated, verify all 12
      spots + cost cell show correct PPP lines; with a product that has `costo_ppp = null`,
      verify all 13 spots show "sin PPP" and none silently show a `costo`-derived value.

## Cross-cutting / final gate

- [ ] TF.1 Before final backend push of each PR touching `productos_listing.py`: run
      `ruff format app/` in the venv (repeat of T1.25 — CI blocks on drift).
- [ ] TF.2 Confirm golden snapshot diff (T1.23) is empty except the new `ppp` key(s) as the last
      step before requesting review on PR1.
- [ ] TF.3 Update `openspec/changes/productos-costo-ppp/design.md` Open Questions — check off
      "whether the composite index is needed" with the EXPLAIN evidence link once T1.17 resolves.

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

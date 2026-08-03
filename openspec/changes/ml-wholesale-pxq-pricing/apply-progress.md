# Apply Progress: ml-wholesale-pxq-pricing

## PR 1 — Global collapse toggle (frontend only, independent)

Status: MERGED (PR #1038 into the tracker branch `feat/ml-wholesale-pxq-pricing`).

Shipped with three defects found and fixed during review, in severity order:
(1) after a global expand, manually reopening a node re-exploded its whole
subtree for the rest of the session — children only mount when their parent
opens, so the mount cascade that makes "expand all" work has to stop once the
user takes manual control (`markManual()`, which resets the mode without
advancing the epoch); (2) the sync ignored the catalog-competition sub-panel;
(3) the global-close assertions were vacuous, because `isOpen` alone unmounts
the section, so they passed with the sub-panel sync broken.

- Final diff: 9 files changed, +324/-14 (the review fixes and their tests grew
  it past the ~150 estimate).
- Tests: `pnpm run test` (vitest run) — 35 files / 538 tests passed, including
  new coverage in `treeViewStore.test.js` (epoch/mode defaults, expandAll/
  collapseAll increment epoch, ephemeral partialize exclusion) and
  `TreeNode.test.jsx` (global-open opens nested promo panel, global-close
  closes it, manual toggle after global-open survives).
- Lint: `pnpm run lint` — 0 errors, 1 pre-acknowledged warning
  (`react-hooks/exhaustive-deps` on the epoch-only sync effect in
  `TreeNode.jsx`; intentional per design D6 — the effect must fire only on
  epoch change, not on every `collapseMode` render).
- Files touched: `frontend/src/store/treeViewStore.js`,
  `frontend/src/store/treeViewStore.test.js`,
  `frontend/src/components/promociones/TreeNode.jsx`,
  `frontend/src/components/promociones/TreeNode.test.jsx`,
  `frontend/src/components/promociones/ProductoMLAsPanel.jsx` (wired
  "Expandir todo" / "Colapsar todo" buttons — the tree view UI entry point).

## PR 2 — `ml_pxq_tier` model + migration + permission catalog/backfill + quantity-aware markup

Status: 2a and 2b MERGED (PRs #1040, #1041); 2c open as PR #1042.

SPLIT INTO THREE PRs. The single branch came to 1361 lines against a 400-line
review budget — the design's ~370 estimate did not account for the test volume
strict TDD produces. Rather than ask for a size exception on a money path with
a permissions migration in it, the work was cut along its real seams:

- PR #1040 `feat/pxq-markup-quantity` — the calculation (2a + 2d)
- PR #1041 `feat/pxq-tier-storage` — table, migration, service (2b)
- PR #1042 `feat/pxq-permissions` — permission catalog and backfill (2c)

Ten rounds of pre-push review followed, and the first seven each found a real
money-path defect: a per-unit shipping fallback still reachable through
`grupo_id`; `costo` accepted with no unit attached, so a per-unit figure
inflated the markup by a factor of N (the 1760% golden case was the tell);
`Decimal` columns meeting float constants; the migration and the service
writing different grants while the dry-run reported the service's; a
`FOR UPDATE` that took no lock when the row did not exist; money stored as
binary float. Every one is now covered by a test that fails without the fix.

- Final diffs: #1040 +728, #1041 +657, #1042 +943/-29. Two of the three still
  exceed the 400-line budget after the review rounds added their tests; flagged
  for the reviewer rather than re-split at that point.
- Tests: 64 PxQ tests GREEN; full backend suite 3989 passed / 16 skipped
  (baseline 3927 / 16 — net +62, zero regressions).
- Lint: `ruff format app/` and `ruff check app/` — both clean (`app/models/__init__.py`
  needed `MlPxqTier` added to its `__all__` to silence a real F401).
- Alembic: single head confirmed before and after
  (`20260801_pxq_permisos_backfill` is the new head, chained
  `20260731_ml_catalog_competition` -> `20260801_add_ml_pxq_tier` ->
  `20260801_pxq_permisos_backfill`).

### 2a. Quantity-aware markup (`pxq_markup.py`)
- `backend/app/services/pxq_markup.py`: `ShipmentShippingCost` frozen
  dataclass value object; `resolve_tier_shipping(tier)` reads ONLY
  `tier.costo_envio_total` (no per-unit fallback), returns `None` when
  unset; `calcular_markup_pxq(...)` wraps `calcular_comision_ml_total` /
  `calcular_limpio` UNCHANGED, feeding `precio_unitario * cantidad_minima`
  and the whole-shipment cost. `shipping` parameter has NO default
  (asserted via `inspect.signature`) — fail-closed by construction.
  `pricing_calculator.py` was NOT modified.
- Tests: `backend/tests/services/test_pxq_markup.py` — golden cases
  (1/5/10/30/70 units) matching the canonical chain called directly;
  regression test proving the correct result differs from the old
  per-unit-shipping-times-N bug shape (only visible once `precio_total`
  clears the MONTOT3 envío-gratis bracket); structural tests on the
  shipping parameter and the `ShipmentShippingCost` type.

### 2b. `ml_pxq_tier` model + migration
- `backend/app/models/ml_pxq_tier.py`: `cantidad_minima > 1`
  CheckConstraint, unique `(publicacion_ml_id, cantidad_minima)`,
  `precio_unitario` Numeric(14,2), nullable `costo_envio_total`/`ml_price_id`,
  `estado` String(16), tz-aware timestamps, indexed FKs. `item_id` is the
  MercadoLibre item id (MLA string), denormalized from
  `publicaciones_ml.mla` for the live-vs-mirror compare in PR 3 — NOT the
  ERP integer `productos_erp.item_id`.
- `backend/alembic/versions/20260801_add_ml_pxq_tier.py`.
- `backend/app/services/pxq_tier_service.py`: `create_pxq_tier(...)`
  enforces max 5 tiers per publication and `cantidad_minima > 1` at the
  SERVICE layer (422), ahead of the DB CheckConstraint.
- Tests: `backend/tests/models/test_ml_pxq_tier.py` (constraints),
  `backend/tests/services/test_pxq_tier_service.py` (422s, 6th-tier
  rejection never persisted).

### 2c. Permission catalog + backfill
- `backend/app/services/pxq_permissions_backfill.py`: `pxq.ver` /
  `pxq.escribir` catalog (`ensure_pxq_permission_catalog`) and
  `backfill_pxq_permissions_from_promos(db, dry_run=...)` — derives grants
  from LIVE `promos.escribir` state (roles + positive/negative user
  overrides), never a hardcoded role list (deliberate departure from
  `20260713_add_permisos_promociones.py`'s precedent).
- `backend/alembic/versions/20260801_pxq_permisos_backfill.py`: does NOT
  import the service. It carries its own self-contained SQL (a migration is an
  immutable snapshot; coupling it to the ORM breaks an upgrade from scratch the
  day a model gains a NOT NULL column). Equivalence is held by
  `test_migration_sql_produces_the_same_grants_as_the_service`, which executes
  the migration's statements and compares the resulting grants. Chained after
  the table migration.
- `backend/scripts/pxq_permissions_dry_run.py`: read-only dry-run script
  (task 2c.20) — prints roles/users/negative-overrides counts, writes
  NOTHING (`dry_run=True`, explicit rollback). NOT run against any real
  environment by this apply — must be run against production-like/staging
  data and its counts recorded in the PR description before the backfill
  migration is applied anywhere real.
- Tests: `backend/tests/services/test_pxq_permissions_backfill.py` (7
  covering catalog distinctness, role backfill, no-grant role, positive and
  negative overrides, dry-run writing nothing, all three counters not
  re-counting work already done, and migration/service parity by executing the
  migration SQL).

### 2d. Base-price boundary (structural)
- `backend/tests/unit/test_pxq_base_price_boundary.py`: AST scan that walks
  ALL of `app/` and matches on file name (not a per-directory glob list, which
  had missed `app/routers/`), covering imports and attribute access
  over `app/services/pxq_*.py`, `app/services/ml_pxq_*.py`,
  `app/api/endpoints/pxq*.py`, `app/models/ml_pxq_*.py` (generic by path
  pattern, covers PR 3's future modules without editing this test again).
  Includes a synthetic-violation test proving the scan actually detects
  the forbidden shape (not vacuously green).

### 2e. Wrap-up
- `ruff format app/` / `ruff check app/` clean.
- Full suite: 3958 passed / 16 skipped (was 3927 / 16 — net +31, zero
  regressions).
- Line count: 1361 across the three PRs, over the ~370 estimate — split rather
  than excepted.

## PR 3a — Pure array-replace diff function (tasks 29-38)

Status: DONE locally, NOT PUSHED (per instructions — commit only, no push/PR).
Branch `feat/pxq-array-diff`, targets the tracker `feat/ml-wholesale-pxq-pricing`,
on top of merged #1038/#1040/#1041/#1042.

- `backend/app/services/pxq_diff.py`: pure function `diff_pxq_tiers(live_tiers,
  desired_tiers, *, allow_clear=False) -> PxqDiffResult`. No DB session, no
  HTTP. Value objects `LiveTier`/`DesiredTier` normalize all money to
  `Decimal` via `Decimal(str(value))` (never `Decimal(float)` directly) so a
  JSON-sourced float and a DB-sourced `Decimal` compare equal.
- Reconciliation resolves an ambiguity between design.md's terse pseudocode
  and its own worked scenarios (matched-id-differs appearing both as a
  "divergence -> refuse" and as "modify -> delete+create"): disambiguated via
  each `DesiredTier.estado`. `estado="listo"` (not yet synced, i.e. an
  intentional local edit) on a matched-but-differing id -> **modify**
  (delete old id + create new, mutated id never re-sent). `estado="sincronizado"`
  (mirror believes it's already in sync) on a matched-but-differing id ->
  **divergence, refuse** (an external actor changed it on ML). A mirror
  `ml_price_id` absent from the live read entirely is always a divergence
  refusal regardless of `estado`. A live tier not referenced by any desired
  row's `ml_price_id` is preserved as an untracked keep (spec: "Unmirrored
  live tier is preserved") — the one exception is the empty-desired-with-
  `allow_clear=True` full wipe, which intentionally emits `[]` and drops even
  untracked live tiers, since the caller explicitly asked to clear everything.
  This deviates from a literal reading of design.md line 54's phrase "live id
  not in mirror -> refuse", which — read against spec.md's own scenario and
  tasks.md task 33 — describes the mirror-ml_price_id-absent-from-live case,
  not the untracked-live-tier case; flagged as a risk for PR 3/review to
  confirm against the design author's intent.
  Max 5 desired tiers enforced (`too_many_tiers` refusal), consistent with
  the service-layer 422 in PR 2b (this is a second, defense-in-depth check
  at the diff layer, not a duplicate of that endpoint validation).
- Tests: `backend/tests/services/test_pxq_diff.py` — 13 tests: keep, create,
  delete, modify, unmirrored-live-preserved, divergence (matched-differs +
  id-absent), divergence-refusal-builds-no-partial-array, ids-only-from-live
  invariant, empty-desired guard (refuse + allow_clear wipe), max-5 refusal,
  Decimal/float normalization. Every assertion checks the exact emitted
  array/refusal payload, not just counts or `ok`/`not ok`. Mutation-tested
  the core comparison branch by hand (forced `matches = True`) — 3 of 13
  tests failed as expected, confirming they were not vacuous, then reverted.
- Boundary: covered automatically by the existing PR 2d AST scan
  (`test_pxq_base_price_boundary.py`) via the `pxq*` filename prefix — no
  edit needed to that test.
- Lint: `ruff format app/` — clean (2 files reformatted on first pass,
  clean thereafter). `ruff check app/` — clean.
- Tests: targeted `test_pxq_diff.py` + `test_pxq_base_price_boundary.py` —
  18 passed. Full suite run once: `4004 passed, 16 skipped` (baseline for
  this branch was 3989/16 — net +15, zero regressions/failures).
- Commit: `feat(pxq): add pure array-replace diff function for ML PxQ tiers`
  on `feat/pxq-array-diff` (local only, not pushed).
- Diff size: 459 lines (262 impl incl. module docstring, 197 tests) — over
  the ~120-150 carve-out estimate, driven by the same strict-TDD test volume
  and heavy inline rationale documentation pattern seen in PR 2; flagged for
  the reviewer, not re-split (PR 3a is already the split-out unit).

## PR 3b (write path) — SHIPPED, MERGED into tracker

Status: MERGED into `feat/ml-wholesale-pxq-pricing` (PR #1046
`feat/pxq-write-service` + PR #1047 `feat/pxq-endpoints`). Kill-switch
(`PXQ_WRITE_ENABLED=False` default), eligibility gates, `ml_pxq_write_service`,
`GET /api/pxq/{item_id}/live` (pool-safe) and `POST /api/pxq/{item_id}/sync`
are all live in `backend/app/routers/pxq.py`. See `sdd/ml-wholesale-pxq-pricing/apply-progress`
engram observation for the full write-path detail (gate order, snapshot rule,
runtime `ProductoPricing` boundary assert). This is the API the PR 4a panel
below consumes.

## PR 4a — read-only live+mirror panel (this slice)

Status: DONE locally, NOT PUSHED (per instructions — commit only, no push/PR).
Branch `feat/pxq-panel-lectura`, off tracker `feat/ml-wholesale-pxq-pricing`
(backend PR 3b already merged there).

Scope deliberately excludes tier create/edit/delete forms, the shipping-cost
input, the sync button, and divergence-resolution actions — those are PR 4b,
a separate run, so the read panel can ship and be verified in production
without any write path being exercised.

- `frontend/src/components/promociones/PxqPanel.jsx` (NEW): reads
  `GET /pxq/{item_id}/live` via a new `pxqAPI.getLive` (in
  `frontend/src/services/api.js`), through the existing `useLazyResource`
  cache-ref pattern. Renders live ML tiers and local mirror tiers side by
  side, ALWAYS (not gated behind a divergence — this is the requirement that
  drove the whole feature: "no me gusta que nada suceda en silencio").
  `live_status: "unavailable"` (`live_tiers: null`) renders a distinct
  "no se pudo leer el estado en vivo" message, never "0 tramos en vivo" —
  that would falsely claim ML has none when the truth is unknown. A mirror
  tier whose matched `ml_price_id` disagrees with (or is absent from) the
  live read is marked "Diverge de ML" informationally only; no
  resolution/sync action is offered here.
  Gated on `pxq.ver` via `usePermisos` — invisible (not an error/403) without
  the permission, matching the gating pattern of the sibling
  `CatalogCompetitionPanel`. The permission check happens inside the fetcher
  itself (not just a render-time early return), because `useLazyResource`
  fires its fetch effect unconditionally on mount.
- `frontend/src/components/promociones/TreeNode.jsx`: adds a "Precios
  mayoristas" sub-spoiler beside "Promociones"/"Competencia catálogo", threads
  a new `pxqCacheRef` prop through every recursive call (including the
  familia-hidden passthrough branch), and joins `pxqOpen` to the existing
  `collapseEpoch` sync `useEffect` so "Expandir todo"/"Colapsar todo" include
  it — the catalog-competition panel was previously omitted from this exact
  effect and had to be fixed once already; this slice adds a regression test
  proving the new panel joined it instead of repeating that omission.
- `frontend/src/components/promociones/ProductoMLAsPanel.jsx` and
  `frontend/src/pages/Productos.jsx`: thread `pxqCacheRef` (a new
  `useRef(new Map())` alongside the existing `mlasCacheRef`/`promosCacheRef`/
  `catalogCompetitionCacheRef`, cleared on the same `productIdsKey` effect)
  down to `TreeNode`.
- `frontend/src/components/promociones/promociones.module.css`: new
  `.pxqColumns`/`.pxqColumn`/`.pxqColumnTitle`/`.pxqTierRow`/
  `.pxqTierRowDivergent`/`.pxqUnavailable` classes — deliberately not reusing
  `.filterMessage` (that name means something else; reusing it was a review
  finding on a sibling PR).
- Tests: `frontend/src/components/promociones/PxqPanel.test.jsx` (new,
  RED-first: permission gate invisibility, loading, error+retry,
  unavailable-vs-empty distinction, side-by-side render, divergence marking
  with no resolution control offered) and two additions to
  `TreeNode.test.jsx`'s collapse-epoch describe block (global-open opens the
  PxQ panel, global-close closes it).
- `pnpm run test` (vitest run): 36 files / 547 tests passed (was 35/538 —
  net +9, zero regressions).
- `pnpm run lint` (eslint): clean, zero warnings/errors.
- Diff size: 380 lines across 8 files (+375/-5) — under the 400-line budget.
- Commit: `feat(pxq): add read-only wholesale tiers panel`, `6a1fae45`, on
  `feat/pxq-panel-lectura` (local only, not pushed).

## PR 4b (write path UI) — NOT STARTED (out of scope for this apply run)

Next apply run should pick up PR 4b: tier create/edit/delete form (client-side
max-5 / `min_purchase_unit > 1` mirrors of the backend validation, not a
replacement), the shipping-cost input, the sync button wired to
`POST /pxq/{item_id}/sync`, the divergence banner that DISABLES the sync
action until resolved (no silent local-wins), and the `allow_clear`
confirmation flow — all rendered BELOW the PR 4a read panel inside the same
"Precios mayoristas" sub-spoiler, on top of `feat/pxq-panel-lectura`.

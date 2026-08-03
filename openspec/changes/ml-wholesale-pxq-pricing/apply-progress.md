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

## PR 4b — backend tier CRUD (this slice), FE form NOT STARTED

Scope of this apply run was backend-only: create/edit/delete endpoints for
`MlPxqTier` rows, so PR 4c's authoring UI has something to call. Branch
`feat/pxq-tier-crud`, off the tracker `feat/ml-wholesale-pxq-pricing` (on top
of merged backend PR 3b).

- `backend/app/services/pxq_tier_service.py` — added `update_pxq_tier` and
  `delete_pxq_tier` beside the existing `create_pxq_tier`. `update_pxq_tier`
  re-enforces `cantidad_minima > 1` and the no-duplicate-`cantidad_minima`
  check (scoped to the tier's own publication, excluding itself) as clean
  422s, and deliberately never writes `cantidad_sincronizada` /
  `precio_sincronizado` — those columns are the ML-confirmed snapshot that
  makes the write path a three-way merge; only a confirmed write
  (`pxq_confirm`) may advance them, or the next sync would treat a fresh
  local edit as "nobody touched anything" and silently overwrite it.
  Verified this holds by deliberately making an edit advance the snapshot and
  watching `test_update_tier_never_advances_the_synced_snapshot` fail, then
  reverting. `delete_pxq_tier` removes the local mirror row only — it does
  NOT reach MercadoLibre; the array-replace diff (PR 3) simply omits the row
  on the next sync, so a tier with an `ml_price_id` leaves that sync pending.
- `backend/app/routers/pxq.py` — three new endpoints: `POST
  /pxq/{item_id}/tiers` (201), `PATCH /pxq/{item_id}/tiers/{tier_id}`, `DELETE
  /pxq/{item_id}/tiers/{tier_id}` (204). All gated on `pxq.escribir` via a new
  `_require_pxq_write` helper (mirrors `_require_pxq_read`'s shape). They use
  the ordinary `get_current_user` + `Depends(get_db)` — NOT the
  transient-user/short-session pattern the live endpoint uses — because they
  only touch our own DB, never MercadoLibre; each endpoint's docstring says so
  explicitly so the difference isn't read as an oversight later. Update/delete
  resolve the tier by `tier_id` but also check the path's `item_id` matches
  the tier's stored `item_id`, treating a mismatch as 404 (same as
  not-found) rather than silently operating across publications.
- Tests: 8 new cases in `backend/tests/services/test_pxq_tier_service.py`
  (update happy path, snapshot-preservation, 404, `cantidad_minima<=1` 422,
  duplicate 422, decimal-not-float) + new
  `backend/tests/unit/test_pxq_router_tier_crud.py` (10 cases: create/edit/
  delete happy paths, unknown-item-id 404, wrong-item-id-on-existing-tier 404,
  missing-`pxq.escribir` 403 for all three endpoints) calling router functions
  directly against the real `db` fixture, same style as the existing live-read
  endpoint tests — no TestClient/full auth stack needed.
- Full backend suite: `ENVIRONMENT=testing DATABASE_URL=sqlite:///./test.db
  ./.venv/bin/python -m pytest tests/ -q` → 4071 passed, 16 skipped (baseline
  4053 passed + 18 new tests, zero regressions). `ruff format`/`ruff check`
  clean on the two changed `app/` files.
- Diff: 593 lines across 4 files (+593/-2) — over the 400-line review budget
  as one unit. Split into two commits that each individually stay under
  budget: `feat(pxq): add update/delete tier service functions` (236 lines:
  service + its tests) and `feat(pxq): add tier create/edit/delete endpoints`
  (359 lines: router + its tests). Both committed locally on
  `feat/pxq-tier-crud`, NOT pushed, no PR opened.
- Explicitly NOT built in this slice: any React component/form (PR 4c),
  changes to the existing `/live` or `/sync` endpoints beyond adding imports.

## PR 4c — tier authoring form (this slice), sync/allow_clear NOT started

Scope of this apply run was the local-only authoring form: create/edit/delete
tiers against PR 4b's CRUD endpoints, no MercadoLibre traffic. Branch
`feat/pxq-form-tramos`, stacked on `feat/pxq-tier-crud-endpoints` (PR #1050,
open, off tracker `feat/ml-wholesale-pxq-pricing`).

- `frontend/src/services/api.js` — added `createTier`/`updateTier`/
  `deleteTier` to `pxqAPI`, matching `PxqCreateTierRequest`/
  `PxqUpdateTierRequest`'s field names exactly (`cantidad_minima`,
  `precio_unitario`, `costo_envio_total`).
- `frontend/src/components/promociones/PxqPanel.jsx` — new
  `PxqTierAuthoring` sub-component, rendered below the existing live-vs-mirror
  columns and gated on `pxq.escribir` (read stays `pxq.ver`; a read-only user
  sees the panel above with no editing affordance at all, never a button that
  would 403). Per tier: cantidad mínima, precio unitario, costo de envío del
  bulto, inline edit-in-place and a two-step delete confirmation. "Agregar
  tramo" disables at 5 tiers client-side, but a 422 from either endpoint
  (duplicate quantity, `cantidad_minima<=1`, a race past the 5-tier disable)
  is still caught and its message shown verbatim — the client mirrors the
  backend's rules, it does not reimplement or trust them. A tier whose
  `costo_envio_total` is `null`/`undefined` renders a visible "Incompleto:
  falta el costo de envío del bulto" badge instead of looking ready — there is
  no default and no per-unit-shipping fallback anywhere in this form; that
  fallback is the exact bug PR 2's `resolve_tier_shipping` (no-default,
  `inspect.signature`-asserted) made structurally impossible on the backend,
  and reintroducing it here would defeat that. The create form hides itself
  while a row is mid-edit, avoiding a duplicate-labelled-input ambiguity for
  both users and tests. `useLazyResource`'s `reload` now returns its promise
  (was previously fire-and-forget) so a create/edit/delete can `await` the
  list refresh before clearing its own submitting state.
- `frontend/src/components/promociones/promociones.module.css` — new
  `.pxqAuthoring`/`.pxqTierEditRow`/`.pxqIncompleteBadge` classes, not reused
  from the read panel's `.pxqTierRow` family (those rows are plain text; these
  carry inputs and buttons).
- Tests: `frontend/src/components/promociones/PxqPanel.test.jsx` — 8 new
  cases (RED-first): editing affordances fully hidden for `pxq.ver`-only,
  incomplete-tier badge, create with exact payload shape + list reload,
  max-5 disables the button, 422 surfaced on create, edit via PATCH with the
  changed-fields shape, delete requires explicit confirmation before the
  DELETE call fires. Verified the incomplete-badge test is load-bearing by
  forcing `isIncomplete` to always return `false`, watching that one test
  fail (others stayed green), then reverting.
- `pnpm run test` (vitest run): 36 files / 554 tests passed (was 36/546 before
  this slice — net +8, zero regressions).
- `pnpm run lint` (eslint): clean, zero warnings.
- Diff: 455 lines across 5 files (+455/-11) — over the 400-line budget as one
  unit. Not split further: this is a single cohesive TDD cycle (one new
  sub-component plus its tests plus the three API calls it needs), and
  breaking it into a test-only/impl-only pair would not have produced two
  independently reviewable units the way PR 4b's service/router split did.
  Flagged for the reviewer rather than trimmed scope.
- Commit: `feat(pxq): add wholesale tier authoring form`, `54a2827e`, on
  `feat/pxq-form-tramos` (local only, not pushed, no PR opened).
- Explicitly NOT built in this slice (PR 4d, separate run): the sync button,
  `POST /sync` call, outcome/status handling for a sync, the
  divergence-resolution banner, the `allow_clear` confirmation flow.

Next apply run: PR 4d — sync button + `allow_clear` confirmation + divergence
banner (disables sync until resolved, no silent local-wins) — wires PR 3b's
`POST /pxq/{item_id}/sync` into this same panel, on top of PR 4c's form.

## PR 4d — sync action, full outcome handling, divergence banner (SHIPPED locally)

Shipped locally on `feat/pxq-sync-ui`, off tracker
`feat/ml-wholesale-pxq-pricing`. One commit, not pushed, no PR opened:
`838fdb4f` (366 lines: component + API call + CSS + tests).

This is the LAST slice of the feature — every remaining out-of-scope item
from PR 4a/4c is closed.

- `frontend/src/services/api.js` — added `pxqAPI.sync(itemId, allowClear=false)`
  posting `{ allow_clear }` to `POST /pxq/{item_id}/sync`, matching
  `PxqSyncRequest` exactly.
- `frontend/src/components/promociones/PxqPanel.jsx` — new `PxqSyncControl`
  sub-component, rendered below `PxqTierAuthoring`, gated on `pxq.escribir`
  (same as the authoring form). `syncOutcomeMessage(httpStatus, detail)` maps
  every distinct backend `status` from `_SYNC_STATUS_TO_HTTP` to its own
  Spanish message — collapsing these was explicitly the thing to avoid, since
  the backend went through review rounds to keep them separate:
  - 403 → permissions message, textually distinct from `disabled`.
  - `disabled` (503) → "función apagada", explicitly NOT a permissions message.
  - `rejected_not_eligible` (422) → permanent, about the account/item.
  - `rejected_eligibility_unknown` (503) → transient, retry-friendly wording.
  - `rejected_read_unavailable` (503) → nothing was written, safe to retry.
  - `rejected_by_proxy` (422) → surfaces `detail.reason` when present.
  - `submitted_unconfirmed` / `ambiguous_needs_reconcile` (502, same message)
    → explicitly neither success nor a plain failure: tells the user the
    outcome is unknown and to re-read live state before retrying. Does NOT
    call `reload()` on this branch and does NOT render a success or a bare
    "error" string (both asserted directly in tests).
  - 409 `divergence` → handled separately from the message map: renders a
    dedicated banner (`.pxqDivergenceBanner`) listing each `divergences[]`
    entry's `reason`, `live`, and `desired` side by side. No auto-resolve, no
    "forzar" button — resolution is manual (edit tiers, sync again).
  - 200 `sincronizado` → success message, then `await onSynced()` (the
    panel's existing `reload()`, whose promise PR 4c already made awaitable)
    so the live column reflects what ML now holds.
  Clearing all tiers: when `mirrorTiers.length === 0`, clicking sync does NOT
  call the API directly — it shows an inline confirm (same
  `.applyConfirm` pattern as the delete-tier confirm, not `window.confirm`)
  stating every wholesale tier will disappear from the publication, and only
  sends `allow_clear=true` after that explicit confirmation.
- `frontend/src/components/promociones/promociones.module.css` — new
  `.pxqDivergenceBanner`/`.pxqDivergenceItem` classes, own names, design
  tokens only (no hardcoded colors).
- Tests: `frontend/src/components/promociones/PxqPanel.test.jsx` — 11 new
  cases covering the sync button's permission gate, the direct-sync path, the
  allow_clear confirm gate, all nine distinct outcomes (403, 503×3,
  422×2, 409 divergence with both sides rendered, 502×2), and that the 502
  pair never renders a success or bare-error string. One pre-existing PR 4a
  test (`marks a divergent tier visibly...`) asserted no button matching
  `/resolver|sincronizar/i` existed at all — that assertion predated this
  slice's legitimate sync button; narrowed it to `/^resolver$/i` (an inline
  per-row resolve action, which still correctly does not exist) rather than
  weakening it further.
- Mutation check: renamed the `rejected_not_eligible` case label so it could
  never match, watched exactly the one test asserting that message fail
  (all 565 others stayed green), reverted.
- `pnpm run test` (vitest run): 36 files / 566 tests passed (was 36/555 —
  net +11, zero regressions).
- `pnpm run lint` (eslint): clean, zero warnings.
- Diff: 366 lines across 4 files (+366/-6) — within the 400-line budget as
  one unit; not split (outcome handling and the divergence banner share the
  same component and message map, so a seam there would not have produced two
  independently reviewable units).
- Commit: `feat(ml-wholesale-pxq): sync action with full outcome handling and
  divergence banner`, `838fdb4f`, on `feat/pxq-sync-ui` (local only, not
  pushed, no PR opened).

This closes out the ml-wholesale-pxq-pricing feature's frontend slices
(PR 4a read panel, PR 4c authoring form, PR 4d sync). All local commits are
independent, unpushed branches stacked on the tracker branch; nothing here
implies anything is live until each is actually merged.

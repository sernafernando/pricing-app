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

## PR 3, 3a, 4 — NOT STARTED (out of scope for this apply run)

Next apply run should pick up PR 3 (kill-switch, eligibility gates, diff/
reconcile function, live-read + sync endpoints), on top of the tracker branch
once #1042 lands. Design/tasks flag PR 3 as High budget risk with a pre-declared
3/3a split contingency — re-estimate honestly before starting rather than
discovering an overage mid-apply.

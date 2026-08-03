# Proposal: MercadoLibre Wholesale (PxQ) Pricing

## Intent

Sellers cannot manage MercadoLibre B2B wholesale price-by-quantity (PxQ) tiers from this app, so
wholesale pricing is set by hand in ML with no markup validation. Two concrete costs today:

- **Wrong economics.** `calcular_limpio` subtracts ONE unit's shipping from an N-unit order
  (`pricing_calculator.py:295-337`), understating cost by roughly $37.000 on a 30-unit order and
  inflating reported markup. Any wholesale tier priced off today's numbers loses money silently.
- **Unusable UI.** The nested spoilers in the publication tree (producto -> MLA -> promos) must be
  opened one by one; adding a PxQ panel per MLA makes that worse.

## Scope

### In Scope

1. **Global collapse control** — one synchronized toggle that opens/closes every section across all
   MLAs, including nested promo panels.
2. **PxQ tier storage + ML write path** — local tier table (source of truth), Alembic migration,
   read/write endpoints, kill-switched fail-closed ML write.
3. **Quantity-aware markup** — reuse `calcular_comision_ml_total` / `calcular_limpio` with
   `precio * cantidad` and whole-shipment `costo_envio`; surface per-tier clean markup.
4. **Fail-closed shipping resolution** — manual per-tier value wins; otherwise the tier is marked
   incomplete and refused for ML write.

### Out of Scope (non-goals)

- **B2C PxQ.** Restricted by ML to automotive tire domains (MLB2233, MLA22195, MLM5686); this
  catalog is networking / consumer electronics. Assumption to confirm: B2B-only is acceptable.
- **Weight-derived shipping cost.** No weight field exists in `backend/app/models/`; deferred to a
  later slice (see PR 4).
- Automatic/bulk tier generation, scheduled re-pricing, non-ML marketplaces.
- Changing the fee formula itself. The formula is correct; only its inputs were wrong.

## Capabilities

### New Capabilities

- `ml-wholesale-pxq`: local PxQ tier model, quantity-aware markup, eligibility + kill-switch gated
  ML write, fail-closed shipping resolution.
- `tree-view-collapse`: globally synchronized expand/collapse across the publication tree.

### Modified Capabilities

- None. No existing `openspec/specs/` capability exists yet.

## Approach

**Markup.** No new calculator. Callers pass `precio * cantidad` and the whole-shipment shipping
cost. The fixed-charge bracket (`pricing_calculator.py:276-283`) is already total-based and correct.

**Tier storage.** `POST /items/{ITEM_ID}/prices/standard/quantity` REPLACES the entire prices array;
it is not a PATCH. A local table is therefore mandatory to diff keep (`{"id": ...}`) / create
(object without id) / delete (omit id) / modify (delete + create). Up to 5 tiers per publication.

Proposed table `ml_pxq_tier`: `id`, `publicacion_ml_id` (FK, indexed), `item_id` (indexed),
`cantidad_minima`, `precio_unitario`, `costo_envio_total` (nullable), `ml_price_id` (nullable),
`estado` (`incompleto` | `listo` | `sincronizado`), `usuario_id` (FK, indexed), timestamps.
Migration `YYYYMMDD_add_ml_pxq_tier.py`.

**Shipping resolution (fail-closed).** Precedence: manual `costo_envio_total` -> weight-derived
(future) -> **refuse**. Never fall back to per-unit `costo_envio`; that is the original bug behind a
default. Incomplete tiers are stored and displayed but never written to ML.

**Write path.** Mirror `ml_promotions_write_service.py` exactly: new setting `PXQ_WRITE_ENABLED`
default OFF in code, checked FIRST; eligibility validated BEFORE any POST (seller `business` tag via
`GET /users/{USER_ID}`; item tag `standard_price_by_quantity`); fresh LIVE read of current tiers
immediately before the write, never cached; all traffic via the `ml_webhook_client.py` proxy.

**markup_rebate / markup_oferta — explicit conclusion.** These stored columns on `productos_pricing`
derive from `precio_lista_ml`, the BASE list price, and product-list filters query them. PxQ tiers
are *additional* quantity-bracket prices; they never change `precio_lista_ml`. Therefore a PxQ write
MUST NOT recompute `markup_rebate` / `markup_oferta`, and MUST NOT touch `productos_pricing` at all.
The one exception that would re-arm the hard rule: if a PxQ operation ever also writes the base
price (e.g. a quantity=1 tier mapped onto the list price), that is a base-price write and the
recompute-in-the-same-transaction rule applies in full. The design phase must assert this boundary
in code, not by convention.

**Frontend collapse.** Add an epoch counter plus tri-state (`all-open` / `all-closed` / `manual`) to
`treeViewStore.js`. Each `TreeNode` syncs its local `isOpen`/`promosOpen` from the epoch, so a later
manual toggle by the user is not fought by the global state.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/models/ml_pxq_tier.py` | New | Tier model |
| `backend/alembic/versions/YYYYMMDD_add_ml_pxq_tier.py` | New | Migration, FKs indexed |
| `backend/app/services/ml_pxq_write_service.py` | New | Kill-switch, eligibility, diff, write |
| `backend/app/services/pricing_calculator.py` | Modified | Quantity-aware call sites only |
| `backend/app/api/endpoints/` | New | PxQ CRUD + sync, `response_model`, permissions |
| `backend/app/core/config.py` | Modified | `PXQ_WRITE_ENABLED` default `False` |
| `frontend/src/store/treeViewStore.js` | Modified | Collapse epoch + tri-state |
| `frontend/src/components/promociones/TreeNode.jsx` | Modified | Sync from epoch |

## Testing Strategy (strict TDD)

Tests first, then implementation, for every slice.

- **Backend** (`pytest tests/ -v --tb=short` from `backend/`, `ENVIRONMENT=testing`,
  `DATABASE_URL=sqlite:///./test.db`): quantity-aware markup golden cases against the verified
  shipping table (1/5/10/30/70 units); the regression case proving one-unit shipping is no longer
  subtracted from an N-unit order; tier diff (keep/create/delete/modify) with the array-replace
  semantic; kill-switch OFF blocks the write; eligibility failure blocks the write; incomplete tier
  refused; an assertion that a PxQ write leaves `markup_rebate`/`markup_oferta` untouched.
- **Frontend** (`pnpm run test` / `vitest run`, not CI-gated): global toggle drives every node;
  manual toggle after a global toggle is preserved.
- `ruff format app/` before every backend push — Backend Lint CI enforces it.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Write deletes live tiers never mirrored locally | High | Fresh live read + reconcile before every write; kill-switch OFF by default |
| Shipping cost wrong -> money loss | High | Fail closed; no silent per-unit fallback; manual value required for slice 1 |
| Seller/item not PxQ-eligible | Med | Validate `business` tag and `standard_price_by_quantity` before any POST |
| Collapse epoch fights manual user toggles | Med | Tri-state with `manual` escape; explicit test |
| PxQ write accidentally touches base price | Low | Service asserts it never writes `productos_pricing` |
| B2B-only assumption wrong | Low | Stated as an assumption; B2C is a declared non-goal |

## PR Slicing Plan (400-line budget)

Exploration signalled 3-4 PRs; validated as **4**. Chained PRs are needed — recommend
`ask-on-risk` surfaces this before apply.

| # | Slice | Est. lines | Depends on | Autonomous value |
|---|-------|-----------|------------|------------------|
| 1 | Global collapse toggle (store + TreeNode + tests) | ~150 | — | Ships alone; pure UX win, no backend |
| 2 | Tier model + migration + quantity-aware markup + tests | ~350 | — | Correct math and storage, no ML write |
| 3 | ML write path: kill-switch, eligibility, diff, sync endpoint + tests | ~380 | 2 | Write enabled behind a flag defaulting OFF |
| 4 | PxQ tier UI panel in the tree + tests | ~300 | 1, 3 | User-facing tier management |

PR 1 is independent and can merge first or in parallel. PRs 2 -> 3 -> 4 chain: PR 2 targets the
feature branch, PRs 3 and 4 target the immediately previous branch. Every slice must ship with a
clean diff against its parent — no forward dependency: PR 3 is safe to merge alone because the
kill-switch defaults OFF, and PR 4 renders whatever PR 3 exposes.

Weight-derived shipping (shipping precedence path 2) is deferred entirely and is NOT part of this
plan.

## Rollback Plan

- PR 3/4: set `PXQ_WRITE_ENABLED=False` — no ML traffic, no data mutation. This is the primary
  rollback and needs no deploy revert.
- Data: `alembic downgrade -1` drops `ml_pxq_tier`. The table is additive; nothing else reads it, so
  the drop is safe. Live ML tiers are unaffected by dropping the local mirror.
- PR 1: revert the store commit; nodes fall back to local `useState`.
- No existing pricing column is written by this change, so no pricing data can be corrupted.

## Dependencies

- `ml-webhook` proxy availability for live reads and writes.
- ML seller account carrying the `business` tag (verify before enabling PR 3).
- No new third-party packages.

## Success Criteria

- [ ] Markup for an N-unit tier subtracts the whole-shipment shipping cost, not one unit's, proven
      by a regression test against the verified 1/5/10/30/70-unit table.
- [ ] A tier with no resolvable shipping cost is marked incomplete and is never written to ML.
- [ ] A sync writes the full desired tier array and does not delete tiers the user intended to keep.
- [ ] `PXQ_WRITE_ENABLED=False` blocks every write path, verified by test.
- [ ] `markup_rebate` / `markup_oferta` are provably unchanged by any PxQ operation.
- [ ] One toggle opens and closes all sections across all MLAs; a subsequent manual toggle sticks.
- [ ] All four PRs individually under 400 changed lines.

## Proposal question round

Interactive mode requested a question round, but this executor cannot prompt the user directly.
These questions need answers (or an explicit skip) before spec/design. Each has a working
assumption so the pipeline is not blocked.

1. **B2C scope.** Assumption: B2B-only is correct because B2C PxQ is limited to automotive tire
   domains. Confirm no tire/automotive catalog exists.
2. **Tier authoring workflow.** Assumption: tiers are entered manually per publication, one MLA at a
   time. Is bulk authoring across MLAs needed in the first slice?
3. **Manual shipping cost entry.** Assumption: the user enters `costo_envio_total` per tier from
   ML's wholesale simulator. Is that acceptable operationally, or does fail-closed block too much
   real work until weight-derived shipping ships?
4. **Permissions.** Assumption: PxQ write reuses the same permission gate as promotion writes. Is a
   separate, narrower permission wanted for the money path?
5. **Divergence handling.** Assumption: when live ML tiers differ from the local mirror, we surface
   the divergence and refuse to write until the user resolves it. Is silent local-wins acceptable
   instead?

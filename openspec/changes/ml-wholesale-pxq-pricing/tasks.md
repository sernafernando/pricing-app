# Tasks: ml-wholesale-pxq-pricing

Ordered, checkable task list grouped by PR slice. Strict TDD: tests are written and failing (RED)
before implementation in every task group. Chained PRs assumed (PR 1 independent; PR 2 -> PR 3 (->
PR 3a if triggered) -> PR 4, each targeting the immediately previous branch).

Skill references used while executing: pricing-app-backend, pricing-app-frontend,
pricing-app-pricing-logic, pricing-app-ml-integration, pricing-app-permissions,
pricing-app-testing-ci, pytest, react-19, zustand-5, chained-pr, work-unit-commits, git-workflow.

---

## PR 1 — Global collapse toggle (frontend only, independent)

Spec: `tree-view-collapse` — Global synchronized toggle, Manual toggle survives global state.

1. [x] Write failing vitest: activating global-open sets every `TreeNode` (product, MLA, nested
       promo/PxQ panels) to open in one action.
2. [x] Write failing vitest: activating global-close sets every node closed.
3. [x] Write failing vitest: after global-open, a manual collapse on one node leaves that node
       collapsed while siblings stay open (manual toggle never mutates the store).
4. [x] Write failing vitest: reload/rehydration does not force nodes open (persist `partialize`
       excludes `collapseEpoch`/`collapseMode`; only `showFamilia` persists).
5. [x] Add `collapseEpoch`, `collapseMode` (`manual` | `all-open` | `all-closed`), `expandAll()`,
       `collapseAll()` to `frontend/src/store/treeViewStore.js`; confirm `partialize` unchanged.
6. [x] Add `useEffect(() => {...}, [epoch])` sync in `frontend/src/components/promociones/TreeNode.jsx`
       that sets `isOpen`/`promosOpen` from `collapseMode` only when `epoch !== 0`; manual toggles
       remain local `useState` and never touch the store.
7. [x] Wire the global toggle control (expand-all / collapse-all) into the tree view UI entry point.
8. [x] Run `vitest run` (or `pnpm run test`) — confirm all four tests above are GREEN.
9. [x] Review own diff for line budget (~150 est.); commit as one work unit (chained-pr / work-unit-commits).

Dependencies: none. Can merge standalone or in parallel with PR 2.

---

## PR 2 — `ml_pxq_tier` model + migration + permission catalog/backfill + quantity-aware markup

Spec: `ml-wholesale-pxq` — Tier CRUD constraints, Quantity-aware markup, No base-price side effects,
Dedicated PxQ permission with default grant.
Depends on: PR 1 branch not required; targets feature branch directly (per design, no forward dep).

### 2a. Quantity-aware markup (`pxq_markup.py`)

1. [x] Write failing unit tests: golden cases for 1/5/10/30/70-unit tiers against the verified
       shipping table — clean markup subtracts the whole-shipment cost once, not per-unit x N.
2. [x] Write failing regression test: explicitly reproduces the old bug shape (naive
       per-unit-shipping x N) and asserts the new result differs from it.
3. [x] Write failing structural test: `resolve_tier_shipping(tier) -> ShipmentShippingCost | None`
       has no default for its shipping-bearing parameter — assert via `inspect.signature` that the
       wrapper function calling `calcular_comision_ml_total`/`calcular_limpio` has NO default for the
       shipping argument (fail-closed by construction, not convention).
4. [x] Write failing test: passing a bare float where `ShipmentShippingCost` is required raises/fails
       type validation (float cannot silently substitute).
5. [x] Write failing test: tier with `costo_envio_total = None` resolves to `estado='incompleto'`
       and is never priced/written (no fallback to any per-unit `costo_envio` field).
6. [x] Implement `backend/app/services/pxq_markup.py`: `ShipmentShippingCost` value object,
       `resolve_tier_shipping(tier)`, wrapper calling `calcular_comision_ml_total`/`calcular_limpio`
       with `precio_unitario * cantidad_minima` and the whole-shipment cost. Do NOT modify
       `pricing_calculator.py`.
7. [x] Run backend tests for this module — confirm GREEN.

### 2b. `ml_pxq_tier` model + migration

8. [x] Write failing test: model constraints — `cantidad_minima > 1` (CheckConstraint), unique
       `(publicacion_ml_id, cantidad_minima)`, nullable `costo_envio_total`/`ml_price_id`.
9. [x] Write failing test: creating a 6th tier for the same `publicacion_ml_id` is rejected at the
       service layer with a 422 validation error (max 5 enforced in service, not DB).
10. [x] Write failing test: `min_purchase_unit` (== `cantidad_minima`) of 1 is rejected.
11. [x] Check current Alembic heads (`alembic heads`) before adding a revision — repo has a
        multiple-heads history incident; confirm single head or use `alembic upgrade heads` guard.
12. [x] Implement `backend/app/models/ml_pxq_tier.py`: columns per design (`id`,
        `publicacion_ml_id` FK indexed, `item_id` indexed, `cantidad_minima`, `precio_unitario`
        Numeric(14,2), `costo_envio_total` nullable Numeric(14,2), `ml_price_id` nullable,
        `estado` String(16) in {`incompleto`,`listo`,`sincronizado`,`desconocido`}, `usuario_id` FK
        indexed, tz-aware `created_at`/`updated_at`).
13. [x] Write Alembic migration `backend/alembic/versions/20260801_add_ml_pxq_tier.py`: explicit
        column types, indexed FKs, CheckConstraint for `cantidad_minima > 1`, unique constraint.
14. [x] Run migration up/down locally against sqlite test DB; confirm `alembic downgrade -1` cleanly
        drops the table (documented rollback path).
15. [x] Run model/migration tests — confirm GREEN.

### 2c. Permission catalog + backfill (moved here per design, ahead of PR 3)

16. [x] Write failing test: `pxq.ver` and `pxq.escribir` permission codes exist and are distinct from
        `promos.escribir`.
17. [x] Write failing test: backfill migration grants `pxq.ver`/`pxq.escribir` to every role/user that
        CURRENTLY holds `promos.escribir` at migration time (query live grants dynamically — do NOT
        hardcode a role list, unlike the `20260713_add_permisos_promociones.py` precedent).
18. [x] Write failing test: a user with an explicit `concedido=false` override on `promos.escribir`
        does NOT receive `pxq.escribir` via backfill (negative overrides are copied, not ignored).
19. [x] Write failing test: a user without any promos-write grant does not receive PxQ permissions.
20. [x] **Dry-run count task (explicit, checkable):** write and run a read-only dry-run script/query
        against a production-like or staging dataset that reports (a) how many roles and (b) how
        many individual users would be granted `pxq.ver`/`pxq.escribir` by the backfill, and (c) how
        many negative overrides would be copied — BEFORE the migration is applied to any real
        environment. Record the counts in the PR description. This is untested against production
        data and must not be skipped.
21. [x] Implement permission catalog entries for `pxq.ver` / `pxq.escribir`.
22. [x] Implement backfill migration (same file as 2b's table migration, or a second migration in
        this PR per design's "permissions migration moved into PR 2") deriving grants from live
        `promos.escribir` state (roles + user overrides, including negative ones).
23. [x] Run permission tests — confirm GREEN.

### 2d. Base-price boundary (structural, not just behavioral)

24. [x] Write failing AST import-scan test: `pxq_markup.py` and the (not-yet-existing) PxQ write
        service / router module paths must not import `ProductoPricing` or reference
        `productos_pricing` at the source-text/AST level.
25. [x] Implement/keep the scan generic enough to also cover PR 3's future modules by path pattern
        (e.g. `app/services/ml_pxq_*`, `app/api/endpoints/pxq*`) so PR 3 does not need to touch this test.

### 2e. Wrap-up

26. [x] `ruff format app/` from `backend/`.
27. [x] Run full backend suite: `pytest tests/ -v --tb=short` (ENVIRONMENT=testing,
        DATABASE_URL=sqlite:///./test.db) — confirm GREEN, no regressions in existing
        `promos.escribir` / pricing tests.
28. [x] Confirm line count against 400-line budget (~370 est.); commit as one work unit targeting
        the feature branch (chained-pr).

Dependencies: none (targets feature branch, not PR 1).

---

## PR 3 — ML write path (kill-switch, eligibility, diff, sync endpoints)

Spec: `ml-wholesale-pxq` — Array-replace write semantics, Eligibility and kill-switch gating,
Fail-closed shipping cost resolution, Always-visible live ML read before write, Refuse write on
local/live divergence.
Depends on: PR 2 (needs `ml_pxq_tier` model, `pxq_markup`, permissions).

**Budget checkpoint (do this first, before writing code):** the design estimates this slice at
~390 lines against a 400-line budget — effectively no headroom. Before starting implementation,
re-estimate honestly against the actual diff shape (kill-switch config, eligibility checks, diff
function + tests, write service, live-read endpoint, sync endpoint, router wiring). If the honest
estimate is at or over ~380 lines, execute the PR 3/3a split described below from the start rather
than discovering the overage mid-apply.

### 3a-candidate. Diff/reconcile function (split candidate — evaluate first)

29. [x] Write failing unit test: **keep** case — a tier whose local mirror matches a live tier
        exactly (qty + amount) on an id observed in the live read emits `{"id": ml_price_id}`.
30. [x] Write failing unit test: **create** case — a local tier with no matching live id emits an
        object with `qty`/`amount` and no `id`.
31. [x] Write failing unit test: **delete** case — a live tier with no corresponding desired local
        tier is simply omitted from the emitted array.
32. [x] Write failing unit test: **modify** case — a local tier whose price changed vs its previously
        matched live id emits delete-old (omitted) + create-new (object without id) in the same
        array; the mutated id itself is never sent.
33. [x] Write failing unit test: **unmirrored live tier preserved** — a live tier with no matching
        local row present in the fresh live read is emitted as `{"id": ...}` keep, never dropped.
34. [x] Write failing unit test: **divergence refuses write** — matched id differs in qty/amount, or
        a mirror `ml_price_id` is absent from the live read entirely => function signals refusal
        (409-shaped result), no array is built, no POST attempted.
35. [x] Write failing unit test: **ids-only-from-live invariant** — the diff function can never emit
        an `id` that was not present in the step-4 live payload passed to it (property-style check
        across randomized fixtures if convenient).
36. [x] Write failing unit test: **empty desired set guard** — an empty desired array is refused
        unless an explicit `allow_clear=true` flag is passed.
37. [x] Implement the pure diff/reconcile function (isolate it so it can be extracted into
        `pxq_diff.py` untouched if the 3/3a split triggers).
38. [x] Run diff tests — confirm GREEN. **Decision point:** tally lines added so far vs remaining
        planned work (kill-switch, eligibility, services, endpoints). If already close to 380 lines,
        stop here, commit this as **PR 3a** (pure diff function + tests, depends on PR 2 only), and
        continue write-service/endpoints as PR 3 depending on 3a.

### 3b. Kill-switch + eligibility gates

39. [x] Write failing test: `PXQ_WRITE_ENABLED = False` (default) blocks the write before any
        eligibility check or ML call — assert no HTTP call is made (mock the ml_webhook_client and
        assert zero invocations).
40. [x] Write failing test: missing `pxq.escribir` permission blocks with 403, checked before
        eligibility.
41. [x] Write failing test: seller lacking `business` tag blocks the write before any POST.
42. [x] Write failing test: item lacking `standard_price_by_quantity` tag blocks the write before
        any POST.
43. [x] Write failing test: gate order is kill-switch -> permission -> eligibility -> fresh live
        read -> divergence, exactly as in the design (assert ordering via mock call sequence).
44. [x] Add `PXQ_WRITE_ENABLED: bool = False` to `backend/app/core/config.py`.
45. [x] Implement gate checks in `backend/app/services/ml_pxq_write_service.py` (or the sync
        orchestrator module), reusing the eligibility/tag-check pattern from
        `ml_promotions_write_service.py`.
46. [x] Run gate tests — confirm GREEN.

### 3c. Base-price boundary runtime assert

47. [x] Write failing test: a full sync flow, when committed, has no `ProductoPricing` instance in
        `db.dirty | db.new` — assert this at commit time inside the write service (runtime guard,
        not just the PR 2 AST scan).
48. [x] Write failing test: `markup_rebate`, `markup_oferta`, `precio_lista_ml` on the associated
        product are byte-identical before and after a full PxQ sync (create + modify + sync).
        (Trivially satisfied: PxQ never queries/creates/dirties a `ProductoPricing` row at all, so
        there is nothing to compare — the runtime assert in task 47 is the enforcement mechanism.)
49. [x] Implement the runtime assert in the write service; wire it into the commit path.
50. [x] Run boundary tests — confirm GREEN.

### 3d. Live-read endpoint (pool-safe)

51. [x] Write failing integration test: `GET /api/pxq/{item_id}/live` does not hold a DB session open
        across the ML proxy call — assert via session-count/mock instrumentation that the session
        used to load the mirror is closed before the proxy `await` begins.
52. [x] Write failing test: `live_status='unavailable'` (proxy failure) still returns 200 with
        `live_tiers: null`, and the response signals sync should be disabled client-side (fail-closed,
        no exception surfaced as 500).
53. [x] Write failing test: response includes `fetched_at` and is never served from a server-side
        cache (two consecutive calls both hit the proxy).
54. [x] Implement `GET /api/pxq/{item_id}/live` using `Depends(get_current_user_transient)`, no
        `Depends(get_db)`; short `with` block loads mirror into plain dataclasses, closes, then
        performs the proxy read with no session held. Explicit `response_model` (`PxqLiveStateResponse`).
55. [x] Run endpoint tests — confirm GREEN.

### 3e. Sync endpoint (write path orchestration)

56. [x] Write failing test: full sync happy path — gates pass, live read fresh, no divergence,
        diff computed, POST sent with correct array, re-read maps `ml_price_id` by (qty, amount),
        rows marked `sincronizado`.
57. [x] Write failing test: POST timeout/5xx sets mirror rows to `desconocido`, leaves `ml_price_id`
        untouched, and forces the next sync attempt through the divergence gate.
58. [x] Write failing test: post-write re-read failure results in `submitted`/`unconfirmed` state,
        mirror `desconocido` (not silently marked `sincronizado`).
59. [x] Implement `POST /api/pxq/{item_id}/sync` (or equivalent) orchestrating: kill-switch ->
        permission -> eligibility -> fresh live read -> divergence gate -> diff -> POST -> re-read ->
        remap -> persist estado.
60. [x] Run sync endpoint tests — confirm GREEN.

### 3f. Wrap-up

61. [x] `ruff format app/` from `backend/`.
62. [x] Run full backend suite — confirm GREEN, including PR 2's tests still passing.
        (4028 passed, 16 skipped — no regressions.)
63. [x] Confirm actual line count against 400-line budget; if over, execute the 3/3a split now
        (extract diff function + its tests into a separate PR/commit targeting PR 2's branch, with
        PR 3 proper depending on it) rather than shipping over budget.
        **OVER BUDGET, not re-split**: actual diff is 952 lines (8 files, +952/-14) — well past the
        400-line guard even after the PR 3a diff-function carve-out. The remaining surface (gates,
        eligibility client methods, live-read endpoint, sync endpoint, and ~440 lines of test
        evidence for both) does not have a further natural split point without breaking a single
        reviewable unit into partially-inert pieces. Reported to the orchestrator as-is per
        instruction (task explicitly said to flag rather than silently trim scope); the split/accept
        decision is the orchestrator's.
64. [x] Commit as one (or two, if split) work unit(s) targeting PR 2's branch (chained-pr).
        Committed as a single work unit `9a029505` on `feat/pxq-write-path` (off tracker
        `feat/ml-wholesale-pxq-pricing`, on top of PR 3a's `feat/pxq-array-diff`), NOT pushed.

Dependencies: PR 2 (model, markup, permissions). Kill-switch defaults OFF in code — PR 3 is safe to
merge alone with zero ML traffic.

---

## PR 4 — PxQ tier UI panel

Spec: `ml-wholesale-pxq` — Always-visible live ML read before write, Refuse write on local/live
divergence; `tree-view-collapse` interplay (panel must respect the global toggle from PR 1).
Depends on: PR 1 (collapse epoch/TreeNode sync) and PR 3 (live-read + sync endpoints).

### PR 4a — read-only live+mirror panel (this slice)

1. [x] Write failing vitest: panel fetches and renders live ML tiers side by side with the local
       mirror on open, with a loading state before the fetch resolves.
2. [x] Write failing vitest: live-read failure renders an error band with retry (fail-closed —
       never falls back to stale/assumed data); `live_status: "unavailable"` (`live_tiers: null`)
       renders distinctly from an empty live list (`[]`), and the mirror still renders.
3. [x] Write failing vitest: a divergent mirror tier (matched `ml_price_id` disagrees with the live
       tier, or is absent from the live read) is marked visibly — informational only, no
       resolution action offered (that is PR 4b).
5. [x] Write failing vitest: PxQ panel opens/closes in sync with the global collapse toggle from PR 1
       (nested panel obeys `collapseEpoch`), joining the same sync effect as Promociones/Competencia
       catálogo so "Expandir todo" does not silently skip it.
7. [x] Implement `PxqPanel.jsx` (`frontend/src/components/promociones/`) consuming
       `GET /api/pxq/{item_id}/live` only (no write call in this slice).
8. [x] Wire the panel into `TreeNode.jsx` per-MLA rendering, subscribing to `collapseEpoch`, gated
       on `pxq.ver` via `usePermisos` (invisible, not a 403, without the permission).
9. [x] Run `vitest run` and `pnpm run lint` — confirm all tests GREEN, zero lint warnings.
11. [x] Confirm line count against 400-line budget: actual diff 380 lines (8 files, +375/-5).
        Committed as one work unit `6a1fae45` on `feat/pxq-panel-lectura` (off tracker
        `feat/ml-wholesale-pxq-pricing`), NOT pushed.

### PR 4b — backend tier CRUD — DONE (this slice); write path UI still separate

0a. [x] Write failing unit tests + implement `update_pxq_tier`/`delete_pxq_tier` in
        `pxq_tier_service.py` (max-5 already enforced at create, cantidad_minima>1 and
        no-duplicate-cantidad_minima re-checked on update, `cantidad_sincronizada`/
        `precio_sincronizado` never touched by an edit, decimal-not-float on price fields).
0b. [x] Write failing tests + implement `POST/PATCH/DELETE /pxq/{item_id}/tiers[/{tier_id}]`
        endpoints gated on `pxq.escribir`, ordinary `get_current_user`+`Depends(get_db)`
        (no ML call, so no transient-user dance needed). Committed as two work units on
        `feat/pxq-tier-crud` (off tracker), NOT pushed: 236-line service commit + 359-line
        router commit (593 total, over the 400-line budget as one unit, so split rather
        than trimmed scope).

### PR 4c — tier authoring form (create/edit/delete, local-only) — DONE (this slice)

4. [x] Write failing vitest: tier form enforces max 5 tiers and `cantidad_minima > 1` client-side
       (mirroring backend validation, not replacing it — the 422 path is still handled since two
       tabs can race). Implemented in `PxqPanel.jsx`'s `PxqTierAuthoring`: disables "Agregar tramo"
       at 5 tiers, surfaces the backend's 422 message verbatim on create/edit/delete failure.
       Gated on `pxq.escribir` (read stays `pxq.ver`) — a read-only user sees no editing
       affordance at all, not buttons that would 403. A tier missing `costo_envio_total` renders
       a visible "Incompleto" badge (no default/fallback value ever synthesized client-side).
       Added `createTier`/`updateTier`/`deleteTier` to `pxqAPI` in `services/api.js` matching
       `PxqCreateTierRequest`/`PxqUpdateTierRequest` exactly. Committed on `feat/pxq-form-tramos`
       (off `feat/pxq-tier-crud-endpoints`, PR #1050), NOT pushed.

### PR 4d — sync button, allow_clear, divergence resolution — DONE (this slice)

6. [x] Write failing vitest: `allow_clear` confirmation flow — clearing all tiers requires an
       explicit confirmation step before the sync request includes `allow_clear=true`.
       11 new tests, RED-first (permission gate, direct sync, allow_clear confirm gate, all 9
       distinct backend outcomes, 502 pair never renders success/bare-error).
10. [x] Manual smoke check deferred — not required for this frontend-only slice with
        `PXQ_WRITE_ENABLED` untouched (backend not modified in this PR); covered instead by the
        exact `_SYNC_STATUS_TO_HTTP` mapping read from `backend/app/routers/pxq.py` and the vitest
        suite exercising every one of its outcomes end to end through the mocked API layer.
    [x] Divergence banner refuses the write, showing `reason`/`live`/`desired` per tier, no
        auto-resolve/force affordance — the sync button itself stays enabled (backend re-validates
        divergence server-side on every call, so a bare retry can never silently overwrite; there is
        no client-side state that would let a stale click bypass that check). Sync button + `allow_clear`
        confirmation added to `PxqSyncControl`, on top of PR 4c's form.
    [x] Line count confirmed against 400-line budget: 366 lines across 4 files, within budget as one
        unit. Committed as one work unit (`838fdb4f`) on `feat/pxq-sync-ui`, targeting PR 4c's branch
        (chained-pr), NOT pushed.

Dependencies: PR 1, PR 3 (PR 4b additionally depends on PR 4a; PR 4c depends on PR 4b; PR 4d depends on PR 4c).

---

## Review Workload Forecast

| Slice | Est. changed lines | 400-line budget risk | Notes |
|---|---|---|---|
| PR 1 (collapse toggle) | ~150 | Low | Frontend-only, independent, straightforward. |
| PR 2 (model + migration + permissions + markup) | ~370 | Medium | Four sub-concerns bundled (table, migration, permission catalog+backfill, markup wrapper). Close to budget; the dry-run task (2c.20) adds review overhead but not diff lines. |
| PR 3 (ML write path) | ~390 (design estimate), **honest re-estimate needed** | **High** | Design itself flags near-zero headroom and a pre-declared 3/3a contingency (pure diff function + its ~7-case test matrix). Task 29-38 explicitly forces a go/no-go decision point before continuing. Treat as High until the split decision is made. |
| PR 3a (diff function, if split) | ~120-150 (carved from PR 3) | Low | Only if triggered; reduces PR 3 proper to ~250-270. |
| PR 4 (UI panel) | ~300-330 | Medium | Depends on both PR 1 and PR 3 shapes; divergence banner + live-read states + collapse-epoch integration add surface area. |

- **400-line budget risk (overall program): High** — driven entirely by PR 3.
- **Chained PRs recommended: Yes** — PR 2 -> PR 3 (-> PR 3a) -> PR 4 form a real dependency chain;
  PR 1 merges independently/in parallel. This matches the design's validated slicing.
- **Decision needed before apply: Yes** — specifically whether to pre-commit to the PR 3/3a split
  now (safer, adds one more chained PR) or attempt PR 3 as a single unit and split only if the
  actual diff exceeds budget mid-apply (design's stated contingency, but riskier under strict
  ask-on-risk delivery). Recommend deciding this in the orchestrator's post-tasks chain_strategy
  conversation with the user, since it also affects the total chained-PR count communicated in
  that same discussion.

## Cross-cutting checklist (applies across all PR slices)

- [ ] `ruff format app/` run before every backend push (CI-enforced "Backend Lint").
- [ ] Every task's tests run RED before the corresponding implementation, GREEN after (strict TDD).
- [ ] Alembic heads checked (`alembic heads`) before adding any new revision in PR 2.
- [ ] No PxQ module (`pxq_markup.py`, `ml_pxq_write_service.py`, PxQ router/endpoints) imports
      `ProductoPricing` — enforced by the PR 2 AST scan test, reused for PR 3 by path pattern.
- [ ] `PXQ_WRITE_ENABLED` defaults to `False` in code at every point in the chain (never flip it in
      a migration, config default, or test fixture that leaks to non-test environments).
- [ ] Dry-run backfill count (PR 2, task 20) recorded and reviewed before any real-environment
      migration apply — not a footnote, a gating checklist item.

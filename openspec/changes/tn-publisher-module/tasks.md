# Tasks: Tienda Nube Publisher Module

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | ~3,540 total across 8 slices (PR-0 chore + 7 code PRs) |
| Review budget (session override) | **800 lines/PR** (session `review_budget_lines`, not the skill's generic 400 default) |
| 800-line budget risk | Low per-slice (all 7 code PRs land under 800; PR-5 and PR-7 are the tightest) |
| Chained PRs recommended | Yes |
| Suggested split | PR-0 (chore) → PR-1, PR-2 (independent) → PR-3 → PR-4 → PR-5 → PR-6 → PR-7 (Feature Branch Chain) |
| Delivery strategy | auto-chain (cached at session start) |
| Chain strategy | feature-branch-chain (PR-3…PR-7); PR-1/PR-2 are stacked-to-main exceptions — independent, mergeable in either order or in parallel |

```text
Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: Low
```

Note: the guard's literal line says "400-line budget risk" for tooling compatibility; the operative
budget for this session is **800 lines**, per the session preflight. All verdicts below are evaluated
against 800.

### Suggested Work Units

| Unit | Goal | PR | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| 0 | Unfreeze the codegraph index before any implementation | PR-0 (chore) | N/A — operational | `codegraph sync` (or wait for lock release) | No code change; nothing to roll back |
| 1 | Wire the existing embedder to a real trigger | PR-1 | `pytest tests/services/test_tn_category_embedding_service.py tests/api -k embedding -v` | `python -m app.scripts.sync_tn_category_embeddings` against a real/staging DB | Revert trigger commit; empty table behavior is unchanged and safe |
| 2 | Fix ungated endpoint, nav gate, banlist pagination, mirror `variant_id` | PR-2 | `pytest tests/api/test_tienda_nube_reconcile.py -v` + `pnpm test -- TiendaNubeReconcile` | Manual: hit `GET /tienda-nube/productos` unauthenticated, expect 401/403/404 | Plain revert; no data touched |
| 3 | Strict report-78 extraction + unit/dimension conversion + full field passthrough | PR-3 | `pytest tests/services/test_tn_publish_core_extract.py tests/services/test_tn_reconciliation_service.py -v` | `pytest tests/api/test_tienda_nube_reconcile.py -k reporte -v` (report endpoint returns full field set) | Revert; `ReconcileRowResponse` reverts to 7-field shape |
| 4 | Measurement profiles: model, migration, CRUD, permission, suggestion, seed | PR-4 | `pytest tests/models/test_tn_measurement_profile.py tests/api/test_tn_measurement_profiles.py -v` | `alembic upgrade head && alembic downgrade -1` on a scratch DB | `alembic downgrade -1` drops 3 additive tables; nothing else reads them |
| 5 | Publish core: precedence, validation gate, assembler, 429-aware batch | PR-5 | `pytest tests/services/test_tn_publish_core_resolve.py tests/services/test_tn_publish_core_validate.py tests/services/test_tn_publish_core_assemble.py tests/services/test_tn_publish_core_batch.py -v` | `pytest tests/services/test_tn_publish_service.py -v` (backend-only, no FastAPI/React) | Plain revert restores current 7-field publish path; already-published items in TN are unaffected |
| 6 | Decompose `TnPublishModal.jsx` into hooks + subcomponents (pure refactor) | PR-6 | `pnpm test -- TnPublishModal TiendaNubeReconcile` | Manual: open the modal for one item, confirm identical rendering/behavior | Frontend-only revert; backend core stays usable by any other consumer |
| 7 | Editable controls for every new field, profile confirm flow, SEO/tags seeding | PR-7 | `pnpm test -- TnPublishModal PublishFieldRow MeasurementSection` | Manual: publish one item end-to-end with a profile confirm + edited override | Frontend-only revert; backend core and stored overrides remain intact |

**Hard dependency, encoded in the chain itself (not just documentation):** PR-5 (D3 validation gate)
**MUST NOT** be sequenced, released, or feature-flagged ahead of PR-4 (D5 measurement profiles) merging
into the shared feature branch. PR-5's feature branch parent is PR-4's branch — the chain topology
itself makes "block ships alone" structurally impossible, not just discouraged. If PR-5 is ever
retargeted to skip PR-4, treat it as a chain-integrity bug and stop.

---

## PR-0 — Chore: unfreeze codegraph index

**Goal**: Make the CodeGraph index usable for the rest of this chain.
**Scope**: Operational only, no source changes, does not count toward the review budget.
**Spec IDs**: None.

- [ ] 0.1 Run `codegraph sync` on `/mnt/kingston/sistema/dev/pricing-app-4`; if the lock is held by
      another process, wait/retry rather than forcing re-index.
- [ ] 0.2 Confirm `codegraph status` reports a fresh index before PR-1 work starts.

**Estimated lines**: 0 (no diff). **Budget verdict**: N/A. **Dependencies**: None. **Rollback**: N/A.

---

## PR-1 — Category embedding sync trigger

**Goal**: Give `sync_category_embeddings()` a real, permissioned trigger (endpoint + script).
**Scope**: `backend/app/api/endpoints/tienda_nube_reconcile.py` (new sync route), new
`backend/app/scripts/sync_tn_category_embeddings.py`.
**Spec IDs**: ECS1 (operator-triggerable endpoint), ECS2 (script-reachable trigger), ECS3 (table gets
populated).

- [x] 1.1 RED: test `POST /api/tienda-nube-reconcile/categorias/sync` returns `403` without
      `admin.gestionar_tn_publicacion` (ECS1).
- [x] 1.2 GREEN: add the endpoint, gated on `admin.gestionar_tn_publicacion` (Decision 8 — no new
      permission), calling `sync_category_embeddings()` and returning the embedded-category count.
- [x] 1.3 RED: test authorized call executes the sync and reports a non-zero/zero count accurately
      (ECS1, ECS3).
- [x] 1.4 GREEN: wire response shape.
- [x] 1.5 RED: test the script entry point exits non-zero when `sync_category_embeddings()` reports
      `skipped=True` (ECS2).
- [x] 1.6 GREEN: implement `backend/app/scripts/sync_tn_category_embeddings.py`.
- [x] 1.7 Regression: `tests/services/test_tn_category_embedding_service.py` stays green untouched
      (implementation is not modified — wiring only).

**Estimated lines**: ~200. **Budget verdict**: well under 800. **Dependencies**: PR-0.
**Rollback boundary**: revert the endpoint + script commit; `tn_category_embedding` rows already
written are additive/harmless.

---

## PR-2 — Defect cleanup

**Goal**: Close the four known defects folded into this change; no new behavior.
**Scope**: `backend/app/api/endpoints/tienda_nube.py` (`:279`), `Navbar.jsx:28`, `Sidebar.jsx:86`,
`SmartRedirect.jsx:34`, `TiendaNubeReconcile.jsx:676`, `tn_publish_service.py:357`.
**Spec IDs**: SEC1 (dead ungated endpoint), UI5 (nav gate matches route gate / D9). Banlist pagination
and mirror `variant_id` are proposal "Known Defects", not formal spec requirements.

- [x] 2.1 RED: test `GET /tienda-nube/productos` is gone (404) or requires auth (401/403) (SEC1).
- [x] 2.2 GREEN: remove the route, or gate it with `verificar_permiso` + a typed `response_model`.
- [x] 2.3 RED: frontend test — a user with `admin.ver_items_sin_mla` but not
      `admin.gestionar_mla_banlist` sees the nav entry; a user with only
      `admin.gestionar_mla_banlist` does not (UI5, D9).
- [x] 2.4 GREEN: change the gate in `Navbar.jsx`, `Sidebar.jsx`, `SmartRedirect.jsx` to
      `admin.ver_items_sin_mla`.
- [x] 2.5 RED: test the BANLIST sub-tab paginates against banlist rows only, not the full `reporte`
      (`TiendaNubeReconcile.jsx:676`).
- [x] 2.6 GREEN: fix `currentTabItems` fallback.
- [x] 2.7 RED: test the local mirror does not fabricate `variant_id = product_id`
      (`tn_publish_service.py:357`).
- [x] 2.8 GREEN: fix the mirror write (leave null/pending until the next full sync resolves the real
      variant id, per existing mirror semantics).

**Estimated lines**: ~250. **Budget verdict**: well under 800. **Dependencies**: PR-0 (independent of
PR-1; may merge first, last, or in parallel).
**Rollback boundary**: plain revert; no data migrations.

---

## PR-3 — Strict extraction, unit/dimension conversion, full passthrough

**Goal**: Report 78's full field set reaches the reconcile response with correct units — no publish
behavior changes yet.
**Scope**: `backend/app/services/tn_publish_core/extract.py` (new), `backend/app/services/tn_publish_core/resolve.py`
(new, conversion-only for now), `backend/app/services/tn_reconciliation_service.py` (modify:
`ReconcileRowResponse` gains the full field set, replacing `:210-226`'s discard).
**Spec IDs**: PC1 (fail-loud extraction, S1), PC2 (grams→kg, U1), PC3 (dimension mapping, U2) —
foundation only; full precedence/validate/assemble lands in PR-5.

- [ ] 3.1 RED: test extraction raises naming the missing key when `height` (or any of `weight`,
      `wide`, `large`, `Marca`, `Stock_Disponible`, `coslis_price`/`iclh_price`, `Moneda_Costo`,
      `Código`, `tnr_lastPromotionalPrice`) is absent — never defaults (PC1, S1).
- [ ] 3.2 GREEN: implement `extract.py` with the `Absent` sentinel (distinct from `None`/`0`) and the
      raise-on-missing-key behavior.
- [ ] 3.3 RED: test a complete row extracts cleanly with nothing defaulted (PC1).
- [ ] 3.4 RED: **golden test** — `weight = 1000` → `1.000` kg, `weight = 250` → `0.250` kg (PC2, U1).
- [ ] 3.5 GREEN: implement the ÷1000 conversion in `resolve.py`'s GBP layer, applied before any
      precedence merge (ordering constraint from design Decision 1).
- [ ] 3.6 RED: **named test** — e.g.
      `test_dimension_mapping_large_to_width_wide_to_depth_verified_36_of_36_live_products` — asserting
      GBP `large=13, wide=2, height=8` → TN `width=13, depth=2, height=8` (PC3, U2). The rationale MUST
      be in the test name, not only in a comment.
- [ ] 3.7 GREEN: implement the mapping in `resolve.py`, **with an explanatory code comment at the
      mapping site** stating the mapping is confirmed correct (36/36 live), not a swap error. Comment
      and named test are two separate, independently-required acceptance criteria — neither substitutes
      for the other.
- [ ] 3.8 RED: test `ReconcileRowResponse` now includes `Marca`, `Stock_Disponible`, `cost` (raw,
      pre-currency-conversion — D6 lands in PR-5), `barcode` source, `promotional_price` source, weight
      (kg), and all three dimensions for `FALTA_PUBLICAR`/`FALTA_VINCULAR` rows.
- [ ] 3.9 GREEN: modify `tn_reconciliation_service.py` to project the full field set through
      `extract`/`resolve`'s conversion layer.
- [ ] 3.10 Regression: `tests/api/test_tienda_nube_reconcile.py` and `tests/services/test_tn_publish_service.py`
      stay green.

**Estimated lines**: ~450. **Budget verdict**: under 800. **Dependencies**: PR-0 (does not depend on
PR-1/PR-2; targets the feature branch as PR-3, first link of the Feature Branch Chain).
**Rollback boundary**: revert restores the 7-field `ReconcileRowResponse`.

---

## PR-4 — Measurement profiles

**Goal**: Profiles exist, are manageable, and are suggestible — independent of the publish gate that
will consume them.
**Scope**: `backend/app/models/tn_measurement_profile.py`, `tn_publish_override.py`,
`tn_category_profile_hint.py` (all three new — one migration creates all three tables per design),
`backend/alembic/versions/YYYYMMDD_add_tn_publisher_tables.py`, new
`backend/app/api/endpoints/tn_measurement_profiles.py`.
**Spec IDs**: MP1 (CRUD behind dedicated permission, D5/D10), MP2 (seed data), MP3 (category
suggestion), MP4 (availability precedes the publish gate).

- [ ] 4.1 RED: migration test — after `alembic upgrade head`, exactly 4 seed profiles exist
      (30×20×20, 30×40×10, 50×40×20, 45×55×25), each with all four measurement fields populated (MP2).
- [ ] 4.2 GREEN: write the migration (3 tables: `tn_measurement_profile`, `tn_publish_override`,
      `tn_category_profile_hint`) + `op.bulk_insert` seed, following the seeding pattern of
      `backend/alembic/versions/20260723_tn_publicacion_permiso.py`.
- [ ] 4.3 RED: **D10** — seed the NEW permission `admin.gestionar_tn_perfiles` in the same migration
      (or a companion migration) using the existing permission-seeding pattern; test it exists and is
      distinct from `admin.gestionar_tn_publicacion`.
- [ ] 4.4 GREEN: add the permission-seed migration step.
- [ ] 4.5 RED: test a user holding only `admin.gestionar_tn_publicacion` gets `403` on profile
      create/update/delete (MP1, D10).
- [ ] 4.6 RED: test a user holding only `admin.gestionar_tn_perfiles` gets `403` on the publish
      endpoint (MP1, D10) — separability in both directions.
- [ ] 4.7 GREEN: implement CRUD endpoints in `tn_measurement_profiles.py`, gated on
      `admin.gestionar_tn_perfiles`.
- [ ] 4.8 RED: test suggestion returns a profile id for a category with prior usage history, and an
      empty result (not an error) for a category with none (MP3).
- [ ] 4.9 GREEN: implement suggestion via `tn_category_profile_hint` lookup: exact
      `(categoria, subcategoria)` → else `(categoria, NULL)` → else none.
- [ ] 4.10 Downgrade test: `alembic downgrade -1` drops all 3 tables cleanly on sqlite.

**Estimated lines**: ~570 (was ~550; +permission migration for D10). **Budget verdict**: under 800.
**Dependencies**: PR-3 (targets PR-3's branch — Feature Branch Chain link 2).
**Rollback boundary**: `alembic downgrade -1`; tables are additive, nothing else reads them yet.

---

## PR-5 — Publish core: precedence, validation gate, assembler, batching

**Goal**: The backend publishes the full field set through one framework-agnostic pipeline; batch is
the only execution path.
**Scope**: `backend/app/services/tn_publish_core/resolve.py` (extend with precedence),
`validate.py` (new), `assemble.py` (new), `batch.py` (new), `__init__.py` (new),
`tienda_nube_product_client.py` (modify: `inventory_levels`, `TnRateLimited`),
`tienda_nube_reconcile.py` (modify: `publish_draft` on row response, typed `PublicarRequest`),
`tn_publish_service.py` (modify: consume the core).
**Spec IDs**: PC4, PC5 (precedence + override persistence, D2/D8), PC6 (validation gate, D3), PC7
(visibility exclusivity, D4), PC8 (cost conversion, D6), PC9 (inventory_levels, D1), PC10 (batching +
429, R1), PC11 (UI-independence, D7). MP4 (gate ships together with profiles — see hard dependency
below).

**Hard dependency (repeated here, not just in the forecast table):** this PR's branch parent MUST be
PR-4's branch. The D3 validation gate implemented here MUST NOT be exercised in production before
PR-4's profiles are live — 97 of 324 publishable items would become silently unpublishable with no
remedy. Do not decouple 4.x and 5.x work into parallel independent branches.

- [ ] 5.1 RED: test precedence — stored override outranks a fresh GBP value; in-session edit outranks
      the stored override; profile fills a gap GBP/override leave empty; full ladder `empty < profile <
      GBP < stored override < in-session edit` (PC4, D2/D8).
- [ ] 5.2 GREEN: implement precedence merge in `resolve.py`, returning `Resolved(value, source)`.
- [ ] 5.3 RED: test convert-then-resolve — a stored override (already in kg/cm/ARS) is NOT re-divided
      by 1000 on re-publish (design Decision 1 ordering constraint).
- [ ] 5.4 RED: test a successful publish writes every operator-edited field into
      `tn_publish_override`, keyed by `(ean, campo)`, and touches no GBP/ERP write path (PC5, D8).
- [ ] 5.5 GREEN: implement post-publish override upsert.
- [ ] 5.6 RED: test publish is blocked, naming the missing measurement(s), when weight or any
      dimension resolves to empty with no override/GBP/profile value (PC6, D3).
- [ ] 5.7 RED: test the same item unblocks once a profile supplies all four measurement fields (PC6,
      MP4 — proves the gate and the profile fallback ship as one working unit).
- [ ] 5.8 GREEN: implement `validate.py`'s measurement gate.
- [ ] 5.9 RED: test the assembled payload has `visibility` and never `published` (PC7, D4).
- [ ] 5.10 RED: `Moneda_Costo = ARS` passes through unconverted; `= USD` converts at today's
      `TipoCambio.venta` with fallback-to-latest; an empty `TipoCambio` table blocks the cost field
      rather than sending an unconverted USD figure as ARS (PC8, D6).
- [ ] 5.11 GREEN: implement cost resolution reusing the existing `TipoCambio` fallback pattern.
- [ ] 5.12 RED: test the variant payload has `inventory_levels: [{"stock": N}]` and no top-level
      `stock` key (PC9, D1).
- [ ] 5.13 GREEN: implement `assemble.py`.
- [ ] 5.14 RED: test a single-item publish runs through the same `execute_batch` path as a multi-item
      call — no second code path exists (PC10, R1, design Decision 6).
- [ ] 5.15 RED: **distinctness test** — a `429` with `Retry-After: 2` waits ≥2s and continues the
      batch, and this path is asserted as categorically distinct from the existing no-blind-retry rule
      for ambiguous 5xx/timeout on `publish_product` (PC10, R1). This is a required test per the
      proposal's risk table, not optional coverage.
- [ ] 5.16 GREEN: implement `TnRateLimited` in the client + `execute_batch`'s adaptive-delay backoff
      loop in `batch.py`.
- [ ] 5.17 RED: backend-only integration test — build a GBP row, overrides, and a profile directly in
      Python; call extract→resolve→validate→assemble with no FastAPI request and no React code; assert
      a complete valid TN payload (PC11, D7).
- [ ] 5.18 GREEN: wire `tn_publish_service.py` to call the core; replace `PublicarRequest.product_data:
      Dict[str, Any]` with the typed model from design's Interfaces/Contracts section.
- [ ] 5.19 GREEN: extend `tienda_nube_reconcile.py`'s row response with `publish_draft` for
      `FALTA_PUBLICAR`/`FALTA_VINCULAR` rows, backed by the TTL-cached report (design Decision 2/3).
- [ ] 5.20 Regression: `tests/services/test_tn_publish_service.py`,
      `tests/api/test_tienda_nube_reconcile.py`, `tests/services/test_tn_category_embedding_service.py`
      stay green.

**Estimated lines**: ~620 (was ~600; +2 tests for the D3/D5 co-shipping proof and the 429-vs-5xx
distinctness test). **Budget verdict**: under 800, but the tightest slice in the chain — if it grows,
split `batch.py` (R1) into its own follow-up PR before adding scope. **Dependencies**: PR-4 (branch
parent; see hard dependency above).
**Rollback boundary**: plain revert restores the current 7-field publish path; already-published items
keep their (correct, per U2) mapping and are not touched.

---

## PR-6 — Frontend decomposition (pure refactor)

**Goal**: `TnPublishModal.jsx` (809 lines, 17 `useState`, 4 inline API calls, 0 custom hooks) becomes
11 files under the ~200-line ceiling, with **zero behavior change**.
**Scope**: new `frontend/src/components/tn-publisher/**` (shell + 4 hooks + 7 presentational
components, per design's file table), delete `frontend/src/components/TnPublishModal.jsx`.
**Spec IDs**: None new — this PR satisfies no new UI requirement; it is the structural precondition
for PR-7's UI1–UI4.

- [ ] 6.1 Baseline: run `TnPublishModal.test.jsx` (473 l) and `TiendaNubeReconcile.test.jsx` (1614 l)
      green before any file move, capture the pass count.
- [ ] 6.2 Extract `hooks/usePublishFields.js` (one reducer replacing the 17 `useState`, returns
      dirty-only edits) — no behavior change.
- [ ] 6.3 Extract `hooks/useCategoryPicker.js`, `hooks/usePublishSubmit.js`, `hooks/useMarkupOffset.js`
      (existing offset fetch, moved verbatim).
- [ ] 6.4 Extract `PublishFieldRow.jsx`, `ProductFieldsSection.jsx`, `VariantFieldsSection.jsx`,
      `MeasurementSection.jsx`, `CategorySection.jsx`, `DescriptionEditor.jsx` (TipTap, moved
      verbatim — non-goal to touch), `ImageGallery.jsx`.
- [ ] 6.5 Reassemble `tn-publisher/TnPublishModal.jsx` (shell, ~120 l) from the extracted pieces.
- [ ] 6.6 Update the import in `TiendaNubeReconcile.jsx` to the new path; retain the load-bearing
      `key={publishingRow.ean}` remount at `:1229` with its explanatory comment (same treatment as
      U2 — do not let it be "optimized" away).
- [ ] 6.7 **Acceptance gate**: `TnPublishModal.test.jsx` and `TiendaNubeReconcile.test.jsx` change by
      import path only. If any assertion needs editing, STOP — the refactor changed behavior, not just
      structure — and report before continuing. This is a hard acceptance criterion, not a
      nice-to-have.
- [ ] 6.8 Delete the old `TnPublishModal.jsx`.

**Estimated lines**: ~700. **Budget verdict**: under 800; this is a move/split-heavy PR so raw diff
size is dominated by file relocation, not new logic — call this out explicitly in the PR description
so reviewers scan by file, not by line count. **Dependencies**: PR-5 (branch parent — Feature Branch
Chain link 4; functionally independent of PR-5's new endpoints, since this PR adds no new fields, but
follows the locked chain order).
**Rollback boundary**: frontend-only revert; the backend core (PR-3–5) remains usable by any other
consumer.

---

## PR-7 — Editable controls, profile confirm flow, SEO/tags, blocked-publish UX

**Goal**: The publisher is operator-complete: every transmitted field has a control, the D11 profile
confirm flow is explicit, D12 SEO/tags are seeded, and blocked publication names what is missing.
**Scope**: fields added to `ProductFieldsSection.jsx`, `VariantFieldsSection.jsx`,
`MeasurementSection.jsx`, `CategorySection.jsx`; new SEO/tags seeding logic (frontend-only, per the
prompt's routing of D12 to this PR).
**Spec IDs**: UI1 (every field has a control, D2), UI2 (stored overrides pre-fill, D8), UI3 (profile
selector + suggestion, D5/D11), UI4 (blocked-publication state, D3).

- [ ] 7.1 RED: **D2 audit test** — for the full field set (product: `name`, `description`,
      `categories`, `images`, `brand`, `visibility`, `free_shipping`, `seo_title`, `seo_description`,
      `tags`; variant: `price`, `promotional_price`, `sku`, `barcode`, `cost`, `weight`, `width`,
      `height`, `depth`, `inventory_levels[].stock`), assert every key in `draft.fields` renders a
      control (UI1). This should be a loop over `Object.keys`, not 20 hand-written assertions.
- [ ] 7.2 GREEN: add the missing controls (brand, barcode, cost, weight, width, height, depth, stock,
      promotional_price, seo_title, seo_description, tags, free_shipping) to the section components.
- [ ] 7.3 RED: test `seo_title` and `seo_description` block further input / show a validation error
      past 70/320 chars (UI1).
- [ ] 7.4 GREEN: enforce the length limits in the controls.
- [ ] 7.5 RED: test reopening an item with a stored `weight` override shows the stored value, editable
      (UI2, D8).
- [ ] 7.6 **D11**: RED — test the profile selector shows the suggested profile preselected, but
      `weight`/`width`/`height`/`depth` remain at their prior source (empty, GBP, or override) until
      the operator clicks an explicit "Apply profile" confirm action.
- [ ] 7.7 GREEN: implement the confirm action; only on confirm do the four measurement fields adopt
      the profile's values (still editable after).
- [ ] 7.8 RED: test the operator can still pick a different profile or clear the selection at any time
      (UI3).
- [ ] 7.9 **D12**: RED — test `seo_title` seeds from the resolved `name` truncated to 70 chars,
      `seo_description` seeds from the HTML-stripped description truncated to 320 chars, `tags` seeds
      as `[Marca, Categoría]`, all three with `source = "empty"` (seeded, not GBP-sourced) and fully
      editable. Mark this test/PR description with a note: **`tags` derivation is an orchestrator
      assumption pending maintainer confirmation** (D12) — if the maintainer changes the rule, only
      this seeding function needs to change, nothing downstream.
- [ ] 7.10 GREEN: implement the seeding function, called once when the draft envelope loads, never
      re-applied over an operator edit.
- [ ] 7.11 RED: test the publish button is disabled and the missing measurement fields are named, with
      a path to resolve (pick a profile or type values), when the item has no resolvable weight or
      dimensions (UI4, D3).
- [ ] 7.12 GREEN: implement the blocked-publication banner in `MeasurementSection.jsx`.
- [ ] 7.13 Regression: full `TnPublishModal.test.jsx` + `TiendaNubeReconcile.test.jsx` suite green;
      new tests live under `tn-publisher/` per design's file table.

**Estimated lines**: ~740 (was ~700; +D11 confirm flow, +D12 seeding). **Budget verdict**: under 800
but the second-tightest slice — if scope grows (e.g., maintainer changes the D12 `tags` rule to
something requiring backend support), split SEO/tags seeding into a follow-up PR rather than
expanding this one. **Dependencies**: PR-6 (branch parent — final link of the Feature Branch Chain).
**Rollback boundary**: frontend-only revert; backend core and stored overrides (PR-5) remain intact
and usable by a future bulk view.

---

## Cross-Cutting Acceptance Criteria (apply across the chain, not one PR)

- [ ] U2 mapping site carries BOTH the explanatory code comment (PR-3) AND a test whose name states
      the rationale (PR-3) — two independent, non-substitutable criteria.
- [ ] S1: no consumer of report 78 added in this change may default a missing key to `0`/`None`/`""`
      (PR-3, PR-5).
- [ ] R1: the 429 backoff path (PR-5) is proven categorically distinct from the existing ambiguous-5xx
      no-blind-retry rule by a dedicated test, not by code comment alone.
- [ ] D1: no code path in this change sends `variant.stock`; `inventory_levels` is the only stock
      write path (PR-5, verified again in PR-2's mirror fix regression).
- [ ] D3+D5: the validation gate (PR-5) and the profile fallback (PR-4) are proven to ship together —
      enforced structurally by the Feature Branch Chain parent/child topology, and by test 5.7.
- [ ] Frontend suite survival: `TnPublishModal.test.jsx` and `TiendaNubeReconcile.test.jsx` change by
      import path only through PR-6; any required assertion edit is a stop-and-report event, not a
      silent fix.

## Assumptions Flagged for Maintainer Confirmation

- **D12 `tags = Marca + Categoría`** — orchestrator assumption, not independently verified like D1–D11.
  Implemented in PR-7 as a single, isolated seeding function so a maintainer correction does not
  ripple into the resolver or backend.

## Key Learnings

1. The proposal's own PR slicing plan (7 slices) already matched a Feature Branch Chain topology, so tasks planning only needed to insert a PR-0 chore and thread D10–D12 into the existing slices rather than re-slicing from scratch.
2. Encoding a hard cross-PR dependency (D3 must never ship without D5) as branch-parent topology is stronger than a documentation note — it makes the unsafe sequencing structurally unreachable, not just discouraged.
3. D11's "preselected but not applied" answer is a materially different UX from the design's original `uso_count >= 3` threshold proposal — it replaces a numeric confidence gate with an explicit operator confirm action, which is simpler to test and review.
4. Several existing alembic migrations (`20260723_tn_publicacion_permiso.py`) already establish the exact permission-seeding pattern needed for D10, avoiding any new migration idiom.

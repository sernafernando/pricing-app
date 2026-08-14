# Proposal: Tienda Nube Publisher Module

## Intent

The Tienda Nube publisher embedded in the "Items Sin MLA" page publishes 7 fields out of the ~18 the
business needs, and its logic is trapped inside an 809-line React modal. Four concrete costs today:

- **Incomplete publications.** GBP report 78 already carries `weight`, `wide`, `large`, `height`,
  `Marca`, `Stock_Disponible`, `coslis_price`, `tnr_lastPromotionalPrice` and `Código`, but
  `tienda_nube_reconcile.py:210-226` discards them. Products land in Tienda Nube with no weight, no
  dimensions, no stock, no brand, no barcode and no cost — so shipping is mispriced at checkout and
  margin reporting on the TN side is blind.
- **Category matching looks broken but is not.** `sync_category_embeddings()`
  (`tn_category_embedding_service.py:102-139`) is implemented and tested but has **zero callers** —
  no endpoint, no script, no cron. `tn_category_embedding` is empty in production, so every
  similarity search returns nothing. The embedder itself works.
- **No path to bulk.** The business needs bulk publishing next. All mapping, validation and payload
  assembly currently lives in the modal, so a bulk view would have to duplicate it.
- **~97 items are unpublishable.** Of the 324 items in the publisher working set, ~30% have all-zero
  dimensions and ~4% are placeholders. There is not even a UI field to enter them.

## Why Now

The branch `fix/tiendanube-items-sin-mla` was opened to fix the publisher. Investigation showed the
publisher is not broken in the way reported — it is *unfinished*, and the missing half is exactly the
half a bulk-publishing module would need. Building the core now costs one change; building it after a
bulk view exists costs two rewrites.

## Goals

1. Publish the full field set Tienda Nube accepts, sourced from GBP report 78.
2. Give the category embedder a real trigger so matching works in production.
3. Introduce reusable measurement profiles so items with no GBP measurements become publishable.
4. Extract a **publish core** decoupled from the UI, so a future bulk view is a new consumer, not a
   rewrite.
5. Keep the operator in control: every field sent to TN has an editable control.

## Non-Goals (explicit)

| Non-goal | Why |
|----------|-----|
| Adding a rich-text/WYSIWYG editor | **Already exists.** TipTap + StarterKit at `TnPublishModal.jsx:219-222`, toolbar `:651-724`. Styling/UX polish only, if anything. |
| Rewriting or replacing the category embedder | **It works.** `intfloat/multilingual-e5-small`, 384-dim, self-hosted TEI. `buildCategoryText` already feeds it GBP `Categoría` + `SubCategoría`. Only the source table is empty. |
| Backfilling the 535 already-published products | Their dimension mapping is **correct** (confirmed 36/36 against the live store). Nothing to fix. |
| Fixing dangling `tnr_id` links (~10% return HTTP 404) | Separate reconciliation concern; belongs with the MAL_VINCULADO verdict, not with publishing. |
| Building the bulk-publishing view itself | This change delivers the core it will consume. The view is the next change. |
| Migrating to the "new Product API" | Multi-inventory is already available on v1 via `inventory_levels`. No migration needed. |

## Locked Constraints

Recorded as requirements, with the rationale that makes them non-negotiable.

| ID | Constraint | Rationale |
|----|-----------|-----------|
| **D1** | Use TN **v1** endpoints with `inventory_levels[].stock`. Never the deprecated `variant.stock`. | Multi-inventory is already active on this store (`GET /locations` → 200, single location `01JRK320C38C1ZZH2XP96H1391` "Gauss"). Same v1 endpoints; `variant.stock` is deprecated for updates. With one location, `location_id` may be omitted. No spike, no migration, no vendor request. |
| **D2** | Precedence **GBP → Profile → Operator**. The operator's edit always wins. **Any field sent to TN MUST have an editable control in the UI.** | Maintainer's governing principle: *"la última palabra la tiene el operador"*. A field the operator cannot see and change must not be silently transmitted. |
| **D3** | **Block** publication when weight or any dimension is absent. | Wrong dimensions produce wrong shipping quotes charged to the business. ~97 items block until measurements are supplied — that is the intended forcing function for profiles, not a regression. |
| **D4** | Visibility is operator-selectable (`visible` / `unlisted` / `hidden`), default `visible`. Send **only** `visibility`, never `published`. | TN returns HTTP 422 when both are present in one request. |
| **D5** | Measurement profiles are a new entity with full CRUD behind their **own** permission, plus automatic suggestion by product category. Selecting a profile autocompletes weight/width/height/depth; the operator edits on top. | GBP dimensions cluster into de-facto box classes (30/20/20 ×64, 30/40/10 ×46, 50/40/20 ×35, 45/55/25 ×24). Those clusters seed the initial profiles. |
| **D6** | Send TN `cost`, converting USD→ARS with the BNA rate of the day from the existing `TipoCambio` table. | `Moneda_Costo` is USD for 1128/1140 rows and ARS for 12. `TipoCambio` (populated by `bna_scraper.py` / `tipo_cambio_service.py`, consumed as `float(tc.venta)`) is the project's existing rate source — no new integration. |
| **D7** | Build a **standalone publish core** decoupled from the single-item UI. The current modal becomes one consumer, not the owner. | Bulk publishing is the declared next requirement. |
| **U1** | GBP `weight` is in **grams**; TN wants **kilograms**. Divide by 1000. | Verified 36/36 against the live store. |
| **U2** | Dimension mapping: GBP `large` → TN `width`; GBP `wide` → TN `depth`; GBP `height` → TN `height`. GBP has no *profundidad* column. **This MUST carry an explanatory code comment.** | Confirmed by the maintainer and by 36/36 live samples. It reads as a bug at a glance; without a comment someone will "fix" it and break 535 correct products plus every future publication. |
| **S1** | Every new consumer of report 78 MUST **fail loudly** on a missing expected key. Never degrade to `0` / `None`. | `parse_soap_response` is schema-less. During the investigation session the ERP renamed `higth` → `height` **live**, and two runs minutes apart returned different key names. A silent degrade would publish zeroed weights and dimensions at scale. |
| **R1** | Batching and 429 handling belong in the core from day one. | TN rate-limits variant updates with a Weighted Token Bucket; cost scales with payload weight. Retrofitting this after the bulk view exists means rewriting the core. |
| **D8** | Operator overrides are **persisted locally per item** in a new overrides table, reused on subsequent visits and by the future bulk publisher. Never written back to GBP. Precedence: `stored override` > `GBP report 78 value` > `selected profile` > empty; the operator's live edit always wins. | Decided post-proposal. A stored override IS a prior operator decision, and D2 says the operator has the last word — it must outrank machine-sourced values. |
| **D9** | Align the **nav** to the **route**: `Navbar.jsx:28`, `Sidebar.jsx:86`, `SmartRedirect.jsx:34` gate on `admin.ver_items_sin_mla`, matching `App.jsx:124`, not on `admin.gestionar_mla_banlist`. | Decided post-proposal. Whoever can enter the route must see the link. |
| **D10** | Profile administration permission is `admin.gestionar_tn_perfiles`, a NEW permission, seeded the same way as `admin.gestionar_tn_publicacion` / `admin.gestionar_tn_reconcile_banlist`. It is separable from publish rights in both directions: publish without profile admin, and profile admin without publish. | Decided during tasks planning. Matches the repo's existing per-capability permission convention; keeps box-class administration out of the hands of anyone who merely holds publish rights. |
| **D11** | A category-suggested measurement profile is **preselected in the selector but NOT applied**. Weight/width/height/depth stay empty until the operator explicitly confirms the profile. | Decided during tasks planning. Keeps the "profile" precedence tier an explicit operator act, not an automatic fill — which is what keeps the D3 publication block meaningful rather than a rubber stamp. |
| **D12** | `seo_title` = product name truncated to 70 chars; `seo_description` = description with HTML stripped, truncated to 320 chars; `tags` = Marca + Categoría. All three prefilled (`source = "empty"` per design Decision 1/open-questions) and fully editable per D2. | Decided during tasks planning as a working default so PR 7 is not blocked. **`tags = Marca + Categoría` is an orchestrator assumption — flag for maintainer confirmation**, not a verified requirement like D1–D9. |

## Field Set (target state)

**Product**: `name`, `description`, `categories`, `images`, `brand`, `visibility`, `free_shipping`,
`seo_title` (≤70), `seo_description` (≤320), `tags`.

**Variant**: `price`, `promotional_price`, `sku`, `barcode`, `cost`, `weight`, `width`, `height`,
`depth`, `inventory_levels[].stock`.

Each one requires an editable control per **D2**.

## Capabilities

### New Capabilities

- `backend/tn-publish-core`: strict GBP report-78 extraction, unit/dimension mapping, GBP→Profile→
  Operator precedence resolution, publish validation gate, TN v1 payload assembly with
  `inventory_levels`, cost currency conversion, rate-limit-aware batching primitives.
- `backend/tn-measurement-profiles`: profile entity, CRUD, dedicated permission, category-based
  suggestion.
- `backend/tn-category-embedding-sync`: an operator- and script-reachable trigger for
  `sync_category_embeddings()`.
- `frontend/tn-publisher-ui`: decomposed publisher UI consuming the core; editable control for every
  transmitted field; profile selector; blocked-publication UX.

### Modified Capabilities

- `backend/security-hardening`: `GET /tienda-nube/productos` (`tienda_nube.py:279`) is currently
  ungated (no `verificar_permiso`), has no `response_model`, and has zero callers — it must be
  removed or gated.

## Approach (high level — not the design)

**Publish core (backend, D7).** A service layer that takes a GBP row plus operator overrides plus an
optional profile, and returns a validated TN payload. Three separable stages so both the single-item
modal and the future bulk view drive the same pipeline:

1. **Extract** — strict projection of report 78. Missing expected key → raise, never default (S1).
2. **Resolve** — apply precedence GBP → Profile → Operator (D2), unit conversions (U1), documented
   dimension mapping (U2), USD→ARS cost via `TipoCambio` (D6).
3. **Validate + assemble** — block on missing measurements (D3), emit v1 payload with
   `inventory_levels` and `visibility` only (D1, D4).

`tn_publish_service.py:526-529` already merges into an incoming variant precisely so a caller can
send stock/weight/dimensions — the backend shape is ready; the caller is what is missing.

**Category embeddings.** Expose the existing `sync_category_embeddings()` behind a permissioned
endpoint plus a script entry point. Implementation exists and is tested; this slice is wiring.

**Measurement profiles.** New model + Alembic migration + CRUD endpoints behind a dedicated
permission (D5). Category-based suggestion reuses the same similarity approach already proven for
categories, or a simpler category→profile mapping — the design phase decides. Initial profile seed
data comes from the observed GBP box clusters.

**Frontend.** Decompose `TnPublishModal.jsx` (809 lines, 17 `useState`, 4 inline API calls, 0 custom
hooks) against the ~200-line ceiling in `frontend/AGENTS.md`: extract data fetching into custom
hooks, split into presentational subcomponents, keep the existing TipTap editor intact. Then add the
editable controls for the new fields and the profile selector.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/services/tn_publish_core/` | New | Extract / resolve / validate / assemble stages |
| `backend/app/services/tn_publish_service.py` | Modified | Consume the core; feed the full variant |
| `backend/app/services/tn_reconciliation_service.py` | Modified | Strict report-78 projection (S1) |
| `backend/app/api/endpoints/tienda_nube_reconcile.py` | Modified | Pass full field set to the modal (`:210-226`); publish endpoint takes overrides |
| `backend/app/api/endpoints/tienda_nube.py` | Modified | Gate or remove `GET /tienda-nube/productos` (`:279`) |
| `backend/app/models/tn_measurement_profile.py` | New | Profile entity |
| `backend/alembic/versions/YYYYMMDD_add_tn_measurement_profile.py` | New | Migration + seed-friendly schema |
| `backend/app/services/tn_category_embedding_service.py` | Modified | Expose sync trigger |
| `backend/app/services/tienda_nube_product_client.py` | Modified | `inventory_levels`, 429 backoff |
| `frontend/src/components/TnPublishModal.jsx` | Modified | Decomposed; becomes a core consumer |
| `frontend/src/components/tn-publisher/` | New | Extracted subcomponents + hooks |
| `frontend/src/pages/TiendaNubeReconcile.jsx` | Modified | Fix `currentTabItems` fallback (`:676`) |
| `frontend/src/components/Navbar.jsx`, `Sidebar.jsx`, `SmartRedirect.jsx` | Modified | Align nav gate with `App.jsx:124` |

## Known Defects Folded In

| Defect | Location | Disposition |
|--------|----------|-------------|
| Ungated, response-model-less, zero-caller endpoint | `tienda_nube.py:279` | **Fix** (gate or remove) |
| Nav gates on `admin.gestionar_mla_banlist`, route requires `admin.ver_items_sin_mla` | `Navbar.jsx:28`, `Sidebar.jsx:86`, `SmartRedirect.jsx:34` vs `App.jsx:124` | **Fix** (make coherent) |
| BANLIST sub-tab paginates against the whole `reporte` | `TiendaNubeReconcile.jsx:676` | **Fix** |
| Local mirror writes `variant_id = product_id` (fabricated id shown as real) | `tn_publish_service.py:357` | **Fix** |
| 809-line god component | `TnPublishModal.jsx` | **Fix** (D7 decomposition) |
| ~10% dangling `tnr_id` (HTTP 404 on TN) | report 78 / reconciliation | **Defer** — follow-up, declared non-goal |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Someone "corrects" the U2 dimension mapping later and breaks every publication | **High** | Mandatory explanatory code comment at the mapping site + a test asserting the exact mapping with the rationale in its name |
| GBP renames a report-78 column again mid-flight | **High** | S1: fail loudly on missing key. A publish that raises is recoverable; a publish with zeroed dimensions is not |
| D3 blocking makes ~97 items unpublishable on day one | **High (by design)** | Ship profiles (D5) in the same change, seeded from observed box clusters; surface a clear "measurements required" state, not a generic error |
| TN 429 under bulk load | Med | R1: batching + backoff designed into the client now, exercised by tests before the bulk view exists |
| USD→ARS conversion silently uses a stale rate | Med | Reuse the existing `TipoCambio` fallback-to-latest pattern; surface the rate and its date in the UI so the operator sees what is being sent |
| Frontend decomposition regresses working behavior (incl. TipTap) | Med | Pure-refactor slice with the existing `TnPublishModal.test.jsx` kept green before any feature is added |
| Sending both `published` and `visibility` → HTTP 422 | Low | D4 enforced in the assembler, covered by a test |
| Profile permission over-broad and operators mass-edit box classes | Low | D5 dedicated permission, separate from `admin.gestionar_tn_publicacion` |

## PR Slicing Plan (800-line review budget, auto-chain)

Forecast: **7 slices**. Chained delivery is required; `delivery_strategy` is `auto-chain`, so slices
proceed without a per-slice decision gate.

| # | Slice | Est. lines | Targets | Autonomous value |
|---|-------|-----------|---------|------------------|
| 1 | Category embedding sync trigger: endpoint + script + permission + tests | ~200 | feature branch | Ships alone — makes category matching work in production immediately |
| 2 | Defect cleanup: gate/remove `tienda_nube.py:279`, nav permission coherence, banlist pagination, mirror `variant_id` | ~250 | feature branch | Ships alone — pure correctness/security, no new behavior |
| 3 | Strict report-78 extraction (S1) + unit/dimension mapping (U1, U2) + full passthrough to the modal | ~450 | feature branch | Data reaches the UI; nothing new is sent to TN yet |
| 4 | Measurement profiles: model, migration, CRUD, dedicated permission, category suggestion, seed | ~550 | PR 3 | Profiles manageable and suggestable, independent of publishing |
| 5 | Publish core: precedence resolver, validation gate (D3), payload assembler (D1, D4, D6), 429-aware batching (R1) | ~600 | PR 4 | Backend publishes the full field set; core is bulk-ready |
| 6 | Frontend decomposition of `TnPublishModal` into hooks + subcomponents (pure refactor, no new fields) | ~700 | PR 5 | Component under the 200-line ceiling; existing tests green |
| 7 | Frontend editable controls for every new field (D2) + profile selector + blocked-publication UX | ~700 | PR 6 | Operator-complete publisher |

PRs 1 and 2 are independent and may merge first or in parallel. PRs 3 → 4 → 5 → 6 → 7 form a
Feature Branch Chain: PR 3 targets the feature branch, each later PR targets the immediately previous
branch. Every slice must show a clean diff against its parent — rebase/retarget if earlier slices
appear in a child diff.

## Testing Strategy (strict TDD)

Tests first, then implementation, for every slice.

- **Backend** — `cd backend && ENVIRONMENT=testing DATABASE_URL=sqlite:///./test.db pytest tests/ -v --tb=short`.
  Required cases: missing report-78 key raises instead of defaulting (S1); grams→kilograms golden
  conversion (U1); the exact GBP→TN dimension mapping with the rationale in the test name (U2);
  precedence GBP → Profile → Operator with the operator always winning (D2); publish blocked when any
  measurement is absent (D3); payload never contains `published` alongside `visibility` (D4); USD and
  ARS cost rows both converted correctly (D6); `inventory_levels` used and `variant.stock` never sent
  (D1); 429 backoff path (R1); profile CRUD rejected without its permission (D5).
- **Frontend** — `cd frontend && pnpm test`. `TnPublishModal.test.jsx` and
  `TiendaNubeReconcile.test.jsx` stay green through the PR 6 refactor; PR 7 adds control-level tests
  asserting every transmitted field is editable (D2).
- **Lint (CI-gated)** — `ruff check app/`, `ruff format app/`, `pnpm run lint`, `pnpm run lint:css`.

## Rollback Plan

- **PR 1** — revert the trigger commit. `tn_category_embedding` rows are additive; leaving them
  populated is harmless, and the pre-change behavior (empty table, no matches) is restored by simply
  not calling the sync.
- **PR 2** — plain revert. No data touched.
- **PRs 3–5** — plain revert restores the current 7-field publish path. `alembic downgrade -1` drops
  `tn_measurement_profile`; the table is additive and nothing else reads it. **Products already
  published with the full field set are not rolled back** — they remain correct in TN, since the
  mapping being shipped is the same one the existing 535 products use (U2).
- **PRs 6–7** — frontend-only revert; the backend core keeps working and stays available to any other
  consumer.
- No existing pricing, product or reconciliation column is written by this change.

## Dependencies

- Self-hosted TEI embedding service reachable for PR 1 (already used by the ML questions bot).
- GBP report 78 availability (`GBP_REPORT_ID_TN_RECONCILE = 78`, 60s timeout).
- `TipoCambio` populated by the existing BNA scraper for D6.
- Tienda Nube API credentials already configured. No new third-party packages expected.

## Success Criteria

- [ ] `tn_category_embedding` is populated in production and category suggestions return matches.
- [ ] A publication carries brand, barcode, cost (ARS), stock via `inventory_levels`, promotional
      price, weight in kilograms and all three dimensions.
- [ ] The GBP→TN dimension mapping is asserted by a test and explained by a code comment at the
      mapping site.
- [ ] A missing report-78 key raises a loud error; no publish path can emit a defaulted `0`.
- [ ] An item with no measurements cannot be published, and the UI says why.
- [ ] A measurement profile is suggested by category, autocompletes the four fields, and the operator
      can still override every one of them.
- [ ] Every field transmitted to TN has an editable control in the UI (D2 audit).
- [ ] `TnPublishModal.jsx` is under the ~200-line ceiling, with API access in custom hooks.
- [ ] The publish core is callable without any React code, proven by a backend-only test that
      publishes a full payload.
- [ ] Each of the 7 PRs is individually under 800 changed lines.

## Proposal Question Round

Interactive mode calls for a product question round. The maintainer already locked D1–D7, so these
are the remaining product gaps. Each carries a working assumption so the pipeline is not blocked —
correct any of them before spec/design.

1. **DECIDED — Override persistence (D8).** The operator's in-session correction to any publish field
   (weight, dimensions, or otherwise) is persisted locally per item in a new overrides table and reused
   on subsequent visits and by the future bulk publisher. It is **not** written back to GBP — no ERP
   write path exists and none is opened here. Precedence: `stored override` > `GBP report 78 value` >
   `selected profile` > empty, with the operator's live in-session edit always winning over all four.
2. **DECIDED — Profile administration (D10).** The profile permission is a NEW permission,
   `admin.gestionar_tn_perfiles`, following the existing `admin.gestionar_tn_publicacion` /
   `admin.gestionar_tn_reconcile_banlist` seeding convention. It is *not* implied by
   `admin.gestionar_tn_publicacion` in either direction — publish and profile-admin are independent
   grants.
3. **DECIDED — Suggestion strength (D11).** The suggested profile is preselected in the selector but
   **not applied** — weight/width/height/depth stay empty until the operator explicitly confirms the
   profile. This keeps the "profile" precedence tier an explicit operator act.
4. **DECIDED — Nav permission resolution (D9).** `Navbar.jsx:28`, `Sidebar.jsx:86` and
   `SmartRedirect.jsx:34` are aligned to gate on `admin.ver_items_sin_mla`, matching the route guard at
   `App.jsx:124`, replacing the stale `admin.gestionar_mla_banlist` check. Users holding only
   `admin.gestionar_mla_banlist` lose the nav entry — whoever can enter the route must see the link.
5. **DECIDED — SEO and tags sourcing (D12).** `seo_title` is derived by truncating the product name to
   70 chars; `seo_description` is derived from the description with HTML stripped, truncated to 320
   chars; `tags` is derived as Marca + Categoría. All three are prefilled and fully editable per D2.
   **`tags = Marca + Categoría` is an orchestrator assumption, flagged for maintainer confirmation** —
   unlike D1–D9/D10/D11 it has not been independently verified.

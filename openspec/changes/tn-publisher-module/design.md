# Design: Tienda Nube Publisher Module

## Technical Approach

A backend **publish core** owns extraction, precedence resolution, validation and payload assembly; the React modal becomes a rendering client of that core. The seam is a **declarative field catalog** plus a **resolved-draft envelope** carried on the existing reconcile report response — one server-side resolver, two consumers (single-item modal today, bulk view later), zero duplicated business logic.

Implements proposal D1–D9, U1, U2, S1, R1 and the `tn-publish-core` / `tn-measurement-profiles` / `tn-category-embedding-sync` / `tn-publisher-ui` / `security-hardening` specs.

## Architecture Decisions

### Decision 1: The precedence resolver lives in the backend, expressed as a field catalog

**Choice**: `backend/app/services/tn_publish_core/` with a single module-level `FIELD_CATALOG` — one declarative row per transmitted field: `(name, gbp_key, coercion, absence_predicate, profile_fillable, required_for_publish, tn_payload_path)`. Every stage (`extract` → `resolve` → `validate` → `assemble`) iterates that catalog. The resolver returns a `Resolved(value, source)` per field, where `source ∈ {operator, override, gbp, profile, empty}`.

| Option | Tradeoff | Verdict |
|---|---|---|
| Frontend resolves, backend trusts payload | Bulk path has no React; today's `product_data: Dict[str, Any]` validates nothing | **Rejected** — is the defect |
| Shared spec, two implementations | Guaranteed drift between modal and bulk | **Rejected** |
| Backend resolves, frontend renders + sends dirty edits only | One implementation, provenance visible, D2 audit becomes a loop | **CHOSEN** |

**Rationale**: identical behaviour between the two consumers is a *structural* property, not a discipline property. 18 hand-written per-field branches would also make S1's fail-loud check 18 places to forget; as a catalog it is one loop.

**As built (PR-3/PR-5a)**: the backend-resolver choice stands, but no `catalog.py`/`FIELD_CATALOG` module was created. The field definitions live as per-stage tuples/constants (`REQUIRED_REPORT_FIELDS`/`OPTIONAL_REPORT_FIELDS` in `extract.py`, the conversion table in `resolve.py`, `MEASUREMENT_FIELDS` in `validate.py`) — each stage's fail-loud behaviour is enforced by its own tests rather than a shared declarative loop. If a future PR adds transmitted fields and the per-stage lists start drifting, extracting the originally-planned catalog is the documented follow-up.

**Absent vs zero** — the catalog's per-field `absence_predicate`, never an inline `if x == 0`:

| Field class | `"0.000000000"` / blank means | Why |
|---|---|---|
| `weight`, `width`, `height`, `depth` | **ABSENT** → falls through to the next precedence layer | A zero-dimension physical product does not exist |
| `stock` | **0**, a real value | Zero stock is a legitimate publish state |
| `promotional_price` | **ABSENT** (no promo) | A zero promo price would publish a free product |
| any missing **key** | **raise** (S1), never a sentinel | ERP renamed `higth`→`height` live mid-session |

`Absent` is a distinct sentinel object, never `None` and never `0`, so "GBP is silent" and "GBP says zero" can never collapse.

**Ordering constraint**: unit conversion (U1 ÷1000, U2 mapping, D6 USD→ARS) is applied **inside the GBP layer, before precedence**. Overrides are stored already-canonical (kg, cm, ARS). Convert-then-resolve, never resolve-then-convert — otherwise a stored override gets divided by 1000 on re-publish.

### Decision 2: Publish re-resolves server-side from a TTL-cached report, never from client data

**Choice**: a module-level TTL cache (~10 min) wrapping `tn_reconciliation_service.fetch_gbp_report_78`. The report endpoint populates it; `/publicar` reads it. `PublicarRequest.product_data: Dict[str, Any]` is replaced by a typed model carrying only operator intent (`overrides`, `profile_id`, `category_id`, `visibility`, `free_shipping`, `seo_*`, `tags`, `price`).

**Alternatives**: client echoes back the server-produced draft (tamper-able on the wire, and S1 becomes unenforceable — a client can simply omit a key); re-fetch report 78 per publish (60 s timeout on a single-item action); no cache at all in the bulk path (one fetch per item).

**Rationale**: S1 only holds if the server is the one reading GBP. A ≤10-minute-stale server-side report is strictly safer than a client-supplied one. Per-worker cache; worst case is a redundant re-fetch.

### Decision 3: Draft envelope rides the existing report response

**Choice**: extend `ReconcileRowResponse` with `publish_draft: Optional[PublishDraftResponse]`, emitted **only** for `FALTA_PUBLICAR` / `FALTA_VINCULAR` rows (~324 of 1140 — the only rows with a Publicar button). Shape: `{fields: {name: {value, source, editable, options?}}, blocked: bool, blocked_reasons: [str], suggested_profile_id: Optional[int], exchange_rate: {value, fecha} | null}`.

**Alternatives**: a separate `GET /publish-draft/{ean}` (needs its own report fetch or cache lookup, extra round-trip per modal open); keep the modal fetching `/gbp-parser` (the workaround already removed in slice 3c).

**Rationale**: the report build already holds every row in memory; resolving is pure CPU on data in hand. The bulk view gets 324 drafts for free from a call it already makes. Also fixes the `:210-226` column-dropping defect directly. Overrides / hints / exchange rate are loaded as **three bulk queries** (`WHERE ean IN (...)`), never per row.

### Decision 4: Profile suggestion by association table, not embeddings

| Option | Tradeoff | Verdict |
|---|---|---|
| Reuse pgvector embeddings | Existing embedder maps text→**TN category id**, a different problem. Would need a second embedding table; cosine over 4 profiles is unexplainable and untestable on sqlite | **Rejected** |
| Usage-count association table | Deterministic, explainable, sqlite-testable, self-populating | **CHOSEN** |
| No table — global most-used profile | Zero cost but ignores category entirely | **Rejected** |

**Choice**: `tn_category_profile_hint(categoria, subcategoria, profile_id, uso_count)`. On a successful publish where a profile was applied, upsert `+1`. Suggestion = highest `uso_count` for exact `(categoria, subcategoria)`, else `(categoria, NULL)`, else none. Cold start returns none — which is the spec's "empty result, not an error".

### Decision 5: Overrides are one row per (ean, field)

**Choice**: `tn_publish_override(ean, campo, valor TEXT, usuario_id, fecha_actualizacion)`, unique on `(ean, campo)`, keyed by **EAN** (the GBP `Código`, 100 % populated, already the join key for `get_product_by_sku`, the mirror `variant_sku`, and the banlist).

**Alternatives**: one JSON blob row per item (read-modify-write races under concurrent bulk publish, no per-field authorship); keying by `Item_ID` (breaks the EAN-keyed publish path).

`valor` is TEXT and passes through the **same catalog coercion as GBP values**, so a stored override and a GBP value can never diverge in typing. **D8 is enforced structurally**: the core has no GBP write client on its call path at all. Audit reuses the existing `_audit_publish` R2.5 pattern — the publish audit row records the full `sources` map, extending "why did this go live at this number" to every field.

### Decision 6: 429 handling splits between client and executor

**Choice**: `tienda_nube_product_client` raises a typed `TnRateLimited(retry_after)`; `tn_publish_core.batch.execute_batch` owns the backoff loop and per-item outcomes. Sequential execution with an **adaptive inter-item delay** that increases for the remainder of the batch after each 429. Honour `Retry-After`, else exponential 1/2/4/8 s capped; on exhaustion that item's outcome is `rate_limited` and the batch continues.

**Alternatives**: backoff inside the HTTP client (client would own batch-continuation policy); concurrent workers (TN's Weighted Token Bucket makes concurrency a guaranteed 429 storm); fixed sleep (wastes time when the bucket is full).

**Explicitly not a contradiction of the existing no-retry rule**: a 429 is a *rejection* — nothing was created — which is categorically different from the ambiguous 5xx/timeout that `publish_product` must never blind-retry. That distinction is a required test.

**Batch is the only execution path.** A single-item publish is `execute_batch([item])`. There is no second code path for bulk to grow into.

### Decision 7: Price stays where it is

The resolver owns `cost` (D6, USD→ARS), **not** `price`. The surcharge offset remains a frontend preset with the existing backend containment guard (`_validate_publish_price`) and R2.5 audit fields. Moving price into the resolver would rewrite the money path and invalidate ~6 existing frontend money tests for no requirement in this change. Recorded as a deliberate boundary.

### Decision 8: Embedding sync gets endpoint **and** script

`POST /api/tienda-nube-reconcile/categorias/sync` gated on the existing `admin.gestionar_tn_publicacion` (no new permission — sync is maintenance *on* the publish path, minimalism ladder rung 2), plus `backend/app/scripts/sync_tn_category_embeddings.py` exiting non-zero when `skipped=True`. Wiring only; `sync_category_embeddings` is already implemented and tested.

## Data Flow

    GBP report 78 ──(TTL cache)──┐
                                 ▼
    overrides ──►  extract ──► resolve ──► validate ──► assemble ──► batch ──► TN v1
    profile   ──►  (S1)        (U1,U2,     (D3,D6)      (D1,D4)      (R1)
    operator  ──►              D6,prec.)
                                 │
                                 ├──► draft envelope ──► ReconcileRowResponse ──► modal controls
                                 └──► sources map ─────► Auditoria (TN_PUBLICAR)

Precedence, low → high: `empty < profile < GBP < stored override < operator in-session edit`.

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/app/services/tn_publish_core/__init__.py` | Create | Public surface: `build_draft`, `resolve_batch`, `execute_batch` |
| `backend/app/services/tn_publish_core/catalog.py` | ~~Create~~ Not built | Superseded — see "As built" under Decision 1; U2 mapping + comment live in `resolve.py` |
| `backend/app/services/tn_publish_core/extract.py` | Create | Strict report-78 projection, `Absent` sentinel, S1 raise |
| `backend/app/services/tn_publish_core/resolve.py` | Create | Precedence, U1, U2, D6 conversion, `Resolved(value, source)` |
| `backend/app/services/tn_publish_core/validate.py` | Create | D3 measurement gate, D6 no-rate block |
| `backend/app/services/tn_publish_core/assemble.py` | Create | v1 payload, `inventory_levels`, `visibility`-only (D1, D4) |
| `backend/app/services/tn_publish_core/batch.py` | Create | Sequential batch, adaptive delay, 429 backoff (R1) |
| `backend/app/models/tn_measurement_profile.py` | Create | Profile entity |
| `backend/app/models/tn_publish_override.py` | Create | `(ean, campo)` override rows |
| `backend/app/models/tn_category_profile_hint.py` | Create | Usage-count suggestion table |
| `backend/alembic/versions/YYYYMMDD_add_tn_publisher_tables.py` | Create | 3 tables + 4 seed profiles (`op.bulk_insert`) |
| `backend/app/api/endpoints/tn_measurement_profiles.py` | Create | CRUD behind its own permission (D5) |
| `backend/app/scripts/sync_tn_category_embeddings.py` | Create | Cron entry point |
| `backend/app/services/tn_reconciliation_service.py` | Modify | TTL cache around `fetch_gbp_report_78` |
| `backend/app/api/endpoints/tienda_nube_reconcile.py` | Modify | `publish_draft` on row response; typed `PublicarRequest`; sync endpoint |
| `backend/app/services/tn_publish_service.py` | Modify | Consume the core; fix mirror `variant_id` (`:357`) |
| `backend/app/services/tienda_nube_product_client.py` | Modify | `inventory_levels`, `TnRateLimited` |
| `backend/app/api/endpoints/tienda_nube.py` | Modify | Remove dead ungated `GET /tienda-nube/productos` (`:279`) |
| `frontend/src/components/tn-publisher/**` | Create | Shell + 4 hooks + 7 presentational components (see below) |
| `frontend/src/components/TnPublishModal.jsx` | Delete | Replaced by `tn-publisher/TnPublishModal.jsx` |
| `frontend/src/pages/TiendaNubeReconcile.jsx` | Modify | Fix `currentTabItems` (`:676`); import path |
| `Navbar.jsx` / `Sidebar.jsx` / `SmartRedirect.jsx` | Modify | Gate on `admin.ver_items_sin_mla` (D9) |

## Interfaces / Contracts

```python
# tn_publish_core — UI-independent, no FastAPI/React object on the call path
def build_draft(db, gbp_row: dict, *, overrides: dict[str, str],
                profile: MeasurementProfile | None,
                operator_edits: dict[str, Any]) -> PublishDraft
def execute_batch(db, usuario, plan: BatchPlan, client=None) -> list[ItemOutcome]

@dataclass(frozen=True)
class Resolved:
    value: Any
    source: Literal["operator", "override", "gbp", "profile", "empty"]
```

```python
class PublicarRequest(BaseModel):        # replaces product_data: Dict[str, Any]
    ean: str
    category_id: int
    profile_id: Optional[int] = None
    overrides: Dict[str, str] = {}        # operator edits only; keys validated against FIELD_CATALOG
    visibility: Literal["visible", "unlisted", "hidden"] = "visible"
    free_shipping: bool = False
    seo_title: Optional[str] = Field(default=None, max_length=70)
    seo_description: Optional[str] = Field(default=None, max_length=320)
    tags: List[str] = []
    description_html: str
    image_srcs: List[str] = []
    price: str                            # money path unchanged (Decision 7)
    offset_percent: Optional[float] = None
    price_base_source: Optional[Literal["web_transferencia", "manual"]] = None
```

### Frontend decomposition (~200-line ceiling, `frontend/AGENTS.md`)

| File | ~Lines | Responsibility |
|---|---|---|
| `tn-publisher/TnPublishModal.jsx` | 120 | Shell, layout, confirm/submit wiring |
| `hooks/usePublishFields.js` | 70 | One reducer over the draft envelope — replaces 17 `useState`; returns dirty-only edits |
| `hooks/useCategoryPicker.js` | 80 | Suggestion + name search (2 of the 4 inline `api` calls) |
| `hooks/usePublishSubmit.js` | 60 | `POST /publicar`, in-flight guard, error surface |
| `hooks/useMarkupOffset.js` | 50 | Existing offset fetch, extracted verbatim |
| `PublishFieldRow.jsx` | 60 | One labelled control + **source badge** — the D2 primitive |
| `ProductFieldsSection.jsx` / `VariantFieldsSection.jsx` | 90 ea. | Catalog-driven `PublishFieldRow` loops |
| `MeasurementSection.jsx` | 90 | Profile selector + 4 controls + blocked banner |
| `CategorySection.jsx` | 90 | Category picker UI |
| `DescriptionEditor.jsx` | 120 | TipTap + toolbar, moved verbatim (non-goal to touch) |
| `ImageGallery.jsx` | 80 | `SortableImageTile` + dnd |

Because sections render from the envelope's field map, "every transmitted field has a control" is a loop, and the D2 audit test is one assertion over `Object.keys(draft.fields)`.

The `key={publishingRow.ean}` remount at `TiendaNubeReconcile.jsx:1229` is **load-bearing and retained**, with an explanatory comment at the call site (same treatment as U2) so it is not "optimized" away.

## Testing Strategy

Strict TDD — RED first, every slice.

| Layer | What to test | Approach |
|---|---|---|
| Unit (core) | S1 raise on missing key; `Absent` ≠ `0` per field class; U1 grams→kg golden; **U2 exact mapping, rationale in the test name**; precedence ladder incl. operator-wins; convert-then-resolve (override not re-divided); D6 ARS passthrough / USD convert / empty-rate block | Pure Python, no DB fixtures beyond a session |
| Unit (assemble) | `inventory_levels` present, `variant.stock` absent; `visibility` present, `published` absent | Payload dict assertions |
| Unit (batch) | Single item = batch of one; 429 + `Retry-After: 2` waits ≥2 s and continues; 429 ≠ ambiguous-5xx retry rule | Fake client, monkeypatched clock |
| Integration | Core invoked end-to-end with **no FastAPI request and no React** (spec's UI-independence proof); profile CRUD `403` without its permission and publish `403` with only the profile permission; sync endpoint `403` unauthorized; dead endpoint gone/gated | `pytest tests/services`, `tests/api` |
| Migration | 4 seed profiles exist after upgrade; `downgrade -1` drops cleanly | sqlite |
| Frontend (regression) | **`TnPublishModal.test.jsx` (473 l) changes by import path only** in the refactor slice | If any assertion needs editing, the refactor changed behaviour and is wrong |
| Frontend (additive) | Per-hook `renderHook` tests; `PublishFieldRow` render; D2 audit loop; SEO 70/320 limits; blocked-publish state names the missing fields | New files under `tn-publisher/` |
| Untouched | `TiendaNubeReconcile.test.jsx` (1614 l) — the modal's props contract is unchanged | Green throughout |

Commands: `cd backend && ENVIRONMENT=testing DATABASE_URL=sqlite:///./test.db pytest tests/ -v --tb=short`; `cd frontend && pnpm test`. Gates: `ruff check app/`, `ruff format app/ --check`, `pnpm run lint`, `pnpm run lint:css`. No `@pytest.mark.postgres` needed — new tables use plain constraints; pgvector paths are unchanged.

## Threat Matrix

**N/A** — this change introduces no routing indirection, no shell-command construction, no subprocess spawn, no VCS/PR automation, and no executable-file classification. The closest boundary is the new cron script `sync_tn_category_embeddings.py`: it reads no `argv`, spawns no process, and builds no shell string — it calls an existing tested service function and exits with a status code. Outbound HTTPS to the TN API is an existing, already-authenticated integration, not a new process boundary.

## Migration / Rollout

1. **PR 1** — embedding sync. Deploy, invoke the endpoint **once manually**, verify `tn_category_embedding` row count, then schedule the script weekly (TN category trees change rarely). **Cold start is safe by construction**: while the table is empty, `suggest_category` returns `{"suggestions": [], "top": None}` and the modal falls back to name search — behaviour already covered by `TnPublishModal.test.jsx:137`. No feature flag needed.
2. **PR 2** — defect cleanup. No data touched.
3. **PRs 3–5** — additive Alembic migration (3 tables + 4 seed profiles). **D3's blocking gate MUST NOT merge before the profile CRUD + selector are reachable**, or ~97 items become silently unpublishable. Enforced by slice ordering: profiles (PR 4) precede the core's gate (PR 5).
4. **PRs 6–7** — frontend. PR 6 is a pure refactor with zero behaviour change; PR 7 adds controls.

Rollback: `alembic downgrade -1` drops the three additive tables; nothing else reads them. Products already published with the full field set are **not** rolled back and stay correct in TN — the shipped mapping is the same one the existing 535 products use (U2). No existing pricing/product/reconciliation column is written by this change.

## Open Questions — RESOLVED (tasks phase)

Three product decisions were proposed for maintainer approval; all three are now decided and recorded
in `proposal.md` as D10–D12.

- [x] **Profile permission name — D10.** `admin.gestionar_tn_perfiles`, a NEW permission, matching the
  existing `admin.gestionar_tn_publicacion` / `admin.gestionar_tn_reconcile_banlist` /
  `admin.ver_items_sin_mla` seeding shape. Distinct from `admin.gestionar_tn_publicacion` per D5,
  separable in both directions.
- [x] **Suggestion strength — D11.** No usage-count threshold. The suggested profile is **preselected
  in the selector but not applied** — `weight`/`width`/`height`/`depth` stay empty until the operator
  explicitly confirms the profile. This supersedes the `uso_count >= 3` threshold proposal below: the
  gate is an explicit confirm action, not a count-based auto-fill.
- [x] **SEO and tags sourcing — D12.** `seo_title` = name truncated to 70 chars; `seo_description` =
  HTML-stripped description truncated to 320 chars; `tags` = Marca + Categoría. All three prefilled
  (`source = "empty"` when untouched, per the seeding-not-deriving principle below) and fully
  operator-editable (D2). **`tags = Marca + Categoría` is an orchestrator assumption pending maintainer
  confirmation** — treat it as lower-confidence than D1–D11.

<details>
<summary>Original proposed text (superseded by the decisions above, kept for audit trail)</summary>

- **Profile permission name.** Proposal: `admin.gestionar_tn_perfiles`, matching the existing `admin.gestionar_tn_publicacion` / `admin.gestionar_tn_reconcile_banlist` / `admin.ver_items_sin_mla` shape. Distinct from `admin.gestionar_tn_publicacion` per D5.
- **Suggestion strength.** Proposal: preselect the profile only when `uso_count >= 3` for that exact `(categoria, subcategoria)`; below the threshold, highlight it in the selector but leave the selector empty. Never auto-apply without the source badge visible.
- **SEO and tags sourcing.** Proposal: `seo_title` seeded from the resolved `name`, truncated at 70 on a word boundary; `seo_description` seeded from the plain-text projection of the sanitized description, truncated at 320; `tags` empty by default.

</details>

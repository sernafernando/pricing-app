# Design: ML Bot Phase B — derive-to-admin lane (Factura A / CUIT)

## Technical Approach

Dedicated back-office task lane, orthogonal to the Phase A reply lifecycle. When `drafting_service._draft_one` classifies a settled anchor as `invoice_cuit_change`, a best-effort derive hook creates exactly one `ml_bot_admin_pending_requests` row (`status='new'`, prefilled from ML user data + extracted CUIT/name + best-effort AFIP padrón), then continues the normal `_mark_awaiting_human` path unchanged. Operators work the queue from a new "Pendientes" tab in `MLQuestions.jsx`; the customer acknowledgement reuses the Phase A take-over → edit → `POST /messages/{id}/send` path with a canned template. Nothing auto-sends. Mirrors the proposal ADR (separate table, not extra `ml_bot_messages` columns) and the exploration recommendation.

## Architecture Decisions

| # | Decision | Choice | Rejected | Rationale |
|---|----------|--------|----------|-----------|
| 1 | Task storage | Dedicated `ml_bot_admin_pending_requests` table | Extra columns on `ml_bot_messages` | Reply state (`bot_status`) and back-office task state are independent (a message can be `sent` while its task is still `new`); mirrors Phase A's own `bot_status`-vs-`status` split; generalizes to future derive types. |
| 2 | Derive trigger guard | `_DERIVE_CATEGORIES = frozenset({"invoice_cuit_change"})` allow-list | Free-text category compare / regex on raw text | Category is an LLM-controlled string; mirror `_CLAIM_CATEGORIES`; never build a query from it. |
| 3 | Extraction | Extend the EXISTING classify JSON with optional `extracted_cuit`/`extracted_name`; regex + `validar_cuit()` as defensive fallback | Second LLM/regex-only pass | One round-trip; free-text name order defeats regex alone; `validar_cuit()` is the authority for the check digit. |
| 4 | Duplicate CUIT in a pack | One open row per `(pack_id, request_type)`; a later DIFFERENT CUIT UPDATES the open row and APPENDS the prior value to a `superseded_values` JSONB array | Append-only free-text note; second row | JSONB array is structured/queryable and machine-auditable (`{cuit,name,at,source}`); a prose note mixes operator text with audit data and can't be rendered as "changed from X". Admin sees the trace in the detail view. |
| 5 | `done` = fiscal audit trail | Transition requires a non-empty `resolved_cuit` in the body; stamps `resolved_cuit`/`resolved_cuit_valid`/`resolved_by`/`resolved_at` in the SAME CAS UPDATE | Bare status flip | The CUIT actually invoiced may differ from what the buyer asked; a compliance record must capture who/what/when, not just "done". |
| 6 | AFIP enrichment | Best-effort, OUTSIDE any DB session, `asyncio.wait_for(get_persona, ~8s)`, full try/except; row is created FIRST and always survives; result written in a second short `get_background_db()` block | Inline 30s call / block creation on AFIP | `AfipService.TIMEOUT=30` and `AfipService.__init__` raises when unconfigured — enrichment must never stall the draft tick or fail the row. `afip_status` records the outcome. |
| 7 | Ack template selection | Two constants in `services/ml_messages/admin_pending_templates.py`; BE computes `suggested_ack_template` in the detail response from the row's flags | FE-side template strings | Single source of truth; avoids FE template drift; clean CUIT → "se realizará el cambio a la brevedad", invalid/mismatch → ask the buyer to CONFIRM the CUIT. |
| 8 | Single-open-row invariant | Enforced in `admin_pending_service` (find-open-then-update); Postgres-only partial UNIQUE index as belt (`dialect.name == 'postgresql'` guard) | DB unique index on all dialects | A partial-unique `postgresql_where` degrades to a FULL unique on sqlite CI, which would wrongly block a second `done` row for the same pack. App-level primary, PG belt secondary. |

## Data Flow

    draft tick ─ _draft_one(anchor) ─ parse ─ category in _DERIVE_CATEGORIES?
         │                                          │ yes (best-effort, own DB block)
         │                                          ▼
         │                       admin_pending_service.derive_from_message()
         │                         1. prefill: buyer_id → tb_mercadolibre_users_data
         │                         2. validate extracted_cuit (validar_cuit) + doc_mismatch soft check
         │                         3. INSERT/UPDATE open row (append superseded_values on change)
         │                         4. AFIP enrich (async, outside session, wait_for, try/except) → afip_status
         ▼                                          │ (failure → log by id only, row still created)
    _mark_awaiting_human(anchor)  ◄─────────────────┘  (draft NEVER fails on derive error)

    Pendientes tab ── list/detail (ver) ── claim/done/cancel (gestionar, CAS)
         └── "Preparar acuse" → Mensajes take-over + prefilled suggested_ack_template → POST /send

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/models/ml_bot_admin_pending_request.py` | Create | ORM model (schema below). |
| `backend/alembic/versions/20260723_ml_bot_admin_pending.py` | Create | Table + 2 permission seeds; chain off current head (verify `alembic heads`). |
| `backend/app/services/ml_messages/admin_pending_service.py` | Create | Derive, prefill, AFIP enrich, single-open-row, CAS helpers. |
| `backend/app/services/ml_messages/admin_pending_templates.py` | Create | `ACK_CLEAN` / `ACK_CONFIRM` constants + selector. |
| `backend/app/services/ml_messages/drafting_service.py` | Modify | `_DERIVE_CATEGORIES` + derive hook after parse (best-effort). |
| `backend/app/services/ml_questions/context_builder.py` | Modify | Prompt: emit `extracted_cuit`/`extracted_name` only for `invoice_cuit_change`. |
| `backend/app/services/ml_questions/llm_provider.py` | Modify | Accept optional fields (see Contracts); `LlmAnswer` grows two optional attrs. |
| `backend/app/routers/ml_bot.py` | Modify | Admin-pending endpoints + `_cas_transition_pending` + permission deps + response models. |
| `frontend/src/pages/MLQuestions.jsx` | Modify | "Pendientes" tab, detail/prefill view, actions, ack hand-off, manual-create trigger. |
| `backend/app/services/afip_service.py` | Reuse | Unchanged. |

## Interfaces / Contracts

Table `ml_bot_admin_pending_requests`:

    id BigInteger PK
    message_id BigInteger FK ml_bot_messages.id (nullable — manual rows may lack one)
    pack_id String(32) NULL; buyer_id BigInteger NULL
    request_type String(40) NOT NULL server_default 'invoice_cuit_change'
    source String(16) NOT NULL server_default 'bot_derived'   # bot_derived | manual
    raw_text Text NULL
    extracted_cuit String(20) NULL; extracted_name String(255) NULL; cuit_valid Boolean NULL
    prefill_nickname String(255) NULL
    prefill_identification_type/number String(255) NULL
    prefill_billing_doc_type/number String(255) NULL
    prefill_billing_first_name/last_name String(255) NULL
    doc_mismatch Boolean NOT NULL server_default false        # CUIT core ≠ stored DNI (soft)
    afip_status String(16) NULL                               # ok | not_found | unavailable | skipped
    afip_razon_social/condicion_iva/domicilio String NULL; afip_checked_at DateTime(tz) NULL
    superseded_values JSON NULL                               # append-only [{cuit,name,at,source}]
    status String(16) NOT NULL server_default 'new'           # new | in_progress | done | cancelled
    notes Text NULL; cancel_reason Text NULL
    resolved_cuit String(20) NULL; resolved_cuit_valid Boolean NULL
    resolved_by Integer FK usuarios.id NULL; resolved_at DateTime(tz) NULL
    created_by Integer FK usuarios.id NULL                    # non-null for manual rows
    claimed_by Integer FK usuarios.id NULL; claimed_at DateTime(tz) NULL
    created_at/updated_at DateTime(tz)

Indexes: `status`, `pack_id`, `message_id`; PG-only partial UNIQUE on `(pack_id, request_type)` where `status IN ('new','in_progress')`.

`parse_llm_output` backward-compat: keep `_REQUIRED_FIELDS` as a required subset; add `_OPTIONAL_FIELDS = frozenset({"extracted_cuit","extracted_name"})`. Reject when `_REQUIRED_FIELDS - fields` (missing) OR `fields - (_REQUIRED_FIELDS | _OPTIONAL_FIELDS)` (unknown) is non-empty. Existing 4-field callers stay valid; extras default `None`.

Endpoints (prefix `/ml-bot`): `GET /admin-pending` (filters: status, source, pack_id, buyer_id, cuit_valid, doc_mismatch) and `GET /admin-pending/{id}` → `ml_bot.admin_pending.ver`; `POST /admin-pending` (manual), `/claim`, `/release`, `/done` (body `resolved_cuit`), `/cancel` (body `reason`), `/enrich-afip` → `ml_bot.admin_pending.gestionar`. All transitions via `_cas_transition_pending` (mirrors `_cas_transition_message`). Detail response includes `superseded_values` and `suggested_ack_template`.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit (pytest) | derive creates one row; AFIP-down (`get_persona` raises/timeout → `afip_status='unavailable'`, row exists); invalid CUIT (`cuit_valid=False`, never auto-corrected); `doc_mismatch` soft flag; duplicate in pack updates + appends `superseded_values`; `parse_llm_output` accepts old 4-field + new optional, rejects unknown | pytest, mock `AfipService`/provider, sqlite CI |
| Integration (pytest) | CAS transitions incl. `done` rejects empty `resolved_cuit` and stamps audit fields; manual create `source='manual'`; permission deps 403; PII endpoints gated | FastAPI TestClient |
| E2E / FE (vitest) | Pendientes tab renders under permission; columns/badges; ack-template selection by flags; jump-to-message hand-off | vitest + jsdom |
| Layout | New tab renders without clipping (jsdom can't verify layout) | headless-Chromium smoke, mirror `ml-bot-resizable-columns` check |

## Threat Matrix

N/A — no shell, subprocess, VCS/PR automation, or executable-file classification. The two real risk surfaces (LLM extraction is untrusted buyer text; PII in a new table) reuse existing defenses: extraction is validated by `validar_cuit()` + human confirmation and never auto-derives a CUIT; PII is gated behind `ml_bot.admin_pending.ver` and MUST NOT be logged (log by row id only).

## Migration / Rollout

Fully additive. Down-migration drops the table + both permission rows. Removing the derive hook restores Phase A drafting exactly (optional LLM fields ignored by the relaxed parser). FE tab is permission-gated — revoke `ml_bot.admin_pending.ver` to hide without deploy. `AFIP_ACCESS_TOKEN`/`AFIP_CUIT` optional → `afip_status` degrades to `unavailable`/`skipped`.

## Open Questions

- [ ] Confirm current alembic head to chain `down_revision` (memory: main had divergent heads — run `alembic heads` before writing the revision).
- [ ] Should AFIP enrichment also run on a lazy re-check when an operator opens a `skipped`/`unavailable` row, beyond the manual `/enrich-afip` action? (Default: manual only.)

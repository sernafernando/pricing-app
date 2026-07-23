# Proposal: ML Bot Phase B — derive-to-admin lane (Factura A / CUIT)

## Intent

Phase A drafts and classifies, but `invoice_cuit_change` conversations (the high-frequency real case: "necesito Factura A", CUIT + razón social) land in the human queue as free text and are re-typed by hand into the back office. Phase B turns each one into an actionable, pre-filled, CUIT-validated admin task plus a human-confirmed templated acknowledgement — no data re-typing, no lost requests, no auto-send.

## Scope

### In Scope
- New table `ml_bot_admin_pending_requests` + migration + permission rows (mirrors the `ml_bot_messages` CAS/status shape).
- Derive hook in `drafting_service._draft_one` keyed off an allow-list constant `_DERIVE_CATEGORIES = frozenset({"invoice_cuit_change"})`.
- Optional `extracted_cuit` / `extracted_name` added to the **existing** classify JSON output (no second LLM pass).
- Pre-fill from `tb_mercadolibre_users_data` (`buyer_id` → `mluser_id`, same join as `_enrich_message_nicknames`).
- Best-effort AFIP enrichment reusing `afip_service.validar_cuit()` + `AfipService.get_persona()` as-is.
- Queue endpoints on the existing `/ml-bot` router; new permissions `ml_bot.admin_pending.ver` / `.gestionar`.
- Admin queue screen (new tab in `MLQuestions.jsx`) + canned ack template routed through the Phase A take-over → edit → send path.

### Out of Scope
- WSFE invoice emission (separate Node service, 2026-07-22 decision).
- Any automatic send; the ack is always human-confirmed.
- New classify categories or a classifier prompt rewrite (`invoice_cuit_change` already exists).
- Rebuilding the Mensajes panel (already shipped, #974).
- A generic reusable "queue" abstraction; other derive types (address change, etc.).
- Writing anything back to ERP / customer master / ML.

## Capabilities

### New Capabilities
- `ml-bot-admin-pending`: derived back-office request lifecycle (creation from classified messages, pre-fill + AFIP enrichment, operator queue, templated ack).

### Modified Capabilities
- None at spec level (`openspec/specs/` is empty; Phase A behavior is extended additively via the derive hook and the optional extraction fields).

## Approach

**Dedicated table, not extra columns on `ml_bot_messages`.** Reply lifecycle (`bot_status`) and back-office task lifecycle are orthogonal — a message can be `sent` while its derived task is still `new`. A second state machine on the same row conflates them and does not generalize past one derive type. Mirrors the precedent Phase A set (separate `bot_status` instead of overloading ML's `status`).

**Reuse over rebuild.** Classifier, AFIP padrón and the human-send path are live; Phase B adds one branch, one table, one service, one screen.

### Lifecycle

`new → in_progress → done`, plus `cancelled` (duplicate/invalid). All transitions are CAS and human-driven:

| Transition | Who | Effect |
|---|---|---|
| (derive hook) → `new` | bot | row created, never blocks the draft |
| `new → in_progress` | `ml_bot.admin_pending.gestionar` | claims row, stamps `claimed_by/at` |
| `in_progress → done` | `gestionar` | stamps `processed_by/at` |
| `in_progress → new` | `gestionar` | release/unclaim |
| `new|in_progress → cancelled` | `gestionar` | requires a reason |

Nothing transitions automatically. `ver` grants read-only access to the queue (PII gate).

### Schema sketch

`id`; refs `message_id` (FK `ml_bot_messages.id`), `pack_id`, `buyer_id`; `request_type`; `raw_text`; extracted `extracted_cuit`, `extracted_name`, `cuit_valid`; pre-filled `prefill_nickname`, `prefill_identification_type/number`, `prefill_billing_doc_type/number`, `prefill_billing_first/last_name`; AFIP `afip_razon_social`, `afip_condicion_iva`, `afip_domicilio`, `afip_status` (`ok|not_found|unavailable|skipped`), `afip_checked_at`; flags `doc_mismatch`; `status`, `notes`, `cancel_reason`; `created_at`, `updated_at`, `claimed_by/at`, `processed_by/at`. Indexes on `status`, `pack_id`, `message_id`.

### Derive hook

Inside `_draft_one`, after parsing and after the claim hard-block, when `parsed.category in _DERIVE_CATEGORIES`: create the pending row in its own short `get_background_db()` block (ADR-5), then continue to `_mark_awaiting_human` exactly as today. Pending-row creation is best-effort: a failure is logged and the message still reaches the human queue, never a failed draft.

### Business rules and edge cases

- **AFIP unavailable** (unconfigured, down, rate-limited, `AfipServiceError`): the row is still created, `afip_status` records why. Enrichment never blocks creation.
- **CUIT invalid or missing**: `cuit_valid = false`, flagged for manual entry. Never silently "corrected" or auto-derived from the stored DNI.
- **CUIT ↔ stored DNI mismatch**: set `doc_mismatch` and surface it. It is a soft cross-check — buying for a company with a different CUIT is legitimate.
- **Duplicates**: one open row per `(pack_id, request_type)` while `status in (new, in_progress)`; a later message updates the existing row instead of creating a second.
- **Category drift**: the category is a free-text LLM string — compared only against the allow-list constant, never used to build queries or branch dynamically.
- **PII**: CUIT, name, billing address are the same sensitivity class already in `tb_mercadolibre_users_data`, but the new table is gated behind `ml_bot.admin_pending.ver`, never globally readable.
- **Ack**: the operator jumps from the queue row to the message's take-over flow with a canned template pre-loaded; `messages_send_enabled` still gates the actual send.

### Admin screen

New "Pendientes" tab in `frontend/src/pages/MLQuestions.jsx` (route `/ml-preguntas` exists), rendered only with `ml_bot.admin_pending.ver`. Operator sees buyer, extracted vs pre-filled vs AFIP data side by side, validity/mismatch flags and the original message; acts: claim, mark done, cancel with reason, jump to the ack draft.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `backend/app/models/ml_bot_admin_pending_request.py` | New | Model + status docstring |
| `backend/alembic/versions/*_ml_bot_admin_pending.py` | New | Table, indexes, permission rows |
| `backend/app/services/ml_messages/admin_pending_service.py` | New | Pre-fill join, AFIP enrichment, CAS transitions |
| `backend/app/services/ml_messages/drafting_service.py` | Modified | Allow-list constant + derive hook |
| `backend/app/services/ml_messages/context_builder.py` | Modified | Prompt: optional extraction fields |
| `backend/app/services/ml_questions/llm_provider.py` | Modified | Parse optional fields (`_REQUIRED_FIELDS` unchanged) |
| `backend/app/routers/ml_bot.py` | Modified | Queue endpoints + `_check_permiso` |
| `backend/app/services/afip_service.py` | Reused | No change |
| `frontend/src/pages/MLQuestions.jsx` | Modified | New "Pendientes" tab |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| AFIP down / rate-limited / unconfigured | High | Best-effort enrichment; `afip_status` column; row always created; no retry storm |
| LLM extraction wrong or hallucinated CUIT | Med | `validar_cuit()` + regex sanity check; `cuit_valid` flag; operator confirms before acting |
| Category string drift | Low | Allow-list frozenset, mirroring `_CLAIM_CATEGORIES` |
| PII exposure in a new table | Med | Dedicated `ml_bot.admin_pending.*` permissions; no PII in logs |
| Duplicate/orphan queue rows | Med | One open row per `(pack_id, request_type)`; `cancelled` state with reason |
| Scope creep into invoice emission | Med | Explicit non-goal; Phase B only records the request |

## Rollback Plan

Fully additive. Revert per PR: the down-migration drops `ml_bot_admin_pending_requests` and its permission rows; removing the derive hook restores Phase A drafting byte-for-byte (extraction fields are optional and ignored by the existing parser); the FE tab is permission-gated, so revoking `ml_bot.admin_pending.ver` hides it without a deploy.

## Dependencies

- Phase A merged and live (done).
- `AFIP_ACCESS_TOKEN` / `AFIP_CUIT` configured for enrichment (optional — degrades gracefully).

## Delivery Slicing

- **PR1 (BE)**: model + migration + permissions, extraction fields, derive hook, pre-fill + AFIP enrichment service. 400-line budget risk: Medium — if endpoints push it over, split queue endpoints into PR1b.
- **PR2 (FE)**: "Pendientes" tab, operator actions, ack template hand-off to the existing take-over/send flow.

## Success Criteria

- [ ] A production `invoice_cuit_change` message creates exactly one pending row with pre-filled buyer data.
- [ ] AFIP unreachable still produces the row, marked `afip_status = unavailable`.
- [ ] Invalid CUIT is flagged, never auto-corrected; DNI mismatch is flagged, not blocked.
- [ ] A second message in the same pack updates the open row instead of duplicating it.
- [ ] An operator can claim → complete a request and send the ack via the Phase A human-send path.
- [ ] Nothing is sent to a buyer without explicit human confirmation.

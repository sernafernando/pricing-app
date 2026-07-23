# Spec: ml-bot-admin-pending — Phase B (derive-to-admin lane, Factura A / CUIT)

## Scope Note

This spec covers **Phase B only**: deriving `invoice_cuit_change`-classified
Phase A conversations into a dedicated back-office queue
(`ml_bot_admin_pending_requests`), pre-filling and best-effort AFIP-enriching
each request, the operator lifecycle (claim/done/cancel), and a
human-confirmed acknowledgement hand-off that reuses the EXISTING Phase A
send path. WSFE invoice emission, new classify categories, a generic derive
abstraction for other request types, and any automatic send are explicitly
OUT OF SCOPE and MUST NOT be implemented under this spec.

## Requirements

### R-1: Derive hook creates exactly one pending row per qualifying message

When `drafting_service._draft_one` classifies a settled thread's category as
a member of an explicit allow-list (`_DERIVE_CATEGORIES`, initially
`{"invoice_cuit_change"}`), the system MUST create exactly one row in
`ml_bot_admin_pending_requests` with `status = 'new'` and `source =
'bot_derived'`.

- R-1.1: The category MUST be compared only against the allow-list constant.
  It MUST NEVER be interpolated into a query or used to branch dynamically
  (category is untrusted, LLM-controlled free text).
- R-1.2: The bot-derived creation path MUST ONLY ever produce rows in state
  `new`. No other state is reachable from the derive hook.
- R-1.3: Derive-row creation MUST be best-effort: a failure (any exception)
  MUST be caught, logged (by row/message id only, never with PII), and MUST
  NOT prevent the underlying Phase A draft from completing or the thread from
  reaching its normal `_mark_awaiting_human` state.

### R-2: Manual creation for missed classifications

An operator holding `ml_bot.admin_pending.gestionar` MUST be able to create a
pending row manually (`source = 'manual'`, `created_by` populated) for a
message the classifier did not tag as `invoice_cuit_change`, using the same
schema and lifecycle as a bot-derived row.

### R-3: Duplicate CUIT in the same pack updates the open row, preserving trace

The system MUST enforce at most one OPEN row (`status IN ('new',
'in_progress')`) per `(pack_id, request_type)`.

- R-3.1: When a later message in the same pack yields a different extracted
  CUIT/name for a request_type that already has an open row, the system MUST
  UPDATE that existing row rather than creating a second one.
- R-3.2: Before overwriting, the system MUST append the prior
  `{extracted_cuit, extracted_name, at, source}` value to the row's
  `superseded_values` JSON array. The array is append-only; no prior entry is
  ever discarded or rewritten.
- R-3.3: The single-open-row invariant MUST be enforced at the application
  level (find-open-then-update) in all environments; a PostgreSQL-only
  partial unique index on `(pack_id, request_type)` filtered to
  `status IN ('new','in_progress')` MAY additionally guard against races, but
  MUST NOT be relied upon in a database that does not support it.

### R-4: Pre-fill from stored buyer data

On creation (bot-derived or manual, when a `buyer_id` is resolvable), the
system MUST pre-fill the row from `tb_mercadolibre_users_data` (nickname,
identification type/number, billing document type/number, billing
first/last name) using the same buyer join Phase A already uses for nickname
enrichment.

- R-4.1: Pre-fill values are read-only reference data captured at creation
  time; they are not themselves modified by later lifecycle transitions.

### R-5: AFIP enrichment is best-effort and never blocks row creation

The system MUST attempt to enrich the row with AFIP padrón data
(`afip_razon_social`, `afip_condicion_iva`, `afip_domicilio`) via the
existing `AfipService`, recording the outcome in `afip_status` (`ok |
not_found | unavailable | skipped`) and `afip_checked_at`.

- R-5.1: The pending row MUST be persisted BEFORE AFIP enrichment is
  attempted (or independently of its outcome) — the row's existence MUST
  NEVER depend on AFIP being reachable, configured, or fast.
- R-5.2: Any AFIP failure mode (unconfigured, network error, timeout,
  rate-limited, `AfipServiceError`) MUST result in `afip_status =
  'unavailable'` (or `'skipped'` if AFIP is not configured at all), never an
  unhandled exception that aborts the derive or the operator's request.
- R-5.3: An operator MUST be able to manually re-trigger enrichment for a row
  whose `afip_status` is `unavailable` or `skipped`.

### R-6: CUIT validity and DNI cross-check are flags, never auto-fixes

- R-6.1: An extracted or manually-entered CUIT MUST be checked with
  `validar_cuit()`; the result is stored as `cuit_valid` (boolean). An
  invalid or missing CUIT MUST NEVER be silently corrected, guessed, or
  derived from the buyer's stored DNI — it is surfaced to the operator for
  manual resolution.
- R-6.2: When the CUIT's embedded document core does not match the buyer's
  stored DNI/identification number, the system MUST set `doc_mismatch =
  true`. This is a soft, informational flag — a mismatch MUST NOT block row
  creation, claiming, or completion; buying on behalf of a company under a
  different CUIT is a legitimate case.

### R-7: Lifecycle is human-driven, CAS, and audit-complete on completion

The row's `status` MUST follow `new → in_progress → done`, with `cancelled`
reachable from `new` or `in_progress`. Every transition MUST be a single CAS
(compare-and-swap) UPDATE conditioned on the current `status` value.

- R-7.1: `new → in_progress` ("claim") requires `ml_bot.admin_pending.gestionar`
  and stamps `claimed_by`/`claimed_at`.
- R-7.2: `in_progress → new` ("release") requires `gestionar` and clears the
  claim stamps.
- R-7.3: `new | in_progress → cancelled` requires `gestionar` and a non-empty
  `cancel_reason`; a cancellation without a reason MUST be rejected.
- R-7.4: `in_progress → done` requires `gestionar` AND a non-empty
  `resolved_cuit` in the request body. The transition MUST be rejected
  (no state change) if `resolved_cuit` is empty/absent. On success, the SAME
  CAS UPDATE MUST also stamp `resolved_cuit_valid`, `resolved_by`, and
  `resolved_at` — `done` is a fiscal audit record, not a bare status flip.
- R-7.5: No transition happens automatically; every state change originates
  from an explicit authenticated operator action.

### R-8: Permission gating for PII

Two distinct permissions gate this capability:

- R-8.1: `ml_bot.admin_pending.ver` — read-only access to the queue (list,
  detail, including all PII fields: extracted/pre-filled/AFIP data). Without
  it, list/detail endpoints and the FE "Pendientes" tab MUST be inaccessible
  (403 / hidden).
- R-8.2: `ml_bot.admin_pending.gestionar` — required for every state
  transition and for manual creation. Holding `gestionar` does not imply
  `ver`; the two are independent grants.
- R-8.3: CUIT, name, and billing address data belonging to this capability
  MUST NEVER be written to application logs. Log statements referencing a
  pending row MUST reference it by row id / message id only.

### R-9: Acknowledgement is human-confirmed via the existing Phase A send path

The system MUST provide a canned acknowledgement template selection
(`suggested_ack_template`), computed server-side from the row's
`cuit_valid`/`doc_mismatch` flags, and MUST hand off to the EXISTING Phase A
take-over → edit → `POST /messages/{id}/send` path for the actual send.

- R-9.1: A clean state (`cuit_valid = true`, `doc_mismatch = false`) selects
  the "confirm nothing, change is being processed" template variant.
- R-9.2: An invalid CUIT or a doc mismatch selects a "please confirm the
  CUIT" template variant that asks the buyer to re-confirm rather than
  asserting the change will happen as requested.
- R-9.3: Phase B MUST NOT introduce any new send mechanism or any automatic
  send. The existing `messages_send_enabled` gate and human-confirmation
  requirement from Phase A apply unchanged; nothing in this capability sends
  a message to a buyer without an explicit operator action.

## Out of Scope (explicit, Phase B)

- WSFE invoice emission (separate Node service, per prior decision).
- Any automatic/unattended send of the acknowledgement.
- New classify categories or a classifier prompt rewrite.
- A generic reusable "derive" abstraction for request types other than
  `invoice_cuit_change`.
- Writing back to ERP, the customer master, or MercadoLibre.

## Acceptance Scenarios

### Scenario: qualifying message derives exactly one pending row

- GIVEN a settled thread is classified with `category = invoice_cuit_change`
- WHEN `_draft_one` runs the derive hook
- THEN exactly one row is created in `ml_bot_admin_pending_requests` with
  `status = 'new'`, `source = 'bot_derived'`
- AND the row is pre-filled from `tb_mercadolibre_users_data` for the
  resolved buyer
- AND the underlying Phase A draft still reaches `_mark_awaiting_human`
  exactly as it would without the derive hook.

### Scenario: AFIP unavailable still creates the row

- GIVEN AFIP enrichment is attempted for a newly derived row
- WHEN `AfipService.get_persona()` raises, times out, or AFIP is
  unconfigured
- THEN the pending row still exists with `status = 'new'`
- AND `afip_status` is set to `'unavailable'` (or `'skipped'` if
  unconfigured), never left null or causing the derive to fail.

### Scenario: invalid CUIT is flagged, not auto-corrected, and drives the confirm-ack variant

- GIVEN an extracted CUIT fails `validar_cuit()`
- WHEN the pending row is created or updated
- THEN `cuit_valid = false` is stored and the original extracted value is
  preserved unmodified (no auto-correction, no derivation from stored DNI)
- AND `suggested_ack_template` resolves to the "confirm the CUIT" variant.

### Scenario: CUIT/DNI mismatch is a soft flag, never a block

- GIVEN the CUIT's document core differs from the buyer's stored DNI
- WHEN the pending row is created
- THEN `doc_mismatch = true` is set
- AND the row can still be claimed and completed normally; the mismatch is
  surfaced to the operator, not enforced as a hard stop.

### Scenario: duplicate CUIT in the same pack updates and preserves trace

- GIVEN an open row exists for `(pack_id, request_type)` with
  `extracted_cuit = A`
- WHEN a later message in the same pack extracts a different CUIT `B` for
  the same `(pack_id, request_type)`
- THEN the existing open row is UPDATED to `extracted_cuit = B` (no second
  row is created)
- AND the prior value `{cuit: A, ...}` is appended to `superseded_values`,
  never discarded.

### Scenario: done requires a resolved CUIT and stamps the audit fields

- GIVEN a row is `in_progress`
- WHEN an operator with `gestionar` attempts `in_progress → done` with an
  empty `resolved_cuit`
- THEN the transition is rejected and `status` remains `in_progress`
- WHEN the same operator retries with a non-empty `resolved_cuit`
- THEN the transition succeeds, `status = done`, and `resolved_cuit`,
  `resolved_cuit_valid`, `resolved_by`, `resolved_at` are stamped in the same
  update.

### Scenario: manual creation for a message the classifier missed

- GIVEN a message was NOT classified as `invoice_cuit_change` but an
  operator recognizes it should be
- WHEN the operator (holding `gestionar`) creates a pending row manually
- THEN the row is created with `source = 'manual'` and `created_by`
  populated, following the same schema and lifecycle as a bot-derived row.

### Scenario: unauthorized access to PII is denied

- GIVEN a user lacks `ml_bot.admin_pending.ver`
- WHEN they call the list or detail endpoint, or open the FE "Pendientes"
  tab
- THEN access is denied (403 on the API; the tab is not rendered on the FE)
- AND no CUIT/name/billing data from this capability is exposed to them.

### Scenario: acknowledgement send always requires human confirmation

- GIVEN a pending row is `done` (or any state) and an operator wants to
  notify the buyer
- WHEN the operator opens the ack hand-off
- THEN they land in the EXISTING Phase A take-over → edit → send flow with
  a `suggested_ack_template` pre-loaded
- AND no message is sent to the buyer until the operator explicitly
  confirms and submits the send
- AND the existing `messages_send_enabled` gate still applies unchanged.

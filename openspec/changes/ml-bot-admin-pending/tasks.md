# Tasks: ML Bot Phase B — derive-to-admin lane (Factura A / CUIT)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~750-950 (model+migration ~150, service ~200, drafting/context/provider ~120, router ~180, FE tab ~250+) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR1 → PR2 → PR3 |
| Delivery strategy | ask-on-risk |
| Chain strategy | feature-branch-chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Migration+model+extraction+derive hook+AFIP enrich | PR1 | `pytest backend/tests/services/ml_messages/test_admin_pending_service.py backend/tests/services/ml_messages/test_drafting_service.py -q` | N/A — pure BE unit/integration, no live scenario needed pre-endpoints | drop migration + revert derive hook, Phase A untouched |
| 2 | Endpoints + permission seed + templates | PR2 (base=PR1 branch) | `pytest backend/tests/routers/test_ml_bot_admin_pending.py -q` | `curl` against local uvicorn for each transition | revert router changes + permission migration |
| 3 | Pendientes tab (FE) | PR3 (base=PR2 branch) | `npx vitest run src/pages/MLQuestions.test.jsx` | headless-Chromium smoke on `/ml-preguntas` Pendientes tab | revert MLQuestions.jsx tab addition, permission-gated hide |

## Phase 0: Pre-flight (BLOCKING)

- [x] 0.1 Run `alembic heads` on current branch (rebased off latest main); record the single real head; abort if >1 head and resolve first. (single head = `20260722_tn_producto_published`)
- [x] 0.2 Set `down_revision` in the new migration file to that exact head (no guessed value).

## Phase 1: Migration + Model (PR1)

- [x] 1.1 RED: `backend/tests/models/test_ml_bot_admin_pending_request.py` — asserts table/columns/defaults exist per design schema.
- [x] 1.2 GREEN: create `backend/app/models/ml_bot_admin_pending_request.py` ORM model per design schema.
- [x] 1.3 GREEN: create `backend/alembic/versions/20260723_ml_bot_admin_pending.py` — table + indexes (`status`,`pack_id`,`message_id`) + 2 permission rows (`ml_bot.admin_pending.ver`/`.gestionar`, mirror `20260710_ml_bot_messages.py`); PG-only partial UNIQUE guarded by `op.get_bind().dialect.name == 'postgresql'`.
- [x] 1.4 Verify migration runs clean on sqlite CI and Postgres dev; verify down-migration drops table + permission rows. (`alembic heads` resolves to single new head; downgrade path written and code-reviewed; live Postgres round-trip deferred to task 7.3)

## Phase 2: Extraction (PR1)

- [x] 2.1 RED: `backend/tests/unit/test_ml_bot_llm_provider.py::TestParseLlmOutputOptionalFields` — old 4-field payload still parses; new optional `extracted_cuit`/`extracted_name` parse; unknown field rejected.
- [x] 2.2 GREEN: `llm_provider.py` — add `_OPTIONAL_FIELDS`, relax `parse_llm_output` to required-subset ∪ optional-whitelist; `LlmAnswer` grows two optional attrs.
- [x] 2.3 GREEN: `context_builder.py` — prompt emits `extracted_cuit`/`extracted_name` only for `invoice_cuit_change`.
- [x] 2.4 Verify existing question-drafting tests stay green (no regression on 4-field callers).

## Phase 3: Derive Service (PR1)

- [x] 3.1 RED: `test_admin_pending_service.py::TestDeriveCreatesOneRow` — happy path, prefill from `tb_mercadolibre_users_data`.
- [x] 3.2 RED: `test_admin_pending_service.py::TestDeriveInvalidCuitNeverAutocorrected` — `cuit_valid=False`, no mutation of extracted value.
- [x] 3.3 RED: `test_admin_pending_service.py::TestDeriveAfipDownStillCreatesRow` — mock AFIP to raise/timeout → `afip_status='unavailable'`, row exists.
- [x] 3.4 RED: `test_admin_pending_service.py::TestDeriveDuplicateCuitUpdatesAndSupersedes` — second different CUIT in same pack updates open row, appends prior to `superseded_values`.
- [x] 3.5 RED: `test_admin_pending_service.py::TestDeriveDocMismatchFlag` — CUIT core ≠ stored DNI sets `doc_mismatch=True`, still creates row.
- [x] 3.6 GREEN: create `backend/app/services/ml_messages/admin_pending_service.py` — `derive_from_message()`, prefill join, `validar_cuit()` validation, find-open-then-update, `superseded_values` append, async AFIP enrichment via `asyncio.wait_for` outside DB session. (CAS transition helper for claim/release/done/cancel deferred to PR2 alongside the endpoints that need it)
- [x] 3.7 GREEN: create `backend/app/services/ml_messages/admin_pending_templates.py` — `ACK_CLEAN`/`ACK_CONFIRM` constants + `select_ack_template()`.

## Phase 4: Wire Derive Hook (PR1)

- [x] 4.1 RED: `test_ml_bot_messages_drafting_service.py::TestDraftOneDeriveAdminPendingHook::test_draft_one_derives_admin_pending_on_invoice_cuit_change` — category in allow-list triggers derive call.
- [x] 4.2 RED: `test_ml_bot_messages_drafting_service.py::TestDraftOneDeriveAdminPendingHook::test_draft_one_derive_failure_does_not_fail_draft` — derive raises → draft still completes, `_mark_awaiting_human` still called.
- [x] 4.3 GREEN: `drafting_service.py` — add `_DERIVE_CATEGORIES = frozenset({"invoice_cuit_change"})`; call derive hook after claim hard-block, best-effort try/except (never fails the draft).

## Phase 5: Endpoints (PR2)

- [x] 5.1 RED: `backend/tests/routers/test_ml_bot_admin_pending.py::test_list_and_get_require_ver_permission` — 403 without permission.
- [x] 5.2 RED: `test_ml_bot_admin_pending.py::test_get_detail_returns_suggested_ack_template` — clean vs invalid/mismatch variant.
- [x] 5.3 RED: `test_ml_bot_admin_pending.py::test_done_requires_resolved_cuit` — empty body rejected; success stamps `resolved_cuit/_valid/by/at`.
- [x] 5.4 RED: `test_ml_bot_admin_pending.py::test_manual_create_source_manual` — `POST /admin-pending` sets `source='manual'`, `created_by`.
- [x] 5.5 GREEN: `routers/ml_bot.py` — `GET /admin-pending` (filters), `GET /admin-pending/{id}`, `POST /admin-pending`, `/claim`, `/release`, `/done`, `/cancel`, `/enrich-afip`; permission deps `ml_bot.admin_pending.ver`/`.gestionar`; response models.

## Phase 6: Pendientes Tab (PR3)

- [ ] 6.1 RED: `frontend/src/pages/MLQuestions.test.jsx::test_pendientes_tab_renders_filtered_list` — under permission, columns/badges.
- [ ] 6.2 RED: `MLQuestions.test.jsx::test_detail_prefill_view_shows_extracted_vs_afip` — side-by-side render.
- [ ] 6.3 RED: `MLQuestions.test.jsx::test_done_modal_captures_resolved_cuit` — modal blocks submit without value.
- [ ] 6.4 GREEN: `MLQuestions.jsx` — add "Pendientes" tab (filters, list, detail/prefill, claim/done/cancel actions, `done` modal, manual-create trigger from Mensajes + blank from Pendientes, jump-to-message/ack hand-off into existing take-over → send path).
- [ ] 6.5 Mandatory headless-Chromium gate: render page with realistic data; confirm tab renders, filters work, detail/prefill shows, done-modal captures `resolved_cuit`, and Mensajes table's TanStack colgroup is undisturbed.

## Phase 7: Verification

- [ ] 7.1 Run full backend suite; confirm Phase A drafting/messages tests unchanged.
- [ ] 7.2 Run full frontend suite + headless-Chromium smoke.
- [ ] 7.3 Manual: verify `alembic upgrade head` then `alembic downgrade -1` round-trips cleanly on dev DB.

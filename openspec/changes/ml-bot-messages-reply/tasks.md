# Tasks: ml-bot-messages-reply — Phase A

Scope: draft + classify + human-send only. NO auto-send, NO admin table, NO AFIP.
TDD: write the failing test first (pytest BE / vitest FE), then implement.

## Legend
- `[BE]` backend, `[FE]` frontend, `[USER]` user-owned/manual gate (not agent-runnable)
- `(spec R-x)` links task to spec requirement

---

## Group 0 — User-owned verification gates (BLOCKING, track early, do not implement send/link until satisfied)

- [ ] **T0.1 [USER]** Live-verify ML send endpoint: one real staging `POST /messages/packs/{pack_id}/sellers/{seller_id}?tag=post_sale` against a real pack; capture exact success/error response shape and any "already sent" idempotency signal. (spec R-8, R-8.1, R-9.2)
  - Done when: real request/response captured and pasted into design "Open Questions"; `messages_send_enabled` may only flip on after this.
- [ ] **T0.2 [USER]** Verify ML conversation URL format: open a real pack's conversation in ML UI (or `/api/ml/render?resource=...&format=json`) and confirm `https://www.mercadolibre.com.ar/mensajes/{pack_id}` resolves, or capture the correct format. (spec R-6.1, R-9.2)
  - Done when: confirmed URL format recorded; FE link task (T7.3) may only ship after this.

These two gates block T5.4 (send wiring enablement) and T7.3 (FE ML link) respectively — everything else can proceed in parallel.

---

## Group 1 — Migration + model (sequential, foundation for everything else)

- [x] **T1.1 [BE]** Test: migration adds nullable `bot_status`, `drafted_answer`, `intent_category`, `confidence`, `answer_source`, `llm_provider`, `attempts` (default 0), `last_error`, `drafted_at`, `bot_updated_at` columns + partial index on `bot_status`, dialect-guarded (sqlite CI skip for partial index), mirroring `test_ml_bot_answer_history_migration`. (design File Changes; spec R-3.1)
- [x] **T1.2 [BE]** Implement the alembic migration (up + down) to pass T1.1.
- [x] **T1.3 [BE]** Update `app/models/ml_bot_message.py` with new columns + docstring documenting the `bot_status` state machine (NULL|pending → drafting → {awaiting_human|blocked_claim|failed}; drafting→pending; awaiting_human→superseded; awaiting_human|blocked_claim→taken_over→{sent|failed}; failed→pending). (spec R-3.1, R-3.2)

Depends on: none. Blocks: all of Group 2-5.

---

## Group 2 — Settle window + thread aggregation (parallel with Group 3 once Group 1 lands)

- [x] **T2.1 [BE]** Test: settle-window helper — settled vs not-settled given `now` and `received_at` of unanswered buyer messages; fail-safe default on missing/malformed `messages_settle_minutes` config (mirror `wait_minutes` fail-safe). (spec R-2, R-2.3)
- [x] **T2.2 [BE]** Implement settle-window check in `drafting_service.py` (or a small helper module) to pass T2.1.
- [x] **T2.3 [BE]** Test: aggregation groups only buyer messages since last seller reply in the pack (or since pack start); a seller reply (bot or human) closes the window; anchor = latest unanswered buyer message. (spec R-1, R-1.1, R-1.2)
- [x] **T2.4 [BE]** Implement `_fetch_settled_packs` aggregation logic to pass T2.3, including live pack-thread fetch for "has the seller already replied" guard (since ingestion drops outgoing seller messages, per design Data Flow).
- [x] **T2.5 [BE]** Test: burst re-open — a new buyer message arriving after `awaiting_human` (draft exists, no send yet) re-opens aggregation and merges into an updated cycle rather than a disconnected second draft. (spec R-2.2, scenario "new message re-opens aggregation")
- [x] **T2.6 [BE]** Implement `awaiting_human → superseded` transition + re-aggregation to pass T2.5.

Depends on: Group 1. Can run in parallel with Group 3 (context builder) since both only need the model/columns.

---

## Group 3 — Context builder (parallel with Group 2)

- [x] **T3.1 [BE]** Test: `ScopedContext` builder produces delimited buyer-turn text + conversation history + order/item attrs, reusing `policy.py` denylist/tag-neutralization; injection-safe delimiters verified against a manipulation-pattern fixture. (spec R-7, R-7.1; design `context_builder.py`)
- [x] **T3.2 [BE]** Implement `app/services/ml_messages/context_builder.py` to pass T3.1.
- [x] **T3.3 [BE]** Test: static tone-only few-shot examples never leak facts into context; `messages_fewshot_dynamic_enabled` flag defaults off; `embed_query` plumbed but unused while off (no crash, no live call). (design "Few-shot is tone-only")
- [x] **T3.4 [BE]** Implement the tone-only few-shot gate to pass T3.3.

Depends on: Group 1. Parallel with Group 2.

---

## Group 4 — Draft + classify service + state machine (sequential, depends on Groups 2 & 3)

- [x] **T4.1 [BE]** Test: one LLM call → `{answer, category, confidence, can_answer}` via `parse_llm_output` + `RotatingProvider`, mocked provider; low-confidence collapses to `other_unknown` regardless of raw label. (spec R-4, R-4.1)
- [x] **T4.2 [BE]** Test: claim classification (or non-`clean` `moderation_status`) → `bot_status='blocked_claim'`, **no draft written**, thread still visible for human review with flag. (spec R-4 claim, R-4.2, scenario "claim message is flagged")
- [x] **T4.3 [BE]** Test: manipulation-signal match in buyer text routes to safe fallback BEFORE any LLM call (assert provider.complete not called). (spec R-7.1, scenario "buyer message attempts prompt injection")
- [x] **T4.4 [BE]** Test: denylist violation post-draft (exact price/stock/address) → draft rejected, replaced with safe fallback; fallback text is what's stored/surfaced, not the raw violating draft. (spec R-7, scenario "guardrail rejects a policy-violating draft")
- [x] **T4.5 [BE]** Implement `run_ml_messages_draft_cycle` in `drafting_service.py` to pass T4.1–T4.4: settle → aggregate → claim (CAS) → classify → `awaiting_human`/`blocked_claim`/`failed`.
- [x] **T4.6 [BE]** Test: every `bot_status` transition is a single CAS UPDATE conditioned on current value (assert WHERE clause includes prior state; simulate concurrent claim attempt losing). (spec R-3.4)
- [x] **T4.7 [BE]** Test: stale-`drafting` reclaim (a row stuck in `drafting` past a timeout reclaims to `pending`); `failed → drafting` manual retry transition works. (spec R-3.3; design "stale-drafting reclaim") — note: the manual `failed → pending` retry transition itself is a Phase B/PR2 human-facing endpoint concern; PR1 only guarantees `failed` is a terminal, retry-eligible state and that automatic stale-`drafting` reclaim works.
- [x] **T4.8 [BE]** Implement CAS transitions + stale reclaim to pass T4.6/T4.7.
- [x] **T4.9 [BE]** Wire `ml_messages_draft_task` into `app/main.py` (warm-up ~120s, `poll_interval_seconds`), mirroring `ml_questions_draft_task`; single-worker fcntl guard (reused from the existing `bg_lock_fd` gate — no new lock needed); per-pack error isolation (one pack's failure doesn't stop the cycle). (design "Data Flow", File Changes)

Depends on: Group 2, Group 3. Sequential within itself (T4.5/T4.8 depend on prior tests).

---

## Group 5 — send_message + human take-over/edit/send endpoints (parallel with Group 4 for T5.1-5.3; T5.4 gated on T0.1)

- [x] **T5.1 [BE]** Test: `ml_api_client.send_message(pack_id, seller_id, buyer_id, text)` builds correct POST body/URL, bearer auth, mirrors `post_answer` error handling (transient → None, permanent 4xx → raise `MessageSendPermanentError`). Mock the HTTP layer — this test does NOT require live ML access. (design "send_message seam"; spec R-8.2 defensive-write clause)
- [x] **T5.2 [BE]** Implement `send_message` in `app/services/ml_api_client.py` to pass T5.1. Also added `get_pack_conversation_status` + wired `claim_ids`-based hard-block into `drafting_service._draft_one` (PRIMARY claim signal, ahead of the classifier/moderation fallbacks).
- [x] **T5.3 [BE]** Test: `take-over` / `answer` (edit) / `send-now` router endpoints — state transitions `awaiting_human|blocked_claim → taken_over → {sent|failed}`; `answer_source` recorded (`human_edited` vs `human_verbatim`); send failure → `failed` + `last_error` populated, not silently dropped. (spec R-5, R-5.1, R-5.2, scenario "human takes over, edits, and sends" + "send endpoint failure surfaces")
- [x] **T5.4 [BE]** Test: `send-now` fail-closed (409) when `messages_send_enabled=False` (default) — asserts the send path is disabled absent the flag, independent of T0.1 status. (spec R-8, R-8.2, scenario "send action is disabled until endpoint is live-verified")
- [x] **T5.5 [BE]** Implement the router endpoints (new or extend `app/routers/ml_bot.py`) to pass T5.3/T5.4. **Do not flip `messages_send_enabled` default in code — it stays off until T0.1 is checked off by the user.** New `ml_bot.messages.responder` permission seeded via migration `20260722_ml_bot_messages_responder_permiso`. Also added nickname enrichment (`buyer_id → tb_mercadolibre_users_data.mluser_id → nickname`, batched, no N+1) on `GET /messages`.

Depends on: Group 1 (model), Group 4 for state-machine shape reuse (can start once T4.6/T4.8 land, or stub the CAS helper). T5.5's *enablement* (not the code) is gated on T0.1.

---

## Group 6 — Frontend (Mensajes tab)

- [x] **T6.1 [FE]** Test (vitest): thread-header action buttons (take-over/edit/send) render inside the thread-header `colSpan` cell without altering the resizable `<colgroup>` from #960. (spec R-5.3; design File Changes note on #960)
- [x] **T6.2 [FE]** Implement thread-header actions in `MLQuestions.jsx`, reusing the Preguntas edit modal pattern, to pass T6.1.
- [x] **T6.3 [FE+BE]** Test (vitest + pytest): `messages_send_enabled` is exposed on `GET /ml-bot/status` (BE) and consumed by the FE to render "Enviar" disabled with an explanatory `title` when the gate is off, while Tomar/Editar stay enabled; `category === 'claim'` shows a visible badge; edit modal opens with prefilled draft or blank if none exists; a `sent: false` (HTTP 200) response from `POST .../send` surfaces a visible row-scoped error instead of a false success. (spec R-4.2 "flag visible to operator", scenario "claim message is flagged"; PR3 review findings 1-2)
- [x] **T6.4 [FE+BE]** Implement claim badge + gate-disabled Enviar button + `sent:false` error surfacing to pass T6.3.
- [x] **T7.1 [FE]** Test (vitest): detail spoiler (`renderDetailRow`-equivalent) shows full pack conversation (not just the drafting window), current draft + category/confidence. (spec R-6, scenario "detail spoiler shows full pack + draft + ML link")
- [x] **T7.2 [FE]** Implement the detail spoiler to pass T7.1.
- [x] **T7.3 [FE, gated on T0.2]** Implement the ML conversation link using the verified URL format from T0.2 (fallback: seller-hub order link if T0.2 finds `.../mensajes/{pack_id}` doesn't resolve). Do not hardcode the unverified URL before T0.2 is checked off. — orchestrator confirmed T0.2 verified format: `https://www.mercadolibre.com.ar/ventas/nueva/mensajeria/{pack_id}` (no query string).

Depends on: Group 1 (columns exist), Group 5 (endpoints for actions). T6.1-T6.4 can run parallel to T7.1-T7.2 (different UI regions: header vs detail row). T7.3 is blocked on T0.2.

---

## Group 7 — Mandatory headless-Chromium FE gate (final, sequential after Group 6)

- [ ] **T8.1 [FE]** Headless-Chromium test (not jsdom) with realistic seeded data: confirm thread-header actions render correctly, edit modal opens and saves, detail spoiler expands showing thread+draft, and column resize (#960) still works after these changes. (spec R-9.1)
  - Done when: this test passes in CI/local headless run — this is the project's established hard gate for MLQuestions.jsx interaction verification and cannot be satisfied by vitest+jsdom alone.

Depends on: Group 6 fully merged.

---

## Suggested PR slicing (per orchestrator instruction, keep each reviewable)

1. **PR 1 — BE foundation**: Group 1 (migration/model) + Group 2 (settle/aggregation) + Group 3 (context builder). No behavior change visible to users; additive only.
2. **PR 2 — BE draft/classify + send seam**: Group 4 (draft cycle, CAS state machine, task wiring) + Group 5 (send_message + endpoints, gated off by default). Reviewable independent of FE.
3. **PR 3 — FE actions + detail + Chromium gate**: Group 6 + Group 7. Depends on PR 2 merged (needs the endpoints and columns).

Each PR should be small enough to review in isolation; PR 2 is the highest-risk (money/send-adjacent, CAS correctness) — expect a `review-reliability` or `review-risk` lens per the orchestrator's risk table given it touches an external send boundary and state-machine correctness.

## Parallelization summary

- Group 2 and Group 3 run in parallel (after Group 1).
- Group 5 (T5.1-5.2) can start in parallel with Group 4 (independent of draft cycle); T5.3-T5.5 need the CAS shape from Group 4.
- Group 6 header actions (T6.1-6.4) and detail spoiler (T7.1-7.2) can run in parallel with each other; both need Group 5 endpoints.
- T0.1/T0.2 (user gates) should be tracked from day one but do not block Groups 1-4, 6 (minus T7.3) — only block T5.5's live enablement and T7.3's link implementation.

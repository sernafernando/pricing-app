# Design: ML Bot Mensajes — Phase A (draft + classify, human-send only)

## Technical Approach

Mirror the Preguntas pipeline (CAS state machine, `RotatingProvider`, denylist/manipulation guardrails, ADR-5 short sessions with the LLM call outside any session, tone-only few-shot) but make it **thread-scoped** and **debounced**. Phase A adds draft/classification columns to `ml_bot_messages` (additive migration), a per-pack aggregation + settle window, a new `ml_messages/` service package (context builder, drafting/classification, draft cycle), a live-verify-gated `send_message` seam, and FE thread actions. **Phase A never auto-sends** — every unit lands in a human-review state; claims are hard-blocked from drafting. Out of scope here: admin-pending table/screen, AFIP lookup, auto-send/allowlist, attachments (Phase B/C).

## Architecture Decisions

### Decision: Draft unit = the pack's latest unanswered buyer message ("anchor")
**Choice**: Draft/classification columns live on `ml_bot_messages`; `bot_status` is non-NULL only on the **anchor** row (latest unanswered buyer message per pack). Earlier messages in the turn stay `bot_status IS NULL`.
**Alternatives**: separate `ml_bot_message_drafts` table (deferred — extra join, no Phase-A need); per-message drafting (rejected — fragmented bursts must become one reply).
**Rationale**: orchestrator mandate to extend `ml_bot_messages`; anchor pattern keeps 1 CAS row = 1 bot unit exactly like Preguntas, and ingestion stays 100% untouched (pure additive columns).

### Decision: `bot_status` is a NEW column, isolated from ML's `status`
**Choice**: separate `bot_status String(24)` lifecycle column; ML's raw `status` untouched.
**Rationale**: proposal hard rule — collision risk; ML `status` semantics must not change.

### Decision: Stateless settle window (no ingest write)
**Choice**: a pack is "settled" when `now − max(received_at of its unanswered buyer msgs) ≥ messages_settle_minutes` (`ml_bot_config`, default **3**). No `pending` row written at ingest — the draft cycle computes settle from timestamps and CAS-claims `NULL/pending → drafting`.
**Alternatives**: per-message `settle_until` written at ingest (rejected — mutates the read-only ingestion path).
**Rationale**: additive-only, debounce lives entirely in the draft cycle; a new mid-window buyer message just moves the anchor and re-opens aggregation next tick.

### Decision: ONE LLM call returns `{answer, category, confidence, can_answer}`
**Choice**: reuse `parse_llm_output` (schema already fits) + `RotatingProvider`; a messages-specific system prompt adds a category enum + post-sale tone. Store `drafted_answer/intent_category/confidence/answer_source/llm_provider` on the anchor.
**Alternatives**: separate classify + draft calls (rejected — 2× rotation cost/latency, no Phase-A benefit).

### Decision: Claim detection = classifier category (primary), human backstop (fallback)
**Choice**: PRIMARY signal is the LLM `category ∈ CLAIM_CATEGORIES` → `bot_status='blocked_claim'`, **no draft written**. Corroborating: a non-`clean` `moderation_status` also routes to human (never drafts an auto-reply). The ML claim-resource (`/post-purchase/v1/claims`) lookup is **deferred to Phase B/C**.
**Alternatives**: ML claim-context lookup now (rejected — extra API surface, unverified mapping; classifier + human review is sufficient safety for a human-only phase).
**Rationale**: cheapest robust signal; FE always exposes take-over so a misclassified claim is caught by a human. **Fallback if classifier misses**: claims are visually badged and the send button is disabled for claim category.

### Decision: Few-shot is tone-only, static in Phase A
**Choice**: reuse the dynamic-fewshot retrieval *code path* but gate messages behind a new `messages_fewshot_dynamic_enabled` flag (default **off**) → static tone examples only. Query embedding is plumbed through (`embed_query` outside session) but unused while off; no messages capture corpus in Phase A.
**Rationale**: no messages answer-history corpus exists yet (cold start); dynamic retrieval over the questions corpus is semantically mismatched. Facts always come from context, never few-shot.

### Decision: `send_message` seam built but live-verify + config gated
**Choice**: new `ml_client.send_message(pack_id, seller_id, buyer_id, text)` → `POST https://api.mercadolibre.com/messages/packs/{pack_id}/sellers/{seller_id}?tag=post_sale`, body `{"from":{"user_id":seller_id},"to":{"user_id":buyer_id},"text":text}`, bearer token (mirrors `post_answer` error handling: transient→None, permanent 4xx→raise, best-effort idempotency). **HARD GATE**: send path enabled only when `messages_send_enabled` (default **off**) AND a **user-owned live verification** (real ML POST against a real pack — sandbox has no ML creds) has passed. While off: BE returns 409, FE button disabled.
**Rationale**: WebSearch-corroborated-only endpoint (proposal High risk); no automated test can prove it — a human live-verify is the only safe gate.

## Data Flow

    ml_bot_messages (buyer rows, ingested)
        │  draft cycle (main.py task, single-worker fcntl)
        ▼
    _fetch_settled_packs ──► CAS claim anchor: NULL/pending → drafting
        │ (outside DB session, ADR-5)
        ├─ live pack thread fetch (history + "seller already replied?" guard)
        ├─ embed_query (gated, off in A)
        └─ RotatingProvider.complete ─► parse_llm_output {answer,category,confidence,can_answer}
        ▼
    classify: claim/moderated → blocked_claim (no draft)
              else            → awaiting_human (+ draft, shaped)
        ▼
    FE Mensajes (thread-header actions) ── take-over → edit → send*
        └─ send* only if messages_send_enabled + live-verified → ml_client.send_message → sent
    (* Phase A: human-initiated only, never automatic)

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/alembic/versions/YYYYMMDD_ml_bot_messages_bot_columns.py` | Create | Add nullable `bot_status`, `drafted_answer`, `intent_category`, `confidence`, `answer_source`, `llm_provider`, `attempts`(default 0), `last_error`, `drafted_at`, `bot_updated_at`(onupdate); partial index on `bot_status`. Dialect-guard partial-index like the pgvector migration test. |
| `backend/app/models/ml_bot_message.py` | Modify | Add the columns above; document the `bot_status` state machine. |
| `backend/app/services/ml_messages/context_builder.py` | Create | Thread-scoped `ScopedContext`: aggregated delimited buyer turn + live conversation history + order/item attrs; reuse `policy` denylist + tag-neutralization + `answer_shaping`. |
| `backend/app/services/ml_messages/drafting_service.py` | Create | `run_ml_messages_draft_cycle`: settle/aggregate → claim → classify → `awaiting_human`/`blocked_claim`/`failed`; stale-`drafting` reclaim; per-pack error isolation. |
| `backend/app/services/ml_api_client.py` | Modify | Add `send_message(...)` (+`MessageSendPermanentError`), mirroring `post_answer`. |
| `backend/app/main.py` | Modify | Wire `ml_messages_draft_task` (warm-up ~120s), interval `poll_interval_seconds`. |
| `backend/app/routers/ml_bot.py` (or new messages router) | Modify/Create | `take-over` / `answer` / `send-now` endpoints for a message anchor; `send-now` fail-closed on the gate. |
| `frontend/src/pages/MLQuestions.jsx` | Modify | Thread-header actions (take-over/edit/send), reuse Preguntas edit modal, detail spoiler (thread + draft + ML link + category/confidence badges). |

## Interfaces / Contracts

State machine (`bot_status`, anchor only; CAS with explicit WHERE on current state):

    (NULL|pending) → drafting → { awaiting_human | blocked_claim | failed }
    drafting → pending          (bounded retry / stale-claim reclaim)
    awaiting_human → superseded  (newer buyer message arrives)
    awaiting_human|blocked_claim → taken_over → { sent | failed }
    failed → pending             (manual retry)

`sent` reachable in Phase A ONLY via human send, ONLY when `messages_send_enabled` + live-verified.

ML conversation URL (FE link): recommend `https://www.mercadolibre.com.ar/mensajes/{pack_id}` — **must be verified against a real pack before FE ships**; fallback = ML seller-hub order link.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | settle window (settled/not, burst re-open, seller-replied skip), aggregation grouping | pytest, frozen `now`, fixture rows |
| Unit | classification/draft, claim-block (no draft), denylist/manipulation reuse | monkeypatch `provider.complete` + `embed_query` |
| Unit | state-machine CAS transitions, idempotency, stale-`drafting` reclaim | in-memory sqlite session |
| Migration | columns + partial index apply; sqlite CI dialect-guard | `skipif`-gated like `test_ml_bot_answer_history_migration` |
| FE | thread actions, gate-disabled send, claim badge; edit modal reuse | vitest + **mandatory headless-Chromium check** |
| Manual | ML `send_message` live-verify | user-owned real ML POST (hard gate, not automated) |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, or executable-file classification. The one external-write boundary (ML `send_message`) carries its own dedicated safety controls documented above: default-off `messages_send_enabled` config gate, mandatory user-owned live-verify prerequisite, fail-closed BE (409) and disabled FE while ungated, and claim/moderation hard-block.

## Migration / Rollout

Additive nullable columns + one partial index; down-migration drops them. Draft task is opt-in wiring — not scheduling it leaves Mensajes read-only. Ingestion and Preguntas untouched. Send stays config-off until live-verified.

## Open Questions

- [ ] ML post-sale conversation URL format (verify `.../mensajes/{pack_id}` on a real pack).
- [ ] `send_message` exact success/error body shape + "already sent" idempotency signal — resolve during live-verify.
- [ ] Confirm the Mensajes table's TanStack resize model (#960) — hang actions inside the thread-header `colSpan` cell to avoid touching the resizable `<colgroup>`.

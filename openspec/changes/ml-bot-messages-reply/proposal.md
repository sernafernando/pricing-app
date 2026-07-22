# Proposal: ML Bot Mensajes — intent-classified post-sale assistant

## Intent

The Mensajes (post-sale) tab is read-only (ingest-only). Turn it into an intelligent assistant that **classifies buyer intent** and routes each conversation by a **per-category policy**: safe categories can auto-respond, back-office categories derive to an admin queue with a templated ack, claims are hard-blocked, and everything else falls to a human. Value: cut post-sale reply time while respecting ML's private-conversation policy and never auto-answering risky messages.

## Scope

### In Scope
- `bot_status` + draft/classification columns on `ml_bot_messages` (migration); NEW `ml_bot_admin_pending` table.
- Per-conversation aggregation + settle/debounce: fragmented bursts → one input → one draft.
- Thread-scoped context builder + intent classification (LLM, provider rotation) + embedder few-shot, reusing the Preguntas pipeline + guardrails.
- Category-policy router (AUTO-RESPOND allowlist / DERIVE-TO-ADMIN / BLOCKED / DEFAULT→human).
- Admin-pending subsystem + admin screen to process derived requests.
- FE Mensajes actions (human take-over/edit/send, always available) + detail spoiler (thread + draft + ML conversation link).
- Live-verified ML send endpoint (hard prerequisite before any send ships).

### Out of Scope
- Open-ended auto-reply (only allowlisted categories ever auto-send).
- Auto-responding to claims/reclamos (hard blocked).
- Reply attachments (text-only MVP); rate-limit tuning (follow-up); Preguntas flow changes.

## Capabilities

### New Capabilities
- `ml-bot-messages-reply`: intent classification + per-category policy routing (auto-respond allowlist, admin-derive, claim block, human default), aggregation/debounce, embedder few-shot, admin-pending queue, live-verified ML send.

### Modified Capabilities
- None.

## Approach

Mirror the Preguntas pipeline (CAS state machine, provider rotation, denylist/deflection/manipulation guardrails, ADR-5 sessions, SSE, tone-only few-shot). Add: **thread-scoped** context, **debounce** aggregation, an **intent classifier** feeding a **category-policy router**. The router — not a global toggle — decides the lane: AUTO-RESPOND only when category ∈ allowlist AND confidence passes the gate; DERIVE creates an `ml_bot_admin_pending` row **and** sends a safe templated ack; BLOCKED (claims, via ML claim context/moderation signal) never auto-sends; DEFAULT/low-confidence/unknown → human. Human take-over/edit/send stays available for every message. `bot_status` is a NEW column — never repurpose ML's raw `status` (collision).

## Category Policy

| Lane | Categories (initial) | Bot action |
|------|----------------------|------------|
| AUTO-RESPOND | shipping status, invoice-change ack | Send draft directly (allowlist + confidence gate) |
| DERIVE-TO-ADMIN | invoice change, CUIT change | Create admin-pending row + send templated ack |
| BLOCKED | claims/reclamos | Never auto-send; route to human |
| DEFAULT | low-confidence / unknown | Human queue only |

## State Machine

`ingested → drafting → classified → drafted → {auto_sent | derived | taken_over → sent | blocked | failed}`; `failed → drafting` (manual retry). Each transition = one CAS UPDATE on current `bot_status`. Auto-send lane only reachable in Phase C behind config.

## Business Rules & Edge Cases

- **Burst aggregation**: draft only after settle window with no newer buyer message; combine all unanswered buyer turns in the pack; new message mid/after-draft re-opens aggregation.
- **status vs bot_status split**: ML status untouched; bot lifecycle isolated.
- **Claims block**: never auto-send; also disabled in human-send UI unless explicitly overridden; detection via ML claim context/moderation (design resolves).
- **Confidence gate**: auto-send requires allowlisted category AND valid/confident draft; else → human.
- **Tone-only guardrail**: facts from context, never few-shot; never reveal exact price/stock/address; buyer text as data.
- **DERIVE ack**: templated, safe ("se realizará el cambio a la brevedad"); admin row is the source of truth for the action.
- **ML conversation link**: verify real URL format before FE ships. Cold-start empty corpus → static few-shot, still gated.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| **Send endpoint unverified** (WebSearch-only) | High | HARD live-verify gate before ANY send ships (Phase C); corroborated by existing GET |
| Auto-sending to real buyers | High | Safe-first phasing (A/B human-only), allowlist + confidence gate, claims hard-blocked, config-gated Phase C |
| ML messaging policy / rate limits | Med | Human-gated by default; allowlist narrow; rate-limit tuning deferred |
| Misclassification (intent → wrong lane) | Med | DEFAULT falls to human; only narrow allowlist auto-sends; claims blocked independently |
| `status`/`bot_status` collision | Med | Separate column, never repurpose `status` |

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/models/ml_bot_message.py` + migration | Modified | `bot_status`, `drafted_answer`, `category`, `confidence`, `answer_source`, `llm_provider`, `attempts`, `last_error`, `replied_at` |
| `backend/app/models/ml_bot_admin_pending.py` + migration | New | message/pack ref, type, buyer, payload, status (new/processing/done), timestamps |
| `backend/app/services/ml_messages/` | New | thread context, classifier, policy router, draft cycle, admin-derive, send publisher |
| `backend/app/main.py` | Modified | `ml_messages_draft_task` wiring |
| `backend/app/routers/seriales_messages.py` (+ admin router) | Modified/New | take-over/send + admin-pending endpoints |
| `frontend/src/pages/MLQuestions.jsx` + admin screen | Modified/New | Mensajes actions + detail spoiler + ML link; admin-pending screen |

## Phased Delivery (safe-first)

- **Phase A (foundation, no auto-send)**: BE draft + `bot_status` migration + thread context + aggregation/debounce + embedder few-shot + intent classification (classify + store, do NOT act). FE Mensajes actions (human take-over/edit/send) + detail spoiler. Every reply human-sent; claims flagged/blocked in UI.
- **Phase B (admin routing)**: `ml_bot_admin_pending` table + admin screen; DERIVE categories create pending rows; still human-confirmed replies.
- **Phase C (conditional auto-send)**: enable AUTO-RESPOND for allowlisted categories with confidence gate, behind config, AFTER endpoint live-verified and A/B proven. Claims stay hard-blocked.

Keep PRs reviewable within each phase.

## Rollback Plan

Additive; revert per PR/phase. Migrations add nullable columns / a new table → down-migrations drop them; ingestion and Preguntas unaffected. Draft task is opt-in wiring; disabling reverts Mensajes to read-only. Auto-send is config-gated → flip off to fall back to human-only without a deploy.

## Dependencies

- `sdd/ml-bot-dynamic-fewshot` embedder pipeline (LAN TEI).
- Live-verified ML send endpoint (`POST /messages/packs/{pack_id}/sellers/{seller_id}?tag=post_sale`) — hard prerequisite for any send.
- ML claim-context / moderation signal for claim detection (design resolves).

## Success Criteria

- [ ] One draft per fragmented buyer burst after the settle window; each conversation gets a stored intent category.
- [ ] No message reaches a buyer in Phase A/B without explicit human send; claims never auto-send in any phase.
- [ ] DERIVE categories create an admin-pending row + send a safe templated ack.
- [ ] Detail spoiler shows full thread + draft + working ML link.
- [ ] Auto-send (Phase C) only fires for allowlisted categories past the confidence gate, behind config, on a live-verified endpoint.
- [ ] `status` semantics unchanged; migrations reversible.

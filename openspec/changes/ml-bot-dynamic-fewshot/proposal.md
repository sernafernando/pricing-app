# Proposal: Dynamic Similarity-Selected Few-Shot for the ML Answer Bot

> Change: `ml-bot-dynamic-fewshot`
> Capture human-approved published answers and, per new buyer question, retrieve
> the most SEMANTICALLY SIMILAR past answers as dynamic few-shot examples — so
> "when the bot answered well, next time it answers similarly." Retrieval-only
> half of an Agent-in-the-Loop data flywheel (ref: arXiv 2510.06674). Explicitly
> NO model fine-tuning.

## Intent

Today the bot's few-shot examples are static: `context_builder.load_few_shot_examples()`
returns the top-10 rows of `ml_bot_answer_examples` ordered by a fixed `orden`
column, feeding the `EJEMPLOS_DE_TONO` block as TONE reference only. Operators
regularly take over, edit, and publish a better answer — that human-approved
answer is stored on `ml_bot_questions` and then effectively thrown away as
learning signal. There is no feedback loop: a great human answer never improves
the next draft.

We want the cheap, retrieval-only flywheel: capture every human-approved
published answer, embed it, and select tone examples by semantic similarity to
the incoming question instead of a fixed order. Success = drafts drift toward the
style of past answers that operators actually approved, with zero fine-tuning,
zero external API cost, and no weakening of the existing data-scoping guardrail.

## Why now

The capture point already exists (the gold tuple is fully present on the row when
status flips to `published`), the retrieval seam already exists (one function,
one return shape), and the corpus grows for free from normal operator work. The
only genuinely new infra is a vector column + a LAN embedding call — both boring
and self-hosted.

## Scope

### In Scope
- **Capture hook** at the terminal publish success in `publisher_service.py`
  (where `row.status = "published"` is set). Capture `(question_text,
  drafted_answer [= published text], item_id, edited_flag)`; `edited_flag` derives
  from `answer_source == "human"` (edited) vs `"bot"` (accepted as-is).
- **New table `ml_bot_answer_history`** (separate trust class from the
  admin-curated `ml_bot_answer_examples`): `question_text`, `answer_text`,
  `item_id`, `edited_flag` (bool), `category` (nullable), `embedding vector(384)`,
  `active` (bool, manual pruning), `created_at`; HNSW vector index.
- **Pluggable `embed()` seam** calling a self-hosted HTTP embedding service on the
  LAN (HuggingFace TEI serving `intfloat/multilingual-e5-small`, 384 dims). The
  HTTP call happens OUTSIDE any DB session (ADR-2/ADR-5, same discipline as the
  existing LLM calls). e5 task prefixes applied consistently: `"query: "` for the
  incoming question, `"passage: "` for stored questions/answers.
- **Similarity retrieval** in `context_builder.load_few_shot_examples()`: replace
  the static `orden` query with a top-k vector-similarity query over
  `ml_bot_answer_history`, returning the SAME `List[FewShotExample]` shape feeding
  the SAME `EJEMPLOS_DE_TONO` block. `k` and similarity threshold are tunable via
  `ml_bot_config` (like other bot knobs).
- **Cold-start / fallback**: empty corpus, embedder unreachable, or retrieval
  error → fall back to the current static top-10-by-`orden` path. Never break
  drafting.
- **Auto-capture policy** (mark for review): auto-capture every edited-and-
  published answer, with the `active` flag for cheap manual pruning.

### Out of Scope (explicit non-goals)
- Model fine-tuning (generator OR embedder).
- Two-candidate preference UI; re-ranker; separate knowledge base.
- Cross-device / global corpus sync.
- LLM-judge corpus quality filter (deferred, MVP non-goal).
- Any change to the admin-curated `ml_bot_answer_examples` behavior.
- Backfill of existing published rows — proposed only as an OPTIONAL follow-up
  slice (see Dependencies), not part of the MVP.

## Capabilities

### New Capabilities
- `ml-bot-answer-history-capture`: persist human-approved published answers into a
  new embedded history corpus at the terminal publish success, with an `active`
  pruning flag and `edited_flag` provenance.
- `ml-bot-dynamic-fewshot-retrieval`: select few-shot tone examples by semantic
  similarity (pluggable embedder + pgvector top-k), with cold-start/error fallback
  to the existing static path and a hard tone-only data-scoping guardrail.

### Modified Capabilities
- None at the spec level in `openspec/specs/`. The existing few-shot loading
  behavior (ordering strategy inside `load_few_shot_examples`) changes, but the
  return shape, prompt template, and `EJEMPLOS_DE_TONO` labeling are unchanged;
  the guardrail boundary is preserved verbatim.

## Approach

Retrieval-only flywheel over the existing seams. Rationale vs alternatives:

- **Self-hosted TEI (chosen) vs paid embeddings API vs MiniMax/hosted model.**
  Cost was the deciding factor: self-hosted TEI on the LAN is FREE, needs no GPU,
  no external API key, and no per-token billing. A paid API (e.g. OpenAI
  `text-embedding-3-small`) is cheap but adds an external dependency and recurring
  cost for a high-frequency hot-path call. The `embed()` seam keeps the provider
  swappable later without touching retrieval logic.
- **New `ml_bot_answer_history` table (chosen) vs reusing
  `ml_bot_answer_examples`.** The examples table is admin-curated and TRUSTED BY
  DESIGN (panel-edited under the `ml_bot.config` permission). Auto-captured bot/
  human answers are a DIFFERENT trust class and must not silently mix into the
  curated seed; a separate table keeps the trust boundary and pruning independent.
- **Retrieval-only (chosen) vs fine-tuning.** Fine-tuning is the expensive,
  slow-feedback half of the flywheel and out of scope; retrieval delivers most of
  the "answer like last time" benefit at near-zero cost and is instantly
  revertible.

### Hard data-scoping guardrail (non-negotiable)
Retrieved examples are TONE/STYLE only; facts come ONLY from the current listing's
scoped context. System-prompt rule 1 ("answer only from CONTEXTO_PERMITIDO") is
NOT weakened. A past answer's facts (price/stock/compatibility of a DIFFERENT
item) must never leak into the current answer. The spec MUST include an explicit
test asserting example content never becomes a fact source.

### Business rules / edge cases
- **Prefix consistency**: `"query: "` on retrieval input, `"passage: "` on stored
  text — a mismatch silently degrades similarity quality.
- **Dimension consistency**: every stored + query embedding is 384-dim; a provider
  swap that changes dimensionality requires a re-embed/migration, not a silent
  mix.
- **Cold start**: corpus starts at zero rows → similarity query returns empty →
  fall back to static path.
- **Embedder down / error**: never block drafting; fall back to static path and
  log.
- **Capture policy**: auto-capture folds into normal operator work; `active` flag
  enables cheap manual pruning of bad examples. LLM-judge filtering deferred.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/alembic/versions/{date}_ml_bot_answer_history.py` (new) | New | `CREATE EXTENSION vector` (prerequisite, see Dependencies) + new table + HNSW index |
| `backend/app/models/ml_bot_answer_history.py` (new) | New | ORM model with `vector(384)` column, `edited_flag`, `active` |
| `backend/app/services/ml_questions/publisher_service.py` | Modified | Capture hook at terminal publish success (`status="published"`), OUTSIDE the DB session for the embed call |
| `backend/app/services/ml_questions/context_builder.py` | Modified | `load_few_shot_examples()` swaps static `orden` query for top-k similarity + fallback |
| `backend/app/services/ml_questions/` (new embedder client) | New | Pluggable `embed()` seam → self-hosted TEI over HTTP, e5 prefixes |
| `ml_bot_config` (data) | Modified | New tunable keys: retrieval `k`, similarity threshold, embedder URL/enable flag |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| **pgvector NOT installed in this Postgres** — needs `CREATE EXTENSION vector` (superuser/hosting permission) | High | BLOCKING PREREQUISITE — confirm hosting permits extension creation BEFORE apply; see Dependencies |
| Embedder is a new network dependency on the hot drafting path | Med | Call OUTSIDE DB session (ADR-5); timeout + fallback to static path; never block drafting |
| Spanish (rioplatense) embedding quality of multilingual-e5-small | Med | e5 is multilingual-trained; `embed()` seam allows swapping to a stronger model later without touching retrieval |
| Hot-path latency added per draft | Med | Single small model on LAN, no GPU; tune `k`; short timeout with fallback |
| Corpus quality drift (bad answers captured) | Med | `active` pruning flag; LLM-judge filter deferred as a known follow-up |
| Fact leakage from example content | Low | Tone-only labeling preserved; explicit guardrail test; prompt rule 1 untouched |

## Rollback Plan

Additive and isolated. To revert: turn off the embedder-enable config key →
retrieval falls back to the static `orden` path immediately (no deploy needed).
Full revert: restore the static `load_few_shot_examples` body, remove the capture
hook, `alembic downgrade -1` (drops `ml_bot_answer_history` and, if desired, the
extension). The static few-shot path is always present as the fallback, so a
failed embedder or empty corpus cannot regress drafting.

## Dependencies

- **BLOCKING: pgvector**. `CREATE EXTENSION vector` requires superuser/hosting
  permission — must be CONFIRMED available on the current Postgres before apply.
  This is the one gating prerequisite.
- **Self-hosted TEI embedding service** reachable on the LAN, serving
  `intfloat/multilingual-e5-small` (384 dims).
- Existing `ml_bot_config` mechanism for tunable bot knobs.
- **Optional follow-up slice (not MVP)**: one-off backfill embedding existing
  published `MlBotQuestion` rows to seed the corpus — estimate bulk-embedding
  cost/latency up front before committing.

## Open Questions to Confirm (product/decision review)

1. **pgvector availability** on the production Postgres host (blocking).
2. **Auto-capture policy**: confirm auto-capturing EVERY edited-and-published
   answer (with `active` pruning) is acceptable, vs a lighter opt-in, for the MVP.

## Success Criteria

- [ ] A human-approved published answer is captured into `ml_bot_answer_history`
      with its embedding at publish success.
- [ ] A new question retrieves top-k semantically similar past answers as tone
      examples, feeding the unchanged `EJEMPLOS_DE_TONO` block.
- [ ] Empty corpus / embedder-down / retrieval error falls back to the static
      top-10-by-`orden` path; drafting never breaks.
- [ ] Guardrail test proves example content never becomes a fact source; prompt
      rule 1 is unchanged.
- [ ] `k` and similarity threshold are tunable via `ml_bot_config`.
- [ ] `ml_bot_answer_examples` behavior is untouched.

## Next Phase

`sdd-spec` and `sdd-design` (can run in parallel). Spec formalizes capture,
retrieval, fallback, prefix/dimension rules, and the tone-only guardrail
(including the explicit no-fact-leak test). Design decides the embedder client
shape and `embed()` seam contract, the HNSW index parameters, the exact capture
side-effect placement relative to the terminal write, and confirms the pgvector
prerequisite.

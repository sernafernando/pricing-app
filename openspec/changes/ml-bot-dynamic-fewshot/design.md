# Design: Dynamic Similarity-Selected Few-Shot for the ML Answer Bot

## Technical Approach

Retrieval-only flywheel bolted onto three existing seams, reusing the codebase's
established discipline verbatim: every external HTTP call happens OUTSIDE any DB
session (ADR-5, mirrors `ml_client.get_item_description` and the LLM provider
calls); every `ml_bot_config` read goes through `policy.get_config` with fail-safe
casting; the retrieval return shape (`List[FewShotExample]`) and the
`EJEMPLOS_DE_TONO` prompt block are unchanged, so the tone-only guardrail holds by
construction. One new client, one new model, one migration; two modified services.

## Architecture Decisions

### Decision: `embed()` client seam
**Choice**: New `embedding_client.py` with an `EmbeddingProvider` Protocol and a
`TEIEmbeddingProvider` impl over `httpx.AsyncClient`, mirroring
`OpenAICompatProvider` (retry on 5xx/timeout, error contract, no DB access). Public
async functions: `embed_query(text) -> Optional[list[float]]` and
`embed_passage(text) -> Optional[list[float]]` (single) plus
`embed_passages(texts) -> Optional[list[list[float]]]` (batch). The CLIENT owns the
e5 prefix (`"query: "` / `"passage: "`) so callers can never mismatch it, and owns
defensive truncation to the 512-token limit (char-budget heuristic, ~2000 chars,
then let TEI truncate). Base URL from `ml_bot_config.embedder_url` (default
`http://192.168.1.231:8080`), route `POST /v1/embeddings`, model
`intfloat/multilingual-e5-small`, no auth, short timeout (`5.0s`).
**Alternatives**: caller-applied prefixes (rejected — the exact silent-degradation
bug the proposal warns about); raise-on-failure (rejected — callers want a `None`
fallback signal, not an exception on the hot path).
**Rationale**: Protocol keeps the provider swappable (proposal requirement) without
touching retrieval; returning `Optional` makes cold-start/error fallback a plain
`is None` check. Failure (timeout, 5xx-after-retries, malformed body, dim != 384)
returns `None`, logged.

### Decision: `ml_bot_answer_history` model + migration
**Choice**: New table, separate trust class from `ml_bot_answer_examples`. Columns:
`id`, `question_text` (Text), `answer_text` (Text), `item_id` (String(32)),
`edited_flag` (Bool), `category` (String(40), nullable), `embedding Vector(384)`
NOT NULL, `active` (Bool, default true), `created_at`. Use the `pgvector` Python
package (`from pgvector.sqlalchemy import Vector`; add `pgvector` to
`requirements.txt`). Migration `YYYYMMDD_ml_bot_answer_history.py`:
`op.execute("CREATE EXTENSION IF NOT EXISTS vector")` first, then table, then
`op.execute` an HNSW index with `vector_cosine_ops`, `m=16, ef_construction=64`.
**Alternatives**: IVFFlat (rejected — needs a trained/populated corpus and a `lists`
tuned to size; bad for a corpus starting at zero). Nullable embedding + backfill
(rejected — out of MVP scope; a NULL-embedding row is dead weight).
**Rationale**: HNSW needs no training and performs well from the first row; `m=16 /
ef_construction=64` are the pgvector defaults, ample for a small/slow-growing
corpus (query-time recall tunable later via `hnsw.ef_search`). `CREATE EXTENSION`
needs DB superuser/owner privilege — the **blocking prerequisite**; confirm before
apply.

### Decision: Capture side-effect placement
**Choice**: In `publisher_service._publish_one`, on the genuine post-success path
only (after `result is not None` → `_mark_published`). Add
`await _capture_answer_history(question_id)`: load the row's plain fields in a short
session, `await embed_passage("passage: " + answer_text)` with NO session open, then
INSERT in a second short session. Whole call wrapped in `try/except Exception` →
log-and-swallow. `edited_flag = (answer_source == "human")`. If embed returns
`None`, SKIP capture (no row inserted).
**Alternatives**: capture inside `_mark_published` (rejected — also fires on the
already-answered idempotency path where our draft was not the posted text);
store-with-NULL-embedding (rejected — un-retrievable dead row).
**Rationale**: A failed embed must never fail a publish (best-effort). NOT NULL
embedding keeps retrieval simple; a missed capture is self-healing (the corpus grows
from the next success).

### Decision: Retrieval query + fallback
**Choice**: `load_few_shot_examples(db, limit, question_embedding=None)`. The query
embedding is computed by `drafting_service` OUTSIDE the session (like
`get_item_description`) and threaded through `build_scoped_context(...,
question_embedding=...)`. If `question_embedding is None` (embedder disabled or
failed) → static `orden` path unchanged. Else run pgvector cosine query:
`ORDER BY embedding <=> :qvec LIMIT :k` filtered `active = true`, keeping only rows
within the similarity threshold; empty result → static fallback.
**Alternatives**: L2 `<->` (rejected — e5 outputs are cosine-normalized; cosine
`<=>` is the correct metric).
**Rationale**: One extra param, zero change to the return shape or prompt. Three
independent fallbacks (disabled flag, embedder error → `None`, empty result) all
converge on the existing static path — drafting never breaks.

### Decision: Config keys (`ml_bot_config`, via `policy.get_config`)
| Key | Cast | Default | Purpose |
|-----|------|---------|---------|
| `fewshot_dynamic_enabled` | bool | `false` | master enable (off → static path, instant rollback) |
| `embedder_url` | str | `http://192.168.1.231:8080` | TEI base URL |
| `fewshot_retrieval_k` | int | `10` | top-k, clamped `[1, 20]` |
| `fewshot_similarity_threshold` | float | `0.0` | min cosine similarity (permissive default) |
| `fewshot_capture_enabled` | bool | `false` | capture hook enable |
All parsed with the fail-safe malformed→default convention of
`get_description_max_chars`. Enable flags default `false` → additive, dark-launch.

## Data Flow

    publish success ─► embed_passage(answer) [no session] ─► INSERT history row
    new question ─► embed_query(question) [no session] ─► build_scoped_context(db, …, qvec)
                                                            └► load_few_shot_examples
                                                                 ├─ qvec present ─► cosine top-k (active) ─┐
                                                                 └─ None/empty ───► static orden path ─────┤
                                                                                    FewShotExample[] ──────► EJEMPLOS_DE_TONO

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/services/ml_questions/embedding_client.py` | Create | `EmbeddingProvider` Protocol + TEI impl, e5 prefixes, truncation, `Optional` return |
| `backend/app/models/ml_bot_answer_history.py` | Create | ORM model, `Vector(384)` NOT NULL, `edited_flag`, `active` |
| `backend/alembic/versions/YYYYMMDD_ml_bot_answer_history.py` | Create | `CREATE EXTENSION vector` + table + HNSW cosine index |
| `backend/app/services/ml_questions/context_builder.py` | Modify | `load_few_shot_examples` + `build_scoped_context` accept optional `question_embedding`; cosine query + fallback |
| `backend/app/services/ml_questions/publisher_service.py` | Modify | best-effort `_capture_answer_history` on post-success |
| `backend/app/services/ml_questions/drafting_service.py` | Modify | embed query outside session, pass into `build_scoped_context` |
| `backend/requirements.txt` | Modify | add `pgvector` |

## Interfaces / Contracts

    async def embed_query(text: str) -> Optional[list[float]]   # applies "query: "
    async def embed_passage(text: str) -> Optional[list[float]] # applies "passage: "
    async def embed_passages(texts: list[str]) -> Optional[list[list[float]]]
    def load_few_shot_examples(db, limit=10, question_embedding: Optional[list[float]] = None) -> List[FewShotExample]

## Guardrail

Tone-only boundary holds by construction: retrieved rows populate the SAME
`few_shot_examples` field feeding `_few_shot_to_text` → `EJEMPLOS_DE_TONO`; the
`EJEMPLOS_DE_TONO` label and system-prompt rule 1 ("answer only from
CONTEXTO_PERMITIDO") are untouched. `_context_to_json` never reads
`few_shot_examples`, so example text can never enter `CONTEXTO_PERMITIDO`. Required
test asserts a retrieved example carrying a foreign price/address never appears in
the `context_json` half of `build_prompt`'s output.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | embedding_client | mock `httpx`; assert `"query: "`/`"passage: "` prefix, >512-token truncation, batch shape, timeout/5xx/dim-mismatch → `None` |
| Unit | capture best-effort | monkeypatch `embed_passage` to raise/return `None`; assert publish outcome still `published`, no exception, `edited_flag` from `answer_source` |
| Unit | retrieval | monkeypatch embedder; assert cosine ordering, `active=true` filter, `question_embedding=None` → static path, empty result → static path |
| Unit | guardrail | retrieved example with foreign fact never reaches `context_json` |
| Integration | pgvector query | real Postgres (`<=>`, HNSW) — **skip on sqlite CI** |

**CI note**: project CI runs backend tests on sqlite (`DATABASE_URL`); the
`Vector` column type and `<=>` operator are Postgres-only. Guard pgvector-dependent
tests with `@pytest.mark.skipif` on backend dialect (or a `postgres` marker) and
keep all retrieval/capture logic unit-tested via a monkeypatched embedder and a
faked query layer so coverage does not depend on a live Postgres. Run `ruff format`
+ `ruff check` before push (CI "Backend Lint").

## Threat Matrix

N/A — no shell, subprocess, routing, VCS/PR automation, or executable-file
classification. The one new boundary is a LAN HTTP call whose URL is sourced from
`ml_bot_config` (admin-only `ml_bot.config` trust class, same as existing embedder/
provider config); no untrusted input reaches the URL.

## Migration / Rollout

Additive, dark-launched behind `fewshot_dynamic_enabled` / `fewshot_capture_enabled`
(both default `false`). Rollout: apply migration (needs `CREATE EXTENSION`
privilege) → enable capture to grow the corpus → enable retrieval. Rollback: flip
`fewshot_dynamic_enabled` off (instant, no deploy); full revert `alembic downgrade
-1`.

## Open Questions

- [ ] pgvector `CREATE EXTENSION` privilege confirmed on production Postgres (BLOCKING).
- [ ] Auto-capture-every-published-answer policy accepted for MVP (vs opt-in).

# STATUS — ml-bot-dynamic-fewshot (recovery doc)

_Last updated: 2026-07-20. Written so this can be picked up from another machine._

## TL;DR
Planning is **COMPLETE** (proposal → spec → design → tasks, all in this folder + engram).
Implementation (`sdd-apply`) has **NOT started**. It is blocked on **one prerequisite** and
**two open decisions** (below). The embedding service it depends on is already **deployed and verified**.

## What this feature is
Turn the ML answer-bot's static tone few-shot into **dynamic, similarity-selected** few-shot fed
by human-approved answers. On publish of a taken-over/edited answer, capture
`(question, published answer, item_id, edited_flag)` + a 384-dim embedding into a new
`ml_bot_answer_history` table. Per new buyer question, retrieve the top-k most semantically
similar past answers as the few-shot tone block (replacing static top-10 by `orden`).
Retrieval-only — **no fine-tuning**. Ref: arXiv 2510.06674 (Agent-in-the-Loop flywheel), the
cheap retrieval half.

**Hard guardrail (non-negotiable):** retrieved examples are TONE/STYLE only. Facts still come
ONLY from the current listing's scoped context (`CONTEXTO_PERMITIDO`, prompt rule 1 unchanged).
A past answer's facts (price/stock/compatibility of a *different* item) must never leak.

## Artifacts (this folder + engram topic keys under project "pricing-app")
- `proposal.md` — `sdd/ml-bot-dynamic-fewshot/proposal`
- `specs/ml-bot-dynamic-fewshot/spec.md` — `sdd/ml-bot-dynamic-fewshot/spec` (4 reqs, 15 scenarios)
- `design.md` — `sdd/ml-bot-dynamic-fewshot/design`
- `tasks.md` — `sdd/ml-bot-dynamic-fewshot/tasks` (20 TDD tasks)
- exploration — `sdd/ml-bot-dynamic-fewshot/explore`

## Embedding service — DONE + verified (infra memory: `infra/ml-bot-embedding-service`)
- **LXC 103 "embeddings" on host `xenon`** (Debian 13, unprivileged, 4c/4GB, autostarts). TEI in Docker.
- **Base URL `http://192.168.1.231:8080`**, route `POST /v1/embeddings` (OpenAI-compatible).
- Model `intfloat/multilingual-e5-small`, **384 dims**, no auth (LAN-only), **512-token input limit**.
- Request: `{"model":"intfloat/multilingual-e5-small","input":"query: <text>"}` (`input` accepts array).
- **e5 prefixes (caller applies): `"query: "` for search input, `"passage: "` for indexed text.**
- Ops: `pct exec 103 -- docker restart tei-embeddings` from xenon; README at `/root/EMBEDDINGS-README.md` in the LXC.
- Gotcha: TEI image `cpu-1.5` is BROKEN vs current HF Hub — **pinned `cpu-1.8` (never < 1.6)**.

## BLOCKER before apply (hard gate — task 0)
**pgvector is NOT installed in the app's Postgres.** The migration does `CREATE EXTENSION vector`,
which needs DB superuser/owner privilege. **Confirm the Postgres host allows it before any migration.**
Quick check: `psql <db> -c "CREATE EXTENSION IF NOT EXISTS vector;"` (or ask the hosting provider).

## Open decisions to confirm on return
1. **Capture policy:** auto-capture EVERY edited-and-published answer (recommended, with an `active`
   flag for manual pruning) vs a lighter opt-in. Design assumes auto-capture, dark-launched behind
   a config flag defaulting to `false`.
2. **PR split:** the tasks forecast is ~800–1050 lines (incl. tests), over the 400-line budget →
   **3 chained PRs recommended:**
   - PR1 — migration + `ml_bot_answer_history` model + `embedding_client.py` (tasks 0–3). Foundational, no behavior change. Needs pgvector confirmed to merge.
   - PR2 — capture at publish (task 4) + config keys (task 6). Dark-launched (`fewshot_capture_enabled=false`).
   - PR3 — retrieval in `context_builder` (task 5) + guardrail test (task 7) + CI doc (task 8). Dark-launched (`fewshot_dynamic_enabled=false`).

## Key design decisions (see design.md for full rationale)
- New module `backend/app/services/ml_questions/embedding_client.py`: `embed_query` / `embed_passage`
  / `embed_passages` → `Optional[...]`; client owns e5 prefixes + 512-token truncation; URL from
  `ml_bot_config`; 5s timeout; failure → `None`; called OUTSIDE any DB session (ADR-2/ADR-5).
- New model + migration: `Vector(384)` NOT NULL (`pgvector` package); migration `CREATE EXTENSION vector`
  then HNSW `vector_cosine_ops` (m=16, ef_construction=64); add `pgvector` to `requirements.txt`.
- Capture in `publisher_service.py` at the genuine post-success path only, **best-effort** (try/except):
  a failed embed **skips capture** (no NULL-embedding dead rows), never fails the publish.
- Retrieval in `context_builder.load_few_shot_examples()`: cosine `<=>` top-k over `active=true`,
  k + threshold from `ml_bot_config`; query embedding computed outside the session and passed in;
  triple fallback (disabled flag / empty corpus / any error → static `orden` path). Same
  `List[FewShotExample]` return shape, same `EJEMPLOS_DE_TONO` block.
- Config keys (`ml_bot_config`, fail-safe parsing, enable flags default `false` = dark launch):
  embedder_url, dynamic-fewshot enable, capture enable, retrieval `k`, similarity threshold.
- **CI gap:** pgvector `<=>`/HNSW can't run on the sqlite CI backend → Postgres-dependent tests are
  skip-marked; ordering/index behavior validated in unit tests via a faked query layer + must be
  checked on a real Postgres before merge.

## How to resume (from home)
1. `git fetch && git checkout feat/ml-bot-dynamic-fewshot` (this branch has all the planning docs).
2. Confirm pgvector (`CREATE EXTENSION vector`) on the target Postgres — the hard gate.
3. Decide capture policy + PR split (above).
4. Run `sdd-apply` for PR1 (Strict TDD, pytest test-first). Then PR2, PR3.
5. Strict TDD is ON: test runner `pytest tests/ -v` (env `ENVIRONMENT=testing`, sqlite `DATABASE_URL`);
   run `ruff format app/` + `ruff check app/` before every backend push (CI-enforced).

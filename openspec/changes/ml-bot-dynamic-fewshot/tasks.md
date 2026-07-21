# Tasks — ml-bot-dynamic-fewshot

Strict TDD: every task below implements RED (failing test first) → GREEN (minimal code) → refactor as needed. No task's code should be written before its test.

## 0. HARD GATE — prerequisite verification (BLOCKS task 1)
- [x] **0.1** Confirm `CREATE EXTENSION vector` privilege is available on the target Postgres instance (superuser/owner grant, or extension pre-installed by DBA). Verify by running `CREATE EXTENSION IF NOT EXISTS vector;` against a non-prod/staging copy of the DB, or obtaining explicit confirmation from whoever administers the prod Postgres instance.
  - Requirement: design ADR-2 (OPEN QUESTIONS — blocking).
  - Done when: written confirmation (or a successful dry-run) exists that the extension can be created on the deploy target. **`sdd-apply` MUST NOT start task 1 until this is confirmed.**
  - Parallel: none (blocks everything downstream).
  - RESOLVED (PR1): pgvector 0.8.0 confirmed installed on `pricing_db`; `CREATE EXTENSION vector` succeeds.

## 1. Dependency + migration
- [x] **1.1** Add `pgvector` to `backend/requirements.txt`.
  - Requirement: spec Assumptions (pgvector prerequisite); design ADR-2.
  - Done when: `pgvector` pinned in requirements.txt, `pip install -r requirements.txt` succeeds locally.
  - Depends on: 0.1.
- [x] **1.2** (TEST FIRST) Write Alembic migration smoke test (or manual upgrade/downgrade check) asserting: `ml_bot_answer_history` table exists with expected columns/types after upgrade, HNSW index exists, `downgrade()` cleanly drops table+index. If CI runs on sqlite, mark this test `@pytest.mark.skipif` on non-Postgres dialect (see task 8) but still write it now.
  - Requirement: spec Requirement 1; design ADR-2.
  - DONE: `tests/unit/test_ml_bot_answer_history_migration.py` — dialect-agnostic revision-graph checks (run on SQLite CI) + a `@pytest.mark.skipif`-gated live-Postgres table/HNSW-index existence check.
- [x] **1.3** Create `backend/alembic/versions/YYYYMMDD_ml_bot_answer_history.py`:
  - `op.execute("CREATE EXTENSION IF NOT EXISTS vector")` first.
  - Create `ml_bot_answer_history` table: `id`, `question_text` (Text), `answer_text` (Text), `item_id` (String(32)), `edited_flag` (Bool), `category` (String(40), nullable), `embedding` (Vector(384), NOT NULL), `active` (Bool, default true), `created_at`.
  - `op.execute` HNSW index, `vector_cosine_ops`, `m=16`, `ef_construction=64`.
  - `downgrade()` drops index then table (extension left in place — do not drop shared extension on downgrade).
  - Requirement: spec Requirement 1; design ADR-2.
  - Done when: task 1.2 test passes against a real Postgres instance; `alembic upgrade head` / `alembic downgrade -1` both clean.
  - Depends on: 1.1, 1.2, 0.1.
  - Parallel: none (foundation for all following tasks).
  - DONE: `alembic/versions/20260721_ml_bot_answer_history.py`, dialect-guarded on `op.get_bind().dialect.name` (Postgres: real extension + vector(384) + HNSW; SQLite: JSON placeholder column, no extension/index DDL — CI never runs this migration against SQLite anyway, kept dialect-safe for local/manual runs).

## 2. ORM model
- [x] **2.1** (TEST FIRST) Unit test for `MlBotAnswerHistory` model: table name, column types (esp. `Vector(384)` via `pgvector.sqlalchemy.Vector`), defaults (`active=True`), required-not-null on `embedding`.
  - Requirement: spec Requirement 1; design ADR-2.
  - DONE: `tests/unit/test_ml_bot_answer_history_model.py`.
- [x] **2.2** Create `backend/app/models/ml_bot_answer_history.py` — SQLAlchemy model matching migration schema exactly, `from pgvector.sqlalchemy import Vector`.
  - Done when: 2.1 passes; model registered/importable from wherever other ml_bot models are declared/imported (mirror existing pattern for `ml_bot_answer_examples`).
  - Depends on: 1.3.
  - Parallel: can run alongside task 3 (independent files).
  - DONE: `app/models/ml_bot_answer_history.py`. Also patched `tests/conftest.py`'s `_PG_TYPE_MAP` (`Vector -> JSON(none_as_null=True)`) so `Base.metadata.create_all` still builds cleanly on the SQLite test DB, mirroring the existing JSONB/UUID remap pattern.

## 3. Embedding client
- [x] **3.1** (TEST FIRST) Tests for `embedding_client.py` using mocked `httpx.AsyncClient`:
  - `embed_query` applies `"query: "` prefix; `embed_passage` applies `"passage: "` prefix.
  - Defensive truncation kicks in above the ~2000-char / 512-token heuristic before the request is sent.
  - Timeout → returns `None`, logged, no raise.
  - 5xx after retries → returns `None`.
  - Malformed response body (missing/short embedding, wrong dim ≠ 384) → returns `None`.
  - `embed_passages` (batch) returns `List[Optional[list[float]]]` aligned to input order.
  - Base URL read from `ml_bot_config.embedder_url` (mock `policy.get_config`), default `http://192.168.1.231:8080`.
  - No DB session is opened anywhere in this module (assert via no session fixture needed / no import of db session in the client).
  - Requirement: spec Requirements 1 & 2 (embedding correctness); design ADR-1.
  - DONE: `tests/unit/test_ml_bot_embedding_client.py` (14 tests).
- [x] **3.2** Create `backend/app/services/ml_questions/embedding_client.py`:
  - `EmbeddingProvider` Protocol.
  - `TEIEmbeddingProvider` over `httpx.AsyncClient`, mirrors `OpenAICompatProvider` retry/error-contract shape.
  - `embed_query`, `embed_passage` → `Optional[list[float]]`; `embed_passages` → batch.
  - Model `intfloat/multilingual-e5-small`, route `POST /v1/embeddings`, no auth, `timeout=5.0`.
  - Done when: all 3.1 tests pass.
  - Depends on: none (independent of migration; can start immediately, parallel with tasks 1–2).
  - Parallel: yes, with tasks 1 and 2.
  - DONE: `app/services/ml_questions/embedding_client.py`.

**PR1 status (tasks 0–3): SHIPPED (this run).** Tasks 4–8 (capture, retrieval, drafting_service wiring, config keys, guardrail regression, CI docs) are PR2/PR3 — NOT started.

## 4. Capture at publish success
- [x] **4.1** (TEST FIRST) Tests for `_capture_answer_history` / publisher integration:
  - Genuine post-success publish path (result not None → `_mark_published`) triggers capture.
  - Idempotent "already answered" path (no fresh publish) does NOT trigger capture.
  - `embed_passage` raising or returning `None` → capture silently skipped, publish still reports success (assert no exception propagates, publish status unaffected).
  - `edited_flag` set correctly from `answer_source == "human"`.
  - Capture failure (any exception in the whole capture block) is caught and logged, never fails publish.
  - Requirement: spec Requirement 1; design ADR-3.
  - DONE (PR2): `TestFewshotCapture` in `tests/unit/test_ml_bot_publisher_service.py` (7 tests) — also covers the `QuestionAlreadyAnsweredError` POST outcome (idempotent, no capture) and the retry-verification already-answered short-circuit (no capture, embed never called).
- [x] **4.2** Implement `_capture_answer_history(question_id)` in `publisher_service.py`, called from `_publish_one` only on the genuine post-success branch:
  - Short session #1: load plain fields (question_text, answer_text, item_id, category, answer_source).
  - No session while calling `embed_passage`.
  - If embedding is `None`: skip capture entirely (do not insert row with null embedding).
  - Short session #2: INSERT row.
  - Entire block wrapped in `try/except Exception: log.exception(...)`.
  - Done when: all 4.1 tests pass.
  - Depends on: 2.2, 3.2.
  - Parallel: no (depends on model + client).
  - DONE (PR2): `_capture_answer_history` in `app/services/ml_questions/publisher_service.py`, called only from the genuine `result is not None` POST-success branch of `_publish_one` (not from either already-answered path). Guarded by `is_fewshot_capture_enabled` (dark-launch, default False).

## 5. Retrieval in context_builder
- [ ] **5.1** (TEST FIRST) Tests for `load_few_shot_examples(db, limit, question_embedding=None)`:
  - `question_embedding=None` → static `orden`-based path unchanged (existing behavior preserved).
  - Dynamic path (feature flag on, embedding provided): cosine `<=>` ordering, `active=true` filter, `k`/threshold pulled from `ml_bot_config` via monkeypatched `policy.get_config`.
  - Empty result set after dynamic query → falls back to static path.
  - Simulated embedder/query error → falls back to static path (no exception escapes).
  - Return shape is identical `List[FewShotExample]` in both paths.
  - Use monkeypatched embedder + faked query layer (not real Postgres) so this test runs on CI's sqlite backend.
  - Requirement: spec Requirements 2 & 3; design ADR-4.
- [ ] **5.2** Update `context_builder.py`:
  - `load_few_shot_examples` accepts `question_embedding: Optional[list[float]] = None`.
  - `build_scoped_context(..., question_embedding=None)` threads it through.
  - Dynamic branch: pgvector cosine `ORDER BY embedding <=> :qvec LIMIT :k`, `WHERE active = true`, similarity threshold filter.
  - Triple fallback (disabled flag / embedder returns None / query raises or returns empty) → static `orden` path, no exception escapes to caller.
  - Done when: all 5.1 tests pass.
  - Depends on: 2.2.
  - Parallel: independent of task 4; can run alongside it once task 2 is done.
- [ ] **5.3** Update `drafting_service.py` to compute the query embedding OUTSIDE any DB session (mirrors `get_item_description` pattern) and pass it into `build_scoped_context(question_embedding=...)`.
  - Requirement: design ADR-4 (embedding call must never happen inside a session — ADR-5 cross-reference).
  - Depends on: 3.2, 5.2.

## 6. Config keys
- [x] **6.1** (TEST FIRST) Tests for fail-safe config parsing of the 5 new keys: correct type coercion, correct defaults when key missing/malformed, `fewshot_retrieval_k` clamped to `[1, 20]`.
  - Requirement: design ADR-5.
  - DONE (PR2): `tests/unit/test_ml_bot_fewshot_config.py` (17 tests) — covers `fewshot_capture_enabled`, `fewshot_dynamic_enabled`, `fewshot_k` (clamped `[1,20]`), `fewshot_similarity_threshold` (clamped `[0.0,1.0]`).
- [x] **6.2** Wire `fewshot_dynamic_enabled` (bool, default `false`), `fewshot_k` (int, default `5`, clamp `[1,20]`), `fewshot_similarity_threshold` (float, default `0.0`, clamp `[0.0,1.0]`), `fewshot_capture_enabled` (bool, default `false`) through `policy.get_config` fail-safe cast, consumed by tasks 4 and 5. `embedder_url` is NOT re-added here — `embedding_client.py` (PR1) already owns that exact key.
  - Done when: 6.1 passes; both feature flags dark-launch as `false`.
  - Depends on: none directly, but consumed by 4.2/5.2 — should land before or alongside them.
  - Parallel: yes, can run alongside tasks 3/4/5 exploration, but must merge before 4.2/5.2 are considered done (they call `get_config` for these keys).
  - DONE (PR2): `is_fewshot_capture_enabled`, `is_fewshot_dynamic_enabled`, `get_fewshot_k`, `get_fewshot_similarity_threshold` in `app/services/ml_questions/policy.py`. Key renamed from proposal's `fewshot_retrieval_k` to `fewshot_k` (matches design's own "Config keys" table naming) — PR3 (task 5) must use `get_fewshot_k`/`fewshot_k`, not `fewshot_retrieval_k`.

**PR2 status (tasks 4 + 6): SHIPPED (this run).** Task 5 (retrieval in context_builder + drafting_service wiring) is PR3 — NOT started. Capture is dark-launched (`fewshot_capture_enabled` default False); no corpus grows until explicitly enabled post-deploy.

## 7. Guardrail regression test
- [ ] **7.1** (TEST FIRST/ONLY — this is a pure regression test, no new production code) Add explicit test: seed a retrieved dynamic example containing a foreign price/address in its answer text; assert that text appears in `EJEMPLOS_DE_TONO` (tone block) but never in `_context_to_json` output / `CONTEXTO_PERMITIDO`. Assert system-prompt rule 1 text is unchanged (string/hash comparison against baseline).
  - Requirement: spec Requirement 4 (tone-only guardrail).
  - Depends on: 5.2 (dynamic path must exist to test against it).
  - Parallel: none — run last among the logic tasks, right after 5.2 lands.

## 8. CI limitation documentation
- [ ] **8.1** Mark Postgres-only tests (task 1.2 migration smoke test, any test exercising real `<=>`/HNSW against a live Vector column) with `@pytest.mark.skipif` on non-Postgres dialect (CI runs backend tests on sqlite `DATABASE_URL`).
  - Add a short note to `backend/README.md` or existing testing docs (wherever CI/test-backend caveats are already documented) stating: pgvector cosine operator and HNSW index require Postgres; these specific tests are skipped on sqlite CI and must be run manually / in a Postgres-backed CI job before merge.
  - Requirement: design "CI GOTCHA".
  - Depends on: 1.2.
  - Parallel: can be done any time after 1.2 exists, does not block other tasks.

---

## Parallelization summary
- **Sequential spine**: 0.1 → 1.1/1.2 → 1.3 → 2.1/2.2 → (4 and 5 in parallel) → 7.1.
- **Parallel from the start**: task 3 (embedding client) has no dependency on the migration/model and can start immediately alongside task 1.
- **Parallel mid-stream**: task 6 (config keys) can be developed alongside tasks 3/4/5, must land before 4.2/5.2 are marked done.
- **Task 4 vs Task 5**: independent of each other once task 2 (model) is done; can be split across two PRs/agents.
- **Task 8**: trivial, can slot in anytime after 1.2.

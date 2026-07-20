# Spec: ML Bot Dynamic Few-Shot (Answer History Capture + Similarity Retrieval)

## Purpose

Retrieval-only flywheel: capture human-approved published bot answers into a
new embedded corpus, and select few-shot tone examples by semantic similarity
to the incoming buyer question instead of a fixed `orden`. No fine-tuning. No
weakening of the tone-only data-scoping guardrail.

## Requirements

### Requirement: Answer History Capture at Publish Success

The system MUST persist `(question_text, answer_text, item_id, edited_flag,
category)` into `ml_bot_answer_history` at the terminal `status="published"`
write in `publisher_service.py`, with a 384-dim embedding of `answer_text`
computed via the "passage: " e5 prefix. `edited_flag` MUST derive from
`answer_source == "human"` (true) vs `"bot"` (false).

#### Scenario: Successful publish captures history row
- GIVEN a `MlBotQuestion` row transitions to `status="published"`
- WHEN the terminal write completes
- THEN a new `ml_bot_answer_history` row is created with `question_text`,
  `answer_text` (= `drafted_answer`), `item_id`, `edited_flag`, `active=true`
- AND the row's `embedding` is a 384-dim vector of the "passage: "-prefixed
  `answer_text`, truncated to the embedder's token limit before embedding

#### Scenario: Edited flag reflects operator takeover
- GIVEN a published row has `answer_source == "human"`
- WHEN it is captured
- THEN `edited_flag` is `true`
- GIVEN a published row has `answer_source == "bot"`
- WHEN it is captured
- THEN `edited_flag` is `false`

#### Scenario: Embed failure never fails the publish
- GIVEN the embedding call raises, times out, or the embedder is unreachable
- WHEN a row transitions to `published`
- THEN the publish transition itself MUST already have committed and MUST NOT
  roll back or block on capture
- AND the capture attempt is logged and skipped (no history row, or a row
  with a null embedding excluded from retrieval — implementation's choice, but
  drafting/publishing is never blocked)

#### Scenario: Long answer text is truncated before embedding
- GIVEN `answer_text` (or `question_text`) exceeds the embedder's 512-token
  input limit
- WHEN the text is prepared for embedding
- THEN it MUST be truncated defensively before the HTTP call, so the embedder
  never rejects the request for exceeding the token limit

### Requirement: Similarity-Based Few-Shot Retrieval

`load_few_shot_examples()` MUST embed the incoming buyer question with the
"query: " e5 prefix (truncated to the token limit) and return the top-k most
similar ACTIVE rows from `ml_bot_answer_history` as `List[FewShotExample]`,
with `k` and a similarity threshold read from `ml_bot_config`. The return
shape, `EJEMPLOS_DE_TONO` prompt block, and labeling MUST remain unchanged.

#### Scenario: Similar past answers are retrieved
- GIVEN `ml_bot_answer_history` has active rows with embeddings
- WHEN `load_few_shot_examples(db, question_text)` is called
- THEN the incoming question is embedded with the "query: " prefix
- AND the top-k rows by similarity above the configured threshold are
  returned as `FewShotExample(question, answer, category)`

#### Scenario: k and threshold are tunable
- GIVEN `ml_bot_config` has retrieval `k` and similarity-threshold keys set
- WHEN retrieval runs
- THEN it MUST use those configured values (not hardcoded constants)
- AND absent/malformed config values fail safe to documented defaults

#### Scenario: Inactive rows are excluded
- GIVEN a history row has `active=false`
- WHEN retrieval runs
- THEN that row MUST NOT be returned as a few-shot example, regardless of
  similarity score

#### Scenario: Prefix and dimension consistency
- GIVEN stored embeddings were computed with the "passage: " prefix at
  384 dims
- WHEN a query embedding is computed for retrieval
- THEN it MUST use the "query: " prefix and produce a 384-dim vector matching
  the stored dimensionality (a dimension mismatch MUST be treated as a
  retrieval error, triggering fallback)

### Requirement: Cold-Start and Failure Fallback

Retrieval MUST fall back to the existing static top-10-by-`orden` query over
`ml_bot_answer_examples` whenever the history corpus is empty, the embedder is
unreachable/times out/errors, or the similarity query itself fails. Drafting
MUST NEVER be blocked by retrieval failure.

#### Scenario: Empty corpus falls back to static path
- GIVEN `ml_bot_answer_history` has zero active rows
- WHEN `load_few_shot_examples()` is called
- THEN it returns the static top-10-by-`orden` examples from
  `ml_bot_answer_examples`, unchanged from current behavior

#### Scenario: Embedder unreachable falls back
- GIVEN the embedding HTTP call times out or raises a connection error
- WHEN `load_few_shot_examples()` is called
- THEN it falls back to the static `orden` path
- AND the failure is logged
- AND no exception propagates to the drafting caller

#### Scenario: Retrieval query error falls back
- GIVEN the similarity query raises a database error
- WHEN `load_few_shot_examples()` is called
- THEN it falls back to the static `orden` path without raising

### Requirement: Tone-Only Data-Scoping Guardrail Preserved

Retrieved few-shot examples MUST remain tone/style reference only; system
prompt rule 1 ("answer only from CONTEXTO_PERMITIDO") is unchanged, and
example content MUST NEVER become a fact source for a different item's
price/stock/compatibility.

#### Scenario: Example content never leaks as a fact source
- GIVEN a retrieved few-shot example contains a fact about a DIFFERENT item
  (e.g. a price or compatibility claim)
- WHEN a prompt is built via `build_prompt()`
- THEN that fact MUST NOT appear in `CONTEXTO_PERMITIDO`
- AND the example content is placed ONLY inside `EJEMPLOS_DE_TONO`, labeled
  "solo como referencia de estilo, no como fuente de datos"
- AND system prompt rule 1 text is byte-identical to the pre-change template

## Assumptions

- `CREATE EXTENSION vector` (pgvector) is available on the target Postgres
  before apply — confirmed as a blocking prerequisite in the proposal, not a
  spec-level guarantee.
- Embedder base URL (`http://192.168.1.231:8080`, LAN-only, no auth) and model
  `intfloat/multilingual-e5-small` (384 dims) are treated as configuration,
  not hardcoded — exact config key naming is a design decision.

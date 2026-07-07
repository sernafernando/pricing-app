# Runbooks - Pricing App

Last update: 2026-02-10
Audience: On-call / solo developer

## 1) API Degraded or Down

### Symptoms

- API returns 5xx or timeout.
- `/health` fails.
- Frontend cannot authenticate or load products.

### First 15-Minute Response

1. Confirm service health (`/health`, process status, recent deploy).
2. Check application logs for startup/runtime exceptions.
3. Check DB connectivity and credential validity.
4. Validate recent config changes (`.env`, CORS, auth settings).
5. If caused by latest release, perform safe rollback.

### Quick Checks

- Is process running and bound to expected port?
- Did DB connection fail or pool saturate?
- Is JWT config (`SECRET_KEY`, `ALGORITHM`) consistent?
- Did CORS/auth middleware change unexpectedly?

### Safe Mitigation

- Roll back to previous known-good revision.
- Disable only non-critical background jobs if they overload service.
- Do not disable auth/permission checks as a temporary workaround.

### Escalation

- Owner: API maintainer.
- Escalate if outage exceeds 15 minutes or data integrity is at risk.

---

## 2) ML Sync Delayed or Stuck

### Symptoms

- Dashboard shows stale ML metrics.
- Order/publication sync lag increases.
- Sync scripts repeatedly fail.

### First 15-Minute Response

1. Identify failing sync job and error class.
2. Verify external dependency availability (ML API/webhook DB).
3. Validate credentials/tokens and expiration state.
4. Check if retries are causing duplicates or lock contention.
5. Execute controlled backfill for missing range only.

### Quick Checks

- Are sync scripts running on expected cadence?
- Is refresh token flow operational?
- Any schema drift between app and source tables?
- Are idempotency keys/guards being respected?

### Safe Mitigation

- Pause failing job temporarily if it causes repeated bad writes.
- Run incremental sync first, then targeted backfill.
- Avoid manual SQL fixes without migration or audit note.

### Recovery Validation

- Lag returns under expected threshold.
- No duplicate rows introduced.
- Metrics and orders align with source system.

### Escalation

- Owner: Integration maintainer.

---

## 3) ML Questions Bot (Auto-Responder)

### Overview

Pipeline: ingest → draft → publish, one MercadoLibre account per env.

- **Ingest**: `ingestion_service.py` polls the ML questions webhook DB
  cross-database and creates `ml_bot_question` rows (state `received`).
- **Draft**: `drafting_service.py` builds context (`context_builder.py`),
  calls the LLM via `llm_provider.py` (`OpenAICompatProvider`, `LlmProvider`
  protocol) rotated across a roster by `provider_rotation.py`, applies the
  soft denylist, and moves the row to `waiting` (a provider/parse error
  routes to the `waiting` fallback message, `answer_source=fallback`;
  `failed` is reserved for unexpected errors after exhausting retries).
- **Publish**: `publisher_service.py` runs a wait-window background loop,
  claims `waiting` rows (CAS on `status`, `waiting -> publishing`), and
  publishes the answer via `ml_api_client.py`, moving the row to
  `published` or `failed`.
- **API**: `routers/ml_bot.py` under `/api/ml-bot` — questions
  list/take-over/answer/publish-now/hold, config CRUD, toggle, few-shot
  examples CRUD. SSE channel `ml_bot:questions` fires a reload hint on
  terminal state transitions only (intermediate retries deliberately do not
  emit, see `publisher_service.py` docstring) (`routers/sse.py`).
- **Panel**: `/ml-preguntas` (`frontend/src/pages/MLQuestions.jsx`).

### Enabling the Bot

1. Set `GROQ_API_KEY` in the environment (`backend/app/core/config.py`).
2. The DB migration seeds `ml_bot_config` with its default clave/valor rows
   automatically — no manual seeding needed. Provider secrets live in
   `.env`, never in `ml_bot_config`.
3. Toggle the bot on from the panel (`ml_bot.on_off` permission) or via
   `POST /api/ml-bot/toggle` (`{"enabled": true}`).

### LLM Provider Rotation

The bot rotates draft requests across multiple OpenAI-compatible free-tier
APIs so no single provider takes 100% of the traffic, with per-question
failover if one is rate-limited/down (`provider_rotation.py`).

1. Env keys (`.env`, secrets only — never in `ml_bot_config`):
   `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `OPENROUTER_API_KEY`. A provider is
   only used if its key is set AND it's `enabled` in the roster.
2. Roster: `ml_bot_config` key `llm_providers`, a JSON list, panel-editable
   via `PUT /api/ml-bot/config`:
   ```json
   [
     {"name": "groq", "enabled": true},
     {"name": "cerebras", "enabled": true},
     {"name": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free", "enabled": true}
   ]
   ```
   `model` is optional per entry (falls back to each provider's default:
   Groq `llama-3.3-70b-versatile`, Cerebras `llama-3.3-70b`, OpenRouter
   `meta-llama/llama-3.3-70b-instruct:free` — panel-changeable). Unknown
   `name`s are skipped with a warning; missing/malformed JSON fails safe to
   a Groq-only roster (the pre-rotation MVP behavior).
3. Rotation cursor: `ml_bot_config` key `llm_rotation_cursor` (int,
   auto-managed) — round-robin, advances once per drafted question.
4. Failover: if the chosen provider raises, the next available provider in
   rotation order is tried (at most one full cycle) before routing to the
   warm fallback. Which provider answered is logged (`drafting_service`
   logs, `INFO` level) — no DB column added for this (logging only, MVP).

### Permissions

`ml_bot.ver` (view the panel / `GET /questions`), `ml_bot.responder` (act on
questions), `ml_bot.on_off` (toggle), `ml_bot.config` (config + examples
CRUD).

### Interpreting Failed Rows

- `failed` at drafting: an unexpected error (bug, DB error) after exhausting
  the bounded retry budget — check drafting_service logs, retry is manual
  (edit + publish-now from the panel). An LLM/provider or schema-parse
  error does NOT produce `failed` — it routes to the `waiting` warm
  fallback message instead (`answer_source=fallback`).
- `failed` at publish: CAS conflict or ML API error — the panel's
  publish-now action re-runs the publish pipeline for that row.
- `taken_over` / `pending_morning`: awaiting a human operator, not a bug.

### Known Limitations (accepted, tracked as follow-ups)

- Cursor tracking uses `NULL`/`''` interchangeably in one ingestion path —
  low-risk collision, not yet unified.
- Single ML account per environment (no multi-account support).
- No standalone `GET /toggle-status`; reading bot on/off currently requires
  `ml_bot.config` in addition to `ml_bot.on_off`.
- Panel status filter accepts a single value (no multi-status/OR filter).
- The soft denylist warning on manual edits does not block human-authored
  content — it is advisory only, by design.

### Escalation

- Owner: ML Bot maintainer.
- Escalate if data mismatch persists after one controlled backfill.

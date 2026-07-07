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
  cross-database and creates `ml_bot_question` rows (state `pending`).
- **Draft**: `drafting_service.py` builds context (`context_builder.py`),
  calls the LLM via `llm_provider.py` (`GroqProvider`, `LlmProvider` protocol),
  applies the soft denylist, and moves the row to `waiting`
  (or `failed` on parse/provider error).
- **Publish**: `publisher_service.py` runs a wait-window background loop,
  claims `waiting` rows (CAS on `updated_at`), and publishes the answer via
  `ml_api_client.py`, moving the row to `published` or `failed`.
- **API**: `routers/ml_bot.py` under `/api/ml-bot` — questions
  list/take-over/answer/publish-now/hold, config CRUD, toggle, few-shot
  examples CRUD. SSE channel `ml_bot:questions` fires a reload hint on every
  state transition (`routers/sse.py`).
- **Panel**: `/ml-preguntas` (`frontend/src/pages/MLQuestions.jsx`).

### Enabling the Bot

1. Set `GROQ_API_KEY` in the environment (`backend/app/core/config.py`).
2. Seed `ml_bot_config` (one row) with the account/provider settings.
3. Toggle the bot on from the panel (`ml_bot.on_off` permission) or via
   `PUT /api/ml-bot/config` (`enabled=true`).

### Permissions

`ml_bot.responder` (act on questions), `ml_bot.on_off` (toggle),
`ml_bot.config` (config + examples CRUD).

### Interpreting Failed Rows

- `failed` at drafting: LLM/provider error or schema parse failure — check
  drafting_service logs, retry is manual (edit + publish-now from the panel).
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

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

### Supervised Mode (Trial Period)

`ml_bot_config` key `auto_publish_enabled` gates the bot's automatic
publish path (`publisher_service.run_ml_questions_publish_cycle`). No
migration seeds this key — the value is cast via the shared `_cast_bool`
truthy convention (`"true"`/`"1"`/`"yes"`/`"si"`/`"sí"`, case-insensitive,
trimmed); **absent, empty, or anything else (any other value) is treated
as `false` (supervised)**, the same fail-safe pattern as `bot_enabled`: the
bot never auto-publishes unless explicitly enabled.

- **Supervised (default)**: the background publish loop skips the
  automatic due-row selection entirely (logged at `debug`,
  `stats["supervised_skip"] = True`). Drafts still land in `waiting` as
  normal — an operator reviews them on the panel and clicks
  "Publicar ahora" (`POST /api/ml-bot/questions/{id}/publish-now`), which
  reuses the same publish pipeline and is **unaffected** by this gate.
  Stale-claim reclaim (crash recovery, not publishing) also always runs.
- **Auto (production)**: set `auto_publish_enabled=true` from the panel's
  config tab (`ml_bot.config` permission) or
  `PUT /api/ml-bot/config/auto_publish_enabled` (`{"valor": "true", "tipo": "bool"}`)
  to let due `waiting` rows publish automatically again.

**Trial workflow**: deploy → turn the bot on (`bot_enabled=true`) with
`auto_publish_enabled` left absent/false → operators review and approve
every drafted answer from the panel (edit if needed, then publish-now) →
once confident in draft quality, flip `auto_publish_enabled=true` from the
panel to let the bot publish unattended.

The panel shows a badge next to the bot toggle ("Publicación automática:
ON/OFF — modo supervisado") for `ml_bot.config` holders, and while
supervised, `waiting` rows show "esperando aprobación" instead of a
countdown (same config-tab-only visibility limitation as the existing
bot-status badge).

### LLM Provider Rotation

The bot rotates draft requests across multiple OpenAI-compatible free-tier
APIs so no single provider takes 100% of the traffic, with per-question
failover if one is rate-limited/down (`provider_rotation.py`).

1. Env keys (`.env`, secrets only — never in `ml_bot_config`):
   `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `OPENROUTER_API_KEY`. A provider is
   only used if its key is set AND it's `enabled` in the roster.
2. Roster: `ml_bot_config` key `llm_providers`, a JSON list, panel-editable
   via `PUT /api/ml-bot/config/{clave}`:
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

### Answer Shaping (Concision, Closing, Company Signature)

`answer_shaping.py` post-processes every REAL bot answer (never the warm
fallback) with four panel-editable `ml_bot_config` keys, all applied
deterministically AFTER the LLM call — never inside the prompt's own JSON
output — so `drafted_answer` always shows the operator exactly what will be
published:

1. `answer_max_chars` (int, default `300` when absent/malformed/non-positive):
   injected dynamically into the system prompt ("Respondé en menos de N
   caracteres...") AND enforced fail-closed at parse time
   (`llm_provider.parse_llm_output`) — an answer over the limit is rejected
   like any other schema violation and routes to the warm fallback, never
   published over-limit.
   ```
   PUT /api/ml-bot/config/answer_max_chars
   {"valor": "250", "tipo": "int"}
   ```
2. `answer_closing_text` (string, absent/empty = off): a closing greeting
   appended to real answers only.
   ```
   PUT /api/ml-bot/config/answer_closing_text
   {"valor": "¡Gracias por tu consulta!", "tipo": "string"}
   ```
3. `answer_company_signature` (string, DEFAULT signature): used ONLY for
   publications WITHOUT an official store (`item.official_store_id` absent).
   ```
   PUT /api/ml-bot/config/answer_company_signature
   {"valor": "Somos Gauss Online", "tipo": "string"}
   ```
4. `answer_signatures_by_store` (JSON object, per-store override): applies
   ONLY to publications WITH an official store — the default signature is
   never used for these. Key = `official_store_id` as a string, value = the
   signature text (`""` = explicitly no signature for that store).
   ```
   PUT /api/ml-bot/config/answer_signatures_by_store
   {"valor": "{\"2645\": \"Somos la tienda oficial TP-Link\"}", "tipo": "json"}
   ```
   **Fail-safe rules**: an official-store item with NO entry in this map
   gets NO signature at all (better unsigned than signed with the wrong
   store's text); malformed JSON disables per-store signatures entirely
   (logged warning) without affecting the default signature for
   non-official items.

Assembly order: `LLM answer` + `"\n\n" + closing` (if any) + `"\n" +
signature` (if any). `answer_max_chars` values above 1500 are clamped to
1500 (with a warning logged) so closing/signature always have room; each
optional component is appended only if it fits within the 2000-char ML
cap, otherwise it is dropped WHOLE (never sliced mid-text) — the assembled
text never ends mid-component. Verify signature discrimination against a
real official-store item during the trial (check the drafting log line —
`ml-bot drafting: question <id> official_store_id=... signature_path=...`).

### Business Hours vs Attention Hours (schedules-v2)

Two separate, independently-editable `ml_bot_config` keys — the bot's
WORKING schedule (gates eligibility) is not the same as the ATTENTION hours
text it tells buyers:

1. **`work_schedule`** (JSON, per-day, panel-editable): governs
   `policy.is_within_business_hours` (the bot-eligibility gate, R-201/R-202)
   and the R-602 repeat-buyer-after-midnight window
   (`policy.resolve_last_working_day_end`). Keys are ISO weekdays `"1"`
   (Monday) through `"7"` (Sunday); an absent day means non-working. Example
   matching a Mon-Fri 09-18 + Saturday 09-13 real-world schedule:
   ```
   PUT /api/ml-bot/config/work_schedule
   {
     "valor": "{\"1\": [\"09:00\", \"18:00\"], \"2\": [\"09:00\", \"18:00\"], \"3\": [\"09:00\", \"18:00\"], \"4\": [\"09:00\", \"18:00\"], \"5\": [\"09:00\", \"18:00\"], \"6\": [\"09:00\", \"13:00\"]}",
     "tipo": "json"
   }
   ```
   Boundary semantics are unchanged: `[start, end)` per day (start counts as
   in-hours, end does not). **Fail-safe cascade**: if `work_schedule` is
   absent/empty, or malformed in any way (invalid JSON, not a JSON object,
   a day key outside `1`-`7`, a bad `"HH:MM"` time, or `start >= end` for a
   day), the bot logs a warning and falls back to the legacy
   `business_days` (JSON list of ISO weekdays) + `business_hours_start` /
   `business_hours_end` (single `"HH:MM"` pair, same hours every business
   day) keys — full backward compatibility for deployments that never set
   `work_schedule`.
2. **`attention_hours_text`** (free text, panel-editable): what the bot
   TELLS buyers about when they'll get a human response — independent of
   the gate above, so it can read naturally even for an irregular schedule:
   ```
   PUT /api/ml-bot/config/attention_hours_text
   {"valor": "de lunes a viernes de 9 a 18hs y sábados de 9 a 13hs", "tipo": "string"}
   ```
   Flows into two places:
   - The LLM's `business_vars` (`context_builder.load_business_vars`), so a
     real bot answer can reference it naturally.
   - The `{attention_hours}` placeholder inside `warm_fallback_template`,
     resolved at fallback-render time (`drafting_service._build_fallback_message`):
     replaced with the configured text when set; cleanly removed (never a
     literal `"{attention_hours}"`, never a crash) when absent/empty.

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

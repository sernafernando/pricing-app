# Runbooks - Pricing App

Last update: 2026-08-13
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

### Migration Convention: Updating `ml_bot_config` Defaults

`ml_bot_config` values are **panel-editable**: operators customize them at
runtime. This creates a tension when a new migration wants to update a
default that was previously seeded — we want to fix stale defaults on
prod without clobbering an operator's intentional customization.

**Seeding a new key** (never existed before): use `ON CONFLICT DO NOTHING`.
Fresh deploys get the default; existing prods either get the default (if
absent) or keep whatever was already there (customizations preserved).

```sql
INSERT INTO ml_bot_config (clave, valor, descripcion, tipo)
VALUES (:clave, :valor, :descripcion, :tipo)
ON CONFLICT (clave) DO NOTHING
```

**Rewording a default** for a key that was seeded by a previous migration
with different wording: use a conditional `UPDATE` that pisas only if the
value still matches the OLD default. This is the "smart replace" pattern
that keeps operator customizations intact:

```sql
UPDATE ml_bot_config
SET valor = :new_default
WHERE clave = :clave
  AND valor = :old_default_exact_string  -- only overwrite the stale default
```

If the operator had edited the wording, `valor <> :old_default_exact_string`
and the UPDATE is a no-op — customization preserved. If the operator never
touched it, the row still holds the old default text, matches, gets
updated to the new wording. Idempotent across re-runs.

Case in point: PR #880 (July 2026) added a new fallback wording as the
default for `warm_fallback_template`, but the migration used `ON CONFLICT
DO NOTHING` — which correctly preserved operator customizations but ALSO
preserved the old default from the July 6 seed, so prod kept rendering
the old "¡Hola! Gracias por tu consulta..." text. The fix was an
operator-run UPDATE with the WHERE-matches-old-default guard. Future
default reworks should ship the smart UPDATE inside the migration itself:

```python
def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE ml_bot_config
            SET valor = :new
            WHERE clave = :clave AND valor = :old
            """
        ),
        {
            "clave": "warm_fallback_template",
            "old": (
                "¡Hola! Gracias por tu consulta. Nuestro horario de atención "
                "es de {business_hours_start} a {business_hours_end}. "
                "Te respondemos apenas abramos."
            ),
            "new": (
                "¡Hola! No tengo esa información en este momento. "
                "Volvé a escribirnos {attention_hours} y con gusto te "
                "averiguamos. ¡Gracias!"
            ),
        },
    )
```

**Rule of thumb**: `ON CONFLICT DO NOTHING` is for adding rows; a
match-the-old-default `UPDATE` is for changing wordings. Never
`ON CONFLICT DO UPDATE SET valor = EXCLUDED.valor` blindly — that
overwrites customizations without warning.

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
     {"name": "groq", "model": "llama-3.3-70b-versatile", "enabled": true},
     {"name": "cerebras", "model": "gpt-oss-120b", "enabled": true},
     {"name": "openrouter", "model": "openai/gpt-oss-20b:free", "enabled": true}
   ]
   ```
   `model` is optional per entry (falls back to each provider's default in
   `provider_rotation._known_provider_specs`), but **pin it explicitly and
   verify the id exists at that provider before saving**. A model id the
   provider does not recognise answers 4xx, which is treated as a permanent
   error (no retry) and fails over — so a typo'd or retired id silently
   removes that provider from rotation and hands its share to the others.
   That exact failure shipped once: the original seed carried
   `cerebras/llama-3.3-70b` and `openrouter/meta-llama/llama-3.3-70b-instruct:free`,
   neither of which exists, and Groq quietly answered 100% of questions
   (fixed in migration `20260727_fix_llm_ids`).

   To check an id before saving it:
   ```bash
   curl -s -H "Authorization: Bearer $CEREBRAS_API_KEY" \
     https://api.cerebras.ai/v1/models | jq -r '.data[].id'
   curl -s https://openrouter.ai/api/v1/models | jq -r '.data[].id'   # no auth needed
   ```

   Unknown `name`s are skipped with a warning; missing/malformed JSON fails
   safe to a Groq-only roster (the pre-rotation MVP behavior).

   Note both replacement models are reasoning models: completion tokens
   include reasoning tokens, so Cerebras' 30k tokens/minute cap binds before
   its 5 requests/minute cap at our payload sizes.
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

### Context Enrichment (Item Title + Description)

`context_builder.py` includes the ML listing's own `title` and description
(`plain_text`, fetched via `ml_client.get_item_description`) in the scoped
context passed to the LLM (`titulo`/`descripcion` in the prompt's
`CONTEXTO_PERMITIDO` JSON), on top of the existing allowlisted spec
attributes — fixes a real production case where the bot said "no tenemos
info" about the OS even though the title/description stated it.

- `description_max_chars` (int, default `1500`, clamped to `[100, 4000]`):
  truncates the fetched description before it reaches the prompt.
  ```
  PUT /api/ml-bot/config/description_max_chars
  {"valor": "1000", "tipo": "int"}
  ```
- Fetch failure (network/404/timeout) or an absent description never blocks
  drafting — the row still drafts normally, just without that section.
- Trust boundary: title/description are seller-authored (same trust class as
  the allowlisted spec attributes) and are NOT scanned/dropped for
  price/address-like content — the "never reveal price/stock/address"
  guarantee is enforced on the LLM's OUTPUT (system prompt rule + the
  existing answer denylist), not by hiding seller-authored listing text.

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
     replaced with the configured text when set; cleanly removed — along with
     its immediate surrounding whitespace, never a double space or an orphan
     `" ."` — (never a literal `"{attention_hours}"`, never a crash) when
     absent/empty. Braces inside the configured text itself (e.g. a stray
     `"{"` from a typo) are escaped before substitution and never crash
     rendering. Recommended: write the template so the placeholder forms a
     self-contained clause (e.g. `"Escribinos {attention_hours} y te
     respondemos."`) so it still reads naturally when the value is unset.

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

---

## 4) Deploy Notifications (wabot / WhatsApp)

### Overview

`deploy.sh` announces itself to the internal WhatsApp group through the wabot
service: one message when it starts, one when it finishes. Sending is
best-effort via `scripts/notify-wabot.sh`, which always exits 0 — a WhatsApp
outage can never break or delay a deploy.

Messages sent:

| Moment | Content |
| --- | --- |
| Start | Backend is going to restart, estimated duration, "we'll tell you when it's up" |
| End (OK) | Backend confirmed up via health check, real duration, and — only when the frontend was rebuilt — the Ctrl+Shift+R reminder |
| End (degraded) | Deploy finished but `/health` never answered; tells people **not** to use the app yet |
| Failure / Ctrl+C | Which step it died on and how long it ran, so nobody waits for an "it's up" that will never arrive |

### Required Setup on the Server (one time)

Without `WABOT_TOKEN` the helper logs a warning to stderr and sends nothing.
The deploy still succeeds, so a missing token fails **silently** from the
group's point of view. Verify it after any server rebuild.

```bash
# Read the current token from the service itself — never copy it between docs
ssh wabot 'grep WABOT_TOKEN /etc/wabot.env'

# Store it on the deploy host (192.168.1.219), root-only.
# Single quotes matter: the file is sourced by bash, so an unquoted $, { or }
# in the token would be expanded or mangled instead of sent verbatim.
sudo install -m 600 /dev/null /etc/wabot-client.env
echo "WABOT_TOKEN='<value>'" | sudo tee /etc/wabot-client.env >/dev/null

# Verify the token was stored literally, not expanded into something else
sudo grep WABOT_TOKEN /etc/wabot-client.env

# Confirm the helper reaches the service.
# Invoke it through `bash`: the repo versions .sh files as 100644, so the file
# arrives from git without the executable bit and `./notify-wabot.sh` would fail.
bash /var/www/html/pricing-app/scripts/notify-wabot.sh "prueba de deploy notifications"
```

Only `192.168.1.219`, `192.168.1.228` and `192.168.1.230` are allowed through
the firewall to wabot (TCP 3000). From any other host the call times out and
the helper prints `unreachable (timeout or firewall)`.

### Tuning

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEPLOY_ETA_MIN` | `5` | Estimated minutes announced in the start message |
| `HEALTHCHECK_URL` | `https://pricing.gaussonline.com.ar/health` | Polled to confirm the backend is really up |
| `HEALTHCHECK_TIMEOUT` | `120` | Seconds to wait before declaring the backend degraded |

Do **not** point `HEALTHCHECK_URL` at `http://192.168.1.219:8000/health`: that
path is not mounted on the raw backend port and answers 404, which would
report a permanent false outage.

Use `./deploy.sh --no-notify` for test or repeated deploys so the group is not
spammed.

### First Deploy After `deploy.sh` Itself Changed

`deploy.sh` runs `git pull` on itself while bash is still reading it, so the
running (old) copy can be cut short mid-execution — silently, with no error.
Whenever a deploy brings a new `deploy.sh`, pull first and deploy second:

```bash
cd /var/www/html/pricing-app
git pull            # updates deploy.sh on disk BEFORE bash starts reading it
./deploy.sh         # the internal pull is now a no-op, nothing gets rewritten
```

Skipping this can end the deploy right after the pull: no build, no backend
restart, and no notification. Tracked in `docs/tech-debt-ledger.md`.

### `git pull` Refuses to Touch `deploy.sh`

```
error: Your local changes to the following files would be overwritten by merge:
        deploy.sh
```

Usually **not** a content change: the repo versions `deploy.sh` as `100644`,
but on the server it was made executable to run it as `./deploy.sh`. With
git's default `core.fileMode=true` that mode difference counts as a local
modification. Confirm before touching anything:

```bash
cd /var/www/html/pricing-app
git diff -- deploy.sh              # empty output = only the mode differs
git diff --summary -- deploy.sh    # shows "mode change 100755 => 100644"
```

If the content diff is empty, stop tracking the mode in this clone — it is
the permanent fix and loses nothing:

```bash
git config core.fileMode false
git pull
```

If the content diff is **not** empty, someone edited the script on the server.
Save that first (`cp deploy.sh /root/deploy.sh.server`), review the diff, and
port anything worth keeping into the repo instead of discarding it. Never
`git reset --hard` or `git checkout -- .` before reading that diff.

### Quick Checks

```bash
# Is the WhatsApp session linked? 200 = ok, 503 = not linked (self-heals)
curl -s http://192.168.1.232:3000/health

# Deploy silent but succeeding? The reason is on stderr
sudo cat /etc/wabot-client.env >/dev/null && echo "token file present"
```

### Escalation

- `503` on `/health`: the WhatsApp session is reconnecting. It recovers on its
  own; do not retry in a loop.
- Persistent `503` or `state: "qr"`: the session needs a manual QR re-scan on
  the wabot LXC (`ssh wabot`). Deploys keep working meanwhile.

---

## 5) Gentle AI Review Blocked Across Git Worktrees

### Context

This repo is developed from multiple Git worktrees (`pricing-app`,
`pricing-app-2` … `pricing-app-7`, plus ad-hoc ones). They all share a
single Git common dir, and therefore a single Gentle AI review store at
`<main-worktree>/.git/gentle-ai/`. Several editor instances routinely run
at once, one per worktree. Observed 2026-08-04: 3 live instances, 41
review lineages in the shared store.

### Symptoms

- `gentle-ai review validate` fails with `receipt_ambiguous`.
- `gentle-ai review validate` fails with `scope-changed` on a candidate
  that was already approved.
- `gentle-ai review capture-result` fails with
  `repository_context_capture_failed`, leaving the lineage in `reviewing`
  with no captured result.

### Quick Checks

```bash
# Which worktrees exist and where they point
git worktree list

# Live editor instances and their working directory
for p in $(pgrep opencode); do echo -n "$p "; readlink /proc/$p/cwd; done

# Lineages in the shared store
ls -1 <main-worktree>/.git/gentle-ai/review-transactions/v2/
```

### Known Causes and Fixes

**`receipt_ambiguous` — several worktrees hold terminal receipts.**
Confirmed. The gate cannot pick a receipt on its own. Always pass the
lineage explicitly:

```bash
gentle-ai review validate --gate pre-commit --lineage <lineage-id>
```

**`scope-changed` — a live CodeGraph index inside the reviewed worktree.**
Confirmed. `.codegraph/` holds a multi-hundred-MB SQLite database whose
watcher rewrites it every few minutes. Because the projection includes
intended-untracked paths, the frozen candidate is invalidated mid-review
and an already-approved receipt is lost. Remove `.codegraph/` from a
worktree before starting a review there, or keep the index out of
worktrees used for delivery.

**`scope-changed` — the candidate is empty, not broken.** Confirmed
2026-08-13 in a worktree with no `.codegraph/` at all, so the cause above
did not apply. After committing a `projection=workspace` review the tree
is clean, so the default projection has nothing to compare: it reports
`base_tree == candidate_tree` and `paths: []`. The receipt is fine. Pass
the base explicitly and route from the transition it returns:

```bash
gentle-ai review status --contract gentle-ai.review-integration/v2 \
  --base-ref origin/main --gate pre-pr --next-transition
```

That reports `applicability: current_target`, `receipt: present`, and the
exact `validate` command that returns `allow`.

**`scope-changed` — the receipt covers less than the PR delivers.**
Confirmed 2026-08-13. Reviewing a multi-commit range and then adding
another commit on top leaves the range covered by two chained receipts
and none matching the live gate target, so the gate refuses. This one is
the gate being right: do not force it. Rebasing onto the current `main`
produced a fresh target and `fresh_target_ready`, and a single full-range
review then passed both `pre-push` and `pre-pr` — no recovery
authorization was needed, even though status had been asking for one.

**`repository_context_capture_failed` — recovery procedure established.**
Superseded the earlier "cause NOT established" note. The root cause is
still unknown, but recovery is now known and worked first try on
2026-08-13: do NOT relaunch based on the error text. Re-query negotiated
status, and relaunch the lens reviewer only if the fresh `next_transition`
reoffers the exact same bound slot — identical `lineage`,
`expected-revision`, `target`, `repository-context`, `lens`, `order` and
`subject-hash`. If status instead reports the capture as already
committed, continue without relaunching. The preserved `rinc1_…` result is
not reusable: the same result cannot be re-admitted.

### `--base-ref` is blind to the working tree

Confirmed 2026-08-13, and this one can ship unreviewed code. `--base-ref`
pins the projection to base-against-HEAD, meaning **committed** content.
With uncommitted changes in the tree, status can report `receipt: present`
and `approved_receipt_ready` while describing the OLD content. Trusting it
and committing delivers unreviewed lines under a receipt that never saw
them.

Always confirm the authority is looking at your actual work:

```bash
# What status says it is reviewing
gentle-ai review status --contract gentle-ai.review-integration/v2 \
  --base-ref origin/main --next-transition   # read current_candidate_tree

# What your tree actually is
git add -A && git write-tree && git reset
```

If those two trees differ, status is not looking at your changes. Drop
`--base-ref` to get the workspace projection, which does see them.

### A fast-moving `main` invalidates full-range receipts

Confirmed 2026-08-13: four PRs merged into `main` during a single working
session. A full-range (`base-diff`) review binds the receipt to the base
tree, so every `main` advance changes the target and expires it. Reviewing
the workspace change and pushing promptly is more robust. When a single
receipt over the whole PR range is genuinely required, rebase and review
immediately before pushing, not hours earlier.

### Do NOT assume a queue is missing

The store lock at
`<main-worktree>/.git/gentle-ai/review-transactions/v2/LOCK` is advisory
and tolerates a dead owner. Verified on 2026-08-04: PIDs 1714802 and
1728186 both appeared as lock owners while already dead, the file
persisted, and the owner PID kept rotating; reviews completed
successfully in the same window. Do not serialize work or delete the lock
based on its contents alone — always check owner liveness first
(`ps -p <pid>`).

### Safe Mitigation

- Prefer running one review at a time per repository when practical, but
  do not treat that as a fix — it is noise reduction, not a root cause.
- Never hand-edit files under `.git/gentle-ai/`. Use the supported
  subcommands (`review status`, `review recover`, `review abandon`,
  `review reclaim`) and read their `--help` first.
- Never chain a push behind a pipe that filters gate output. `validate ...
  | rg '"result"' && git push` pushes even when the gate says
  `invalidated`, because the exit code belongs to `rg`, not to the gate.
  Read the gate result, then push as a separate step. Hit on 2026-08-13.
- Route only from the `next_transition` a status query returns. When a gate
  refuses, re-query status instead of improvising a flag: on 2026-08-13 the
  refusals were resolved by an explicit `--base-ref` and by a rebase, and
  the `recovery_authorization_required` state that status kept reporting
  turned out not to need a maintainer override at all.
- If a lineage is stuck with no captured result and cannot be recovered,
  abandon it and start a fresh review rather than forcing the gate.

### Escalation

- Owner: repository maintainer.
- Escalate upstream to `Gentleman-Programming/gentle-ai` when a failure is
  reproducible and the consumer workflow stays blocked. Scrub absolute
  paths, hostnames, usernames and tokens before filing.

# Technical Debt Ledger

Deliberate shortcuts marked with `ponytail:` in the codebase, harvested here so "later" doesn't become "never".

## How it works

1. When you take a conscious shortcut, leave a marker at that exact line:
   `# ponytail: <what was deferred and the condition to revisit>`
2. Harvest markers on demand:
   ```bash
   rg -n "ponytail:" --glob '!docs/tech-debt-ledger.md' backend frontend
   ```
3. Move each item into the **Open debt** table below, then resolve them before releases.

## Open debt

| File:Line | Shortcut | Revisit when | Added |
|-----------|----------|--------------|-------|
| `backend/app/routers/administracion_compras.py` (wipe-compras route decorator) | Env-gate dependency only runs after the HTTP method matches, so `GET /testing/wipe-compras` outside dev/testing returns 405 instead of 404 — reveals the route exists via method-probing | If the route is moved to conditional registration (only mounted when `settings.is_dev_or_test`) | 2026-07-02 |
| `backend/app/api/endpoints/auth.py` (`login` route) | Malformed-body (422) login requests bypass the rate limiter — FastAPI validates the request body before the slowapi-wrapped endpoint runs, so an attacker sending unparseable bodies is never counted | If login abuse via malformed bodies is observed (would need a middleware-level limiter that runs before body validation) | 2026-07-03 |

## Resolved

| File:Line | Shortcut | Resolved |
|-----------|----------|----------|
| _(none yet)_ | | |

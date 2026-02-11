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
- Escalate if data mismatch persists after one controlled backfill.

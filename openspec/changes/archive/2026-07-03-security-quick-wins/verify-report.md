# Verify Report — security-quick-wins

Date: 2026-07-03
Branch checked: main (post-merge of PR #839, #840)
Verdict: **PASS**

## Test run

```
cd backend && pytest tests/unit/test_docs_gate.py tests/compras/test_wipe_compras.py \
  tests/unit/test_login_rate_limit.py tests/unit/test_exception_handler_headers.py -q
```
Result: **21 passed**, 0 failed, 0 skipped (15 warnings, all pre-existing deprecation noise unrelated to this change).

## Per-requirement results

1. **python-multipart CVE remediation** — PASS. `backend/requirements.txt:40` pins `python-multipart==0.0.32` (exact pin, not the `>=0.0.20,<0.1` range in the spec text, but satisfies the intent — 0.0.32 > 0.0.20 and is not CVE-2024-24762-affected). Documented in apply-progress as a deliberate deviation (exact pin to match installed/tested venv version). No behavior regression in the full suite.

2. **OpenAPI docs env-gate** — PASS. `backend/app/main.py:231` `_docs_urls(environment)` gates on `DEV_LIKE_ENVIRONMENTS = ("development", "testing")` (`backend/app/core/config.py:7`), spread into `FastAPI(**_docs_urls(...))` at line 253 — single gate controls all three routes together. `test_docs_gate.py` covers dev/testing/production. Fail-closed default confirmed (unset ENVIRONMENT not in the tuple).

3. **wipe-compras 404 hardening** — PASS. `require_dev_or_test()` dependency in `backend/app/api/deps.py:95`, wired via `dependencies=[Depends(require_dev_or_test)]` at the route level (`administracion_compras.py:4732`), running before `require_permiso`. `test_wipe_compras.py` includes the byte-identical-to-unknown-route 404 test plus retained 401/403/422/200 assertions.
   - **WARNING**: apply-progress notes a known tech-debt gap — a `GET` method-probe against the route still returns 405 outside dev/test, which reveals the route exists (distinguishable from a genuinely unknown route via method, though not via POST). This is tracked in `docs/tech-debt-ledger.md` per the apply-progress note; not a spec violation for the POST scenario, but flag it as unresolved residual risk.

4. **Login rate limiting** — PASS. `backend/app/core/rate_limit.py`: `Limiter(key_func=client_ip_key, swallow_errors=True, strategy="fixed-window", ...)`; `client_ip_key` prioritizes `CF-Connecting-IP` over `request.client.host`, never consults `X-Forwarded-For` (spoof-safety). 429 handler builds `Retry-After` explicitly from the configured window (final implementation uses `headers_enabled=False` + manual header construction — a cleaner approach than the `headers_enabled=True` + `response: Response` workaround originally documented in apply-progress §"Deviations"; the merged code in `auth.py` has no `response: Response` param, contradicting that section of apply-progress — see NOTE below). `@limiter.limit(settings.LOGIN_RATE_LIMIT)` applied only to `/api/auth/login`. Fail-open verified via `swallow_errors=True` and dedicated test. Test isolation via `Limiter.reset()` autouse fixture. All 8 `test_login_rate_limit.py` tests pass.
   - **NOTE (documentation drift, not a code defect)**: apply-progress.md's "Deviations from design.md" section describes an intermediate implementation (`headers_enabled=True` + `response: Response` param) that does NOT match the final merged code in `auth.py` (no `response: Response` parameter present; `rate_limit.py` comment explicitly states `headers_enabled=False`). The code that shipped is functionally correct and tested, but apply-progress was not updated to reflect the final design actually merged. SUGGESTION: correct apply-progress.md before archiving so the historical record matches shipped code.

5. **Non-goals guard** — PASS. Verified directly in `auth.py`: `/api/auth/refresh` and `/api/auth/register` have no `@limiter.limit` decorator and no rate-limit-related code. `test_login_rate_limit.py` includes the two non-goals-guard tests referenced in tasks.md 2.8.1.

## Task/code alignment

- All PR1 tasks (1.1–1.5.1) marked complete and match code.
- All PR2 tasks (2.1–2.9.1) marked complete and match code.
- 1.5.2 and 2.9.2 (opening PRs) are unchecked in tasks.md but PRs #839/#840 are confirmed merged to main per the orchestrator's context — tasks.md checkboxes are stale (cosmetic only, not a functional gap).

## Findings summary

- CRITICAL: none.
- WARNING: 1 — wipe-compras GET method-probe still reveals route existence outside dev/test (405 instead of 404); tracked in tech-debt ledger, acceptable residual risk but should stay visible.
- SUGGESTION: 2
  1. Update apply-progress.md's rate-limiter "Deviations" section to match the actually-shipped `headers_enabled=False` implementation (currently describes an abandoned intermediate approach).
  2. Spec file layout deviation: `openspec/changes/security-quick-wins/specs/security-quick-wins.md` is a flat file rather than `specs/<capability>/spec.md`. Fix at archive time for convention consistency.

## Next recommended

`sdd-archive` — no CRITICAL blockers found; the two SUGGESTIONs (doc drift, file layout) can be folded into the archive step.

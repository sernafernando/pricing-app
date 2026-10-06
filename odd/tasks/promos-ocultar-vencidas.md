# promos-ocultar-vencidas

## Objective
The promo panel must not offer expired promos as applicable. `ml_item_promotions`
is upsert-only and the external bridge can leave rows alive after ML stops
returning them (prod 2026-10-05: SELLER_CAMPAIGN rows finished 16/09 and 30/09
still showed "Aplicar").

## Approach
Defense in depth in `fetch_item_promotions(active_only=True)`: after mapping,
drop rows whose effective finish date (catalog `p.finish_date`, else payload
`finish_date`, same precedence as the returned field) is in the past. Done in
Python, not SQL: payload dates are free-form JSONB strings and a SQL cast would
crash the whole read on one malformed value. Missing/unparseable date => shown.
`active_only=False` (write reconciliation) is untouched.

## Tasks
- [x] T1 RED: tests for expired catalog/payload, future, no date, catalog precedence, malformed date, active_only=False (4 failed, 9 guards passed)
- [x] T2 GREEN: `_is_expired_finish_date` + filter in `fetch_item_promotions`
- [x] T3 ruff format/check clean
- [x] T4 RED (9/9 failed, real Postgres): `tests/unit/test_ml_promotions_expiry_postgres.py`
- [x] T5 GREEN: shared `_PROMO_NOT_EXPIRED_SQL` + `_PROMO_CATALOG_JOIN_SQL` applied to `fetch_promo_summary_by_mla`, `fetch_promo_node_summary_by_mla`, `fetch_mlas_with_active_promo_type`, `fetch_mlas_by_promo_name`, `fetch_mlas_with_started`, `fetch_mlas_with_candidate_only`, `fetch_mlas_with_candidate_only_for_types`

## Mode
TDD: enabled (project config), runner `backend/.venv/bin/pytest`. Route: delegated direct writer.

## Evidence
- `pytest tests -k promo -q`: 522 passed
- `ruff format --check app/ tests/` / `ruff check app/`: clean

## Set-based readers (second commit)
One SQL predicate, `(p.finish_date IS NULL OR p.finish_date >= NOW())`, with a
LEFT JOIN to `ml_promotions p`. It uses ONLY the typed catalog column: the
catalog carries dates for SELLER_CAMPAIGN/DEAL (the reported case). Payload-only
dates (e.g. SMART) are NOT covered in SQL, because casting the free-form payload
string could crash a whole set-based read on one bad value; they stay covered by
the panel's Python filter and the bridge fix (ml-webhook PR #2). No catalog row
or NULL finish => kept. The join cannot duplicate rows: `ml_promotions.promotion_id`
is the primary key (service docstring, verified live; existing joins rely on it).
Side effect: an expired `started` row no longer disqualifies `candidate_only`.
Tests run on the local Postgres (`POSTGRES_TEST_URL` default) in a throwaway schema.

## Not changed
`scripts/sync_promo_prices.py::_fetch_newly_active_rows`: a change-detection
trigger (rows activated since a watermark), not display/selection. Filtering
there would only skip recomputes; `recompute_item` already ignores expired rows.

## Commit
See `git log` on branch `fix/promos-ocultar-vencidas` (work-unit commit).

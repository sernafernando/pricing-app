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

## Mode
TDD: enabled (project config), runner `backend/.venv/bin/pytest`. Route: delegated direct writer.

## Evidence
- `pytest tests -k promo -q`: 522 passed
- `ruff format --check app/ tests/` / `ruff check app/`: clean

## Out of scope (reported, not changed)
Other status-only promo queries in `ml_promotions_service.py`
(`fetch_promo_summary_by_mla`, node summary, `fetch_mlas_*`, filter resolvers).

## Commit
See `git log` on branch `fix/promos-ocultar-vencidas` (work-unit commit).

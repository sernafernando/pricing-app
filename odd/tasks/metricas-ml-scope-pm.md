# Métricas ML board: scope PMs and sub-PMs to their own brands

## Objective

On the new Métricas ML board (`/ml-metricas/*`), a PM or sub-PM sees only the
(marca, categoría) pairs they own, exactly like the old ML metrics dashboard.
Full-view users (SUPERADMIN/ADMIN/GERENTE role or `ventas_ml.ver_todas_marcas`)
keep seeing everything. PRICING and VENTAS roles (the roles that open the old
dashboard through `ventas_ml.ver_dashboard`) get access to the new board.

## Problem

- `backend/app/routers/ml_metricas.py` gates only on `ml_metricas.ver`; once in,
  every user sees every brand. There is no per-user scope.
- `ml_metricas.ver` / `ml_metricas.ver_ganancia` were seeded only for ADMIN and
  GERENTE (`20261001_ml_metricas_permisos.py`), so PMs cannot open the board.
- The `pms` board filter resolves pairs from `marcas_pm` only and is a UI
  filter, not a security boundary.

## Why

The old dashboard (`dashboard_ml.py`) applies `pm_scope.aplicar_filtro_marcas_pm`
to every endpoint. PMs need the same view on the new board before the old one
can be retired. `pm_scope` stays the single source of the rule.

## Decisions

- **Scope source:** `pm_scope.get_pares_marca_categoria_usuario` (union of
  `marcas_pm` + `marca_sub_pm`, uppercased; `[]` for inactive users; `None`
  for full view). No duplicated rule.
- **Injection point:** the per-item base (`Board._pair_source`, join to
  `productos_erp`), so rows, KPIs, group nodes (every level), facets, product
  publications and the CSV export are all bounded at once. Pairs without a
  product (NULL marca) are excluded for scoped users (fail-closed).
- **Scope travels outside `BoardFilter`:** it is resolved server-side from
  `current_user` and passed to `Board(...)`, never parsed from the query.
- **"View as PM X":** the existing `pms` filter already intersects with the
  user's scope, so a PM selecting another PM gets nothing (no escalation) and a
  full-view user selecting PM X sees X's brands. No second `pm_ids` knob.
- **Margins (user decision 2026-10-06):** PMs see margins, like the old
  dashboard (which never gated `total_ganancia`/`markup_porcentaje`). PRICING
  and VENTAS get both `ml_metricas.ver` and `ml_metricas.ver_ganancia`.

## Scope

- `backend/app/services/ml_daily_metrics/board.py` — `Board` accepts the scope
  pairs and filters the base.
- `backend/app/routers/ml_metricas.py` — resolve the scope once per request and
  pass it to every `Board` (board, publications, group-nodes, export pages).
- `backend/alembic/versions/20261006_ml_metricas_permisos_pm.py` — grant both
  permissions to PRICING and VENTAS.
- Tests under `backend/tests/services/ml_daily_metrics/`,
  `backend/tests/integration/`, `backend/tests/unit/`.

## Constraints

- Strict TDD: observed RED before each fix.
- Postgres-level tests where SQL is involved (`@pytest.mark.postgres`).
- Statement ceiling (`test_board_volume_postgres.py`) must hold.
- Temp tables stay inside the always-rolled-back SAVEPOINT.

## TDD

- Mode: enabled (source: user global instructions "Strict TDD Mode: enabled").
- Runner: `backend/.venv/bin/pytest` from `backend/`; Postgres at
  `localhost:5432` (`POSTGRES_TEST_URL` default).

## Tasks

- [x] **T1 — Board scope filter (service).** `Board(..., scope_pairs=None)`;
  `None` = no filter, `[]` = nothing, list = `(UPPER(marca), UPPER(categoria))
  IN pairs` in the base. Postgres tests: rows, KPIs, facets (marca, categoría,
  subcategoría, PM, tienda), every group level, product publications,
  through_leaves export keys; empty scope → nothing; ceiling unchanged.
  Route: delegated (writer trigger: 2+ non-trivial files).
- [x] **T2 — Router wiring.** Resolve scope from `current_user` with
  `pm_scope`; pass to every `Board`. Integration tests per endpoint: PM sees
  only own, sub-PM union, admin all, no pairs → nothing, PM with `pms` of
  another PM → nothing, admin with `pms`=X → X's scope, CSV and every group
  level scoped. Route: delegated (same writer).
- [x] **T3 — Permissions migration.** Grant `ml_metricas.ver` and
  `ml_metricas.ver_ganancia` to PRICING and VENTAS following the
  `20261001_ml_metricas_permisos.py` pattern; unit test. Route: delegated.

## Acceptance criteria

- Every `/ml-metricas` endpoint is bounded by the caller's pm_scope.
- No path lets a scoped user widen their scope through query params.
- PRICING/VENTAS users can open the board and see margins.

## Checks

- Tests of the change + affected suites (`tests/services/ml_daily_metrics`,
  `tests/integration/test_ml_metricas_*`, `tests/services/test_pm_scope.py`,
  migration unit test).
- `ruff format --check app/ tests/` and `ruff check app/`.

## Progress

- 2026-10-06: branch `feat/metricas-ml-scope-pm` from `origin/main` (aaac3e92).
  Exploration done; margins decision taken.
- T1 done. RED: `pytest tests/services/ml_daily_metrics/test_board_pm_scope_postgres.py`
  -> 12 failed, `TypeError: Board.__init__() got an unexpected keyword argument
  'scope_pairs'`. GREEN: 12 passed; `tests/services/ml_daily_metrics` 179 passed
  (statement ceiling test unchanged). Route: delegated writer (one writer for
  T1-T3). Commit: `feat(ml-metricas): scope the board base to the caller's PM pairs`.
- T2 done. RED: `pytest tests/integration/test_ml_metricas_board_scope_router.py`
  -> 13 failed / 8 passed, e.g. `assert {'11', '12', '13', '14'} == {'11'}` (a PM
  saw every brand). GREEN: 21 passed; the 3 existing router files still pass
  (`ML_USER_ID=999` needed locally for the sales fixtures). Test placement:
  router tests run on the SQLite suite (scope SQL is dialect-neutral); the
  Postgres side is covered by T1's test. Commit: `feat(ml-metricas): bound every
  board endpoint by the caller's PM scope`.
- T3 done. RED: `pytest tests/unit/test_migration_ml_metricas_permisos_pm.py`
  -> 4 failed (`Can't locate revision identified by
  '20261006_ml_metricas_permisos_pm'`, head still `20261006_ml_publications_core`).
  GREEN: 4 passed (single head, grants, idempotent upgrade, downgrade scoped to
  the two role grants). Commit: `feat(ml-metricas): grant the board to the PRICING
  and VENTAS roles`.

## Next step

All tasks done; ready for review, push and PR (user decision).

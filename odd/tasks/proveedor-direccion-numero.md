# Proveedor dirección: número separado

## Objective
Split street number out of `proveedor_direcciones.direccion` so pickup labels
(`etiqueta_retiro_service`) fill `manual_street_number` instead of leaving it
empty and forcing depósito to edit by hand.

## Scope
- Alembic migration: add `numero VARCHAR(50) NULL` + backfill by regex (preview
  run on prod 2026-10-09: 10/10 rows OK, none ambiguous).
- Model, schemas (`DireccionResponse`, `DireccionCreate`) in administracion_proveedores.
- `etiqueta_retiro_service`: copy `numero` → `manual_street_number`.
- Frontend `AdministracionProveedores.jsx` DireccionesSection: "Número" input + display.
- Test RED first on retiro service.

## Constraints
- Rows not matching the regex stay untouched (`numero` NULL).
- Branch: `fix/proveedor-direccion-numero` off origin/main.

## Tasks
- [x] T1 Backend: migration + model + schemas + retiro service + tests (route: delegated, writer trigger: 3+ non-trivial files)
- [x] T2 Frontend: Número input + display (route: same writer)

## Delivery
Strategy: single-pr (forecast < 400 lines).

## Progress / Evidence
- Commit: `f01aa606` fix(proveedores): separar número de calle en direcciones de proveedor (T1+T2).
- RED 1: fixture `numero="742"` → `TypeError: 'numero' is an invalid keyword argument for ProveedorDireccion` (8 errors).
- RED 2 (model added, service untouched): `AssertionError: assert None == '742'` on `manual_street_number` (1 failed, 9 passed).
- GREEN: `pytest tests/unit/test_etiqueta_retiro_service.py -q` → 10 passed.
- `ruff format --check` on changed files + `ruff check` → clean; pre-commit hook passed.
- `pnpm exec eslint src/pages/AdministracionProveedores.jsx` → exit 0.
- `alembic heads` → single head `20261015_proveedor_direccion_numero` (down_revision `20261014_ml_ads_account_level`).
- Backfill SQL not executed locally (no Postgres); regex sanity-checked with Python `re` on samples.
- Novedades: not added — README excludes bugfixes.
- Parent: `ModalCargarRetiro.jsx` picker label now appends `numero` (same endpoint returns it); eslint OK; retiro tests re-run 10 passed.

## Next step
Parent: decide novedades entry, run RDD assess on `f01aa606`, then PR.

# pm-scope full-view: read the live role and honour the permission

## Objective

Make `pm_scope.is_full_view()` grant unfiltered brand access when EITHER the
user's live role is a full-view role OR the user holds the
`ventas_ml.ver_todas_marcas` permission.

## Problem

`backend/app/services/pm_scope.py:36` decides full-view access with:

```python
return usuario.rol in FULL_VIEW_ROLES
```

Two defects:

1. **Reads the deprecated column.** `Usuario.rol` is marked DEPRECATED in the
   model; the live role is `rol_id` -> `rol_obj.codigo`, exposed by the
   `Usuario.rol_codigo` property. Accounts created through the current admin UI
   are written with `rol_id` only and leave `rol` NULL, so `is_full_view()`
   returns False for them regardless of their actual role.
2. **The permission is never read.** `ventas_ml.ver_todas_marcas` exists in the
   `permisos` table and is assigned to the GERENTE role, but no code path in
   the repository references it. Granting it changes nothing.

Observed in production: of three GERENTE accounts, only the one with the legacy
`rol` column populated sees all brands. The other two fall through to the
per-assignment filter and land on the `__NINGUNA__` sentinel
(`pm_scope.py:122`), returning either their single assigned brand or zero rows.

## Scope

- `backend/app/services/pm_scope.py` — `is_full_view()` and its two internal
  call sites.
- `backend/app/api/endpoints/ventas_ml.py` — `get_pares_marca_cat_usuario_ventas()`
  carries a divergent inline copy of the same role check; it is repointed at
  `is_full_view()` so the permission is honoured there too.
- `backend/tests/services/test_pm_scope.py` — new cases.

Out of scope: the `marca_sub_pm` omission in `ventas_ml.py`'s own pair lookup,
and `consultas.py::_scope_user_id` (gated on `consultas.ver_ranking`, a
separate contract).

## Constraints

- `is_full_view()` keeps `db` optional so existing callers and tests that pass
  only the user keep working; without a session the permission check is skipped
  and the role check alone decides.
- The permission check must not add queries on the hot path: `tiene_permiso()`
  reads the `_permisos_cache` that `get_current_user` preloads.
- No behaviour change for users who already have full view.

## TDD

Strict TDD is enabled for this repository. Runner: `.venv/bin/pytest` from
`backend/`. Every task observes RED before the implementation lands.

## Tasks

- [x] T1 — RED: tests for a user with `rol=None` and `rol_id` pointing at a
      full-view role, and for a non-full-view user holding
      `ventas_ml.ver_todas_marcas`. Both must fail against current code.
- [x] T2 — GREEN: `is_full_view(usuario, db=None)` reads `rol_codigo` and falls
      back to the permission check; update the two internal call sites to pass
      `db`.
- [x] T3 — GREEN: repoint `ventas_ml.get_pares_marca_cat_usuario_ventas()` at
      `is_full_view()`.
- [x] T4 — Full `test_pm_scope.py` + `test_dashboard_ml_pm_ids_gate.py` green,
      `ruff format app/` clean, commit, PR against `main`.

## Acceptance criteria

- A user whose only role source is `rol_id` = GERENTE gets full view.
- A VENTAS user granted `ventas_ml.ver_todas_marcas` gets full view.
- A VENTAS user without that permission keeps the per-assignment filter.
- Pre-existing tests in `test_pm_scope.py` stay green unchanged.

## Delivery

Single PR against `main`; well under the 400-line budget. Strategy:
`ask-on-risk`.

## Progress

- T1 RED observed: 5 new cases in `test_pm_scope.py` failed against the old
  code (`TypeError: is_full_view() takes 1 positional argument but 2 were
  given` plus the role assertions), 16 pre-existing cases stayed green. Two
  further cases in the new `test_ventas_ml_full_view.py` failed while its
  regression case already passed.
- T2/T3 GREEN: `pytest tests/services/test_pm_scope.py
  tests/services/test_ventas_ml_full_view.py
  tests/services/test_dashboard_ml_pm_ids_gate.py` -> 26 passed.
- T4: `pytest tests/services/ tests/api/test_marcas_pm_sub_pm.py
  tests/api/test_marcas_pm_sub_pm_bulk_scope.py
  --ignore=tests/services/tn_image_normalizer` -> 1601 passed.
  `ruff format app/ tests/` and `ruff check app/ tests/` clean.

## Known environmental failures

`tests/services/tn_image_normalizer/test_engine.py` fails to collect on this
machine with `ModuleNotFoundError: No module named 'PIL'`. Pre-existing and
unrelated to this change; excluded from the run above. `google-genai` was
likewise missing from the local venv and had to be installed before the suite
could be collected at all.

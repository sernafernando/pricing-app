# Spec Index — dashboard-tplink-vista-marca

> Change: `dashboard-tplink-vista-marca`
> Status: spec-complete

## Sub-specs

| Spec | File | Covers |
|------|------|--------|
| Permission model | `permissions/spec.md` | Two new permission codes, migration seeding, role assignment, route gate, margin gate |
| Server-side store lock | `store-lock/spec.md` | Hard-lock to store 2645, rejection of client params, isolation from shared router |
| Brand API surface | `api-surface/spec.md` | Six `/dashboard-tplink/*` endpoints, request params, response models, margin-gated fields, offset absence |
| Frontend view | `frontend-view/spec.md` | Page structure, route, sidebar entry, Resumen tab, Detalle tab, filters, TP-Link branding |

## Non-Goals (explicit out of scope)

- Rentabilidad tab
- Any offset field (offset_flex, rendimientos offsets) in any endpoint or UI surface
- Store switching or PM/marca selectors
- Fixing the pre-existing auth-only gap on `/dashboard-ml/*` endpoints
- Self-service brand user provisioning UI
- Export (Excel/CSV) in v1

## Testability Notes

- Backend (pytest, `cd backend && pytest tests/ -v --tb=short`): every acceptance
  scenario in `permissions/spec.md`, `store-lock/spec.md`, and `api-surface/spec.md`
  is directly expressible as a pytest test using an in-process test client and
  fixture users with controlled permission sets.
- Frontend: no test runner. Verify manually against the scenarios in
  `frontend-view/spec.md`.

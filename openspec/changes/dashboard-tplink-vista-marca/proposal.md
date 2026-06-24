# Proposal: TP-Link Brand-Facing Dashboard (Restricted Brand View)

> Change: `dashboard-tplink-vista-marca`
> Clone `DashboardMetricasML.jsx` into a NEW brand-facing page handed to TP-Link
> (an external brand). TP-Link logs in with a RESTRICTED account that can reach
> ONLY this page, hard-locked server-side to the TP-Link official store
> (`tienda_oficial=2645`), with margin data gated behind a second permission.

## Why

We want to give the TP-Link brand a self-service metrics view of THEIR official
store's MercadoLibre performance without granting access to the rest of the
internal dashboard (which exposes every store: Gauss, Forza, multi-marca, etc.).

The existing `/dashboard-ml/*` endpoints today only require authentication
(`Depends(get_current_user)`) — there is **no per-endpoint permission check** and
the store filter `tiendas_oficiales` is a **free client query param** applied
straight into the SQL filter (`dashboard_ml.py:78-105, 236`). So a brand user who
edits `?tiendas_oficiales=57997` would see Gauss data. The page guard
(`ProtectedRoute permiso=...`) is frontend-only and does not protect the data.

Success =
1. A brand can log in, land ONLY on the TP-Link page, and see ONLY TP-Link store
   data — even if they tamper with the query string.
2. Sensitive margin data (ganancia $, markup %, costos, comisiones) is masked with
   `***` unless a second permission is explicitly granted, mirroring the existing
   `ventas_ml.ver_ganancia` masking already used in `DashboardMetricasML.jsx:~28`.
3. No offsets are ever shown; no store/PM/marca switching is possible.

## What Changes

### Confirmed decisions (product owner — encode, do NOT reopen)

1. **Two new granular permissions**, mirroring `ventas_ml.ver_ganancia`:
   - `dashboard_tplink.ver` → page access + non-sensitive data (facturación,
     unidades, ops, top productos, ventas por día/categoría/logística).
   - `dashboard_tplink.ver_ganancia` → unlocks margin data **as a group**
     (ganancia $, markup %, costos, comisiones). Absent → masked with `***`.
2. **Store hard-locked to `tienda_oficial=2645` ENFORCED SERVER-SIDE.** The brand
   view's data must force store 2645 and ignore/reject any client-supplied store
   filter. The frontend filter is NOT the boundary.
3. **Offsets excluded ALWAYS** (no permission unlocks them): remove Offset Flex
   from KPIs/metricsRow, the operaciones table column, and logística offset. The
   Rentabilidad tab (where rendimientos offsets live, `TabRentabilidad.jsx`) is
   simply NOT part of this view.
4. **Tabs:** Resumen + Detalle de Operaciones only. NO Rentabilidad tab. Drop
   offset columns from the operaciones table; keep margin columns gated by
   `dashboard_tplink.ver_ganancia`.
5. **Filters:** date range + categoría ONLY. No store selector (TP-Link fixed),
   no PMs, no marca selector.
6. **Aesthetic:** TP-Link branding (corporate accent, logo, own title) built on
   the existing Tesla Design System / CSS Modules (design tokens only — no
   Tailwind, no inline styles), scoped without forking the design system.
7. **Delivery:** work on `develop`; PR to `main` closes the change.

### Server-side store-lock approach (recommended + rejected)

**Recommended — Dedicated brand endpoints (`/dashboard-tplink/*`).** New router
that reuses the existing `aplicar_filtros_comunes` helpers but (a) requires
`tienda_tienda.tiene_permiso(user, "dashboard_tplink.ver")` → 403 otherwise, and
(b) **forces `tiendas_oficiales="2645"` internally**, never reading it from the
request. `pm_ids` and `marcas` params are not exposed. Margin fields in the
response/aggregation respect `dashboard_tplink.ver_ganancia`.

*Why:* the store lock and permission gate live in ONE place, decoupled from the
shared internal endpoints; no risk of a refactor on `/dashboard-ml/*` leaking the
brand scope. Boring, explicit, testable.

**Rejected — Reuse `/dashboard-ml/*` with a permission-derived store scope
injected as a dependency.** Would mean threading a "scope" object through every
shared endpoint and trusting that no future param re-opens the store filter. More
coupling, larger blast radius, harder to prove the lock holds. Not worth it for
one brand view.

## Scope / Non-Goals

### In Scope (v1)
- Alembic migration seeding `dashboard_tplink.ver` + `dashboard_tplink.ver_ganancia`
  in `permisos`, assigned to ADMIN/GERENTE (internal visibility); the brand user
  gets `dashboard_tplink.ver` via override and optionally `*.ver_ganancia`.
- New backend router `/dashboard-tplink/*` (clone the read endpoints needed by the
  page): permission gate + forced store 2645 + margin masking server-side.
- New frontend page (clone of `DashboardMetricasML.jsx`) with Resumen + Detalle
  tabs only, date + categoría filters, TP-Link theming, `***` margin masking.
- New route in `App.jsx` guarded by `ProtectedRoute permiso="dashboard_tplink.ver"`.
- Sidebar/menu entry gated by `dashboard_tplink.ver`.
- TP-Link brand theming scoped via a CSS-Modules variant / token override (no
  design-system fork).

### Out of Scope (explicit non-goals)
- **Rentabilidad tab** — not included.
- **Offsets** (Offset Flex + rendimientos offsets) — removed everywhere, no
  permission unlocks them.
- **Store switching** — TP-Link fixed; no store selector.
- **PM filter / marca selector** — not exposed.
- Changing the existing internal `DashboardMetricasML.jsx` or `/dashboard-ml/*`
  behavior.
- Self-service brand user provisioning (the account is created/granted manually).

## Capabilities

### New Capabilities
- `dashboard-tplink-brand-view`: brand-facing TP-Link dashboard — restricted
  account access, server-side store lock to 2645, two-permission margin gating,
  Resumen + Detalle tabs, no offsets, brand theming.

### Modified Capabilities
- None. The internal ML dashboard and shared `/dashboard-ml/*` endpoints are left
  untouched; this change is additive (new permissions, new router, new page).

## Approach

Clone-and-restrict. Reuse the existing query helpers and metric schemas, but serve
the brand through a NEW router whose store scope is hardcoded and whose access is
permission-gated, and a NEW page that omits the Rentabilidad tab, offsets, and the
store/PM/marca filters. Margin masking is enforced BOTH server-side (don't ship
the numbers) and frontend-side (`***`) so the data boundary does not depend on the
client. Boring tech: Postgres + the existing hybrid permission system; no new
infra.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/alembic/versions/{date}_dashboard_tplink_permisos.py` (new) | New | Seed `dashboard_tplink.ver` + `dashboard_tplink.ver_ganancia`, assign to internal roles |
| `backend/app/api/endpoints/dashboard_tplink.py` (new) | New | Brand router: permission gate + forced store 2645 + server-side margin masking |
| `backend/app/main.py` | Modified | Register the new router |
| `frontend/src/pages/DashboardTPLink.jsx` (new) | New | Cloned page: Resumen + Detalle, no offsets, date+categoría filters, `***` masking |
| `frontend/src/pages/DashboardTPLink.module.css` (new) | New | TP-Link brand theming via token override (no Tailwind/inline) |
| `frontend/src/App.jsx` | Modified | New route `ProtectedRoute permiso="dashboard_tplink.ver"` |
| `frontend/src/components/Sidebar.jsx` | Modified | Menu entry gated by `dashboard_tplink.ver` |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| **Exposing ganancia/markup/costos to an external brand is sensitive negotiation data** | High | DECISION TO RECONFIRM AT DESIGN TIME. Cheap fallback: do NOT grant `dashboard_tplink.ver_ganancia` to the brand user — page works fully with margins masked |
| Brand user tampers query string to reach other stores | High | Dedicated endpoints force store 2645 server-side; `tiendas_oficiales`/`pm_ids` not read from request; covered by backend tests |
| Existing `/dashboard-ml/*` endpoints have no permission check (auth-only) | Med | Out of scope to fix here, but the NEW brand endpoints DO gate by permission; note as a follow-up audit item |
| Brand theming forks/pollutes the shared design system | Low | Scope theming to a CSS-Modules variant + token override; no edits to `design-tokens.css` shared values |
| Margin masking inconsistent between FE and BE | Med | Enforce server-side (omit/zero margin fields when permission absent) AND `***` in FE; tests assert the server response |

## Testability

Strict TDD is active for backend (`cd backend && pytest tests/ -v --tb=short`).
Frontend has no test runner — verify the page manually. Backend behaviors that
MUST have tests:
- `dashboard_tplink.ver` required → 403 without it, 200 with it.
- Server-side store lock: response only contains store-2645 data even when the
  request supplies `?tiendas_oficiales=57997` (param ignored/rejected).
- Margin gating: with `dashboard_tplink.ver_ganancia` absent, margin fields are
  masked/omitted server-side; present → real values.
- SUPERADMIN still resolves (has all permissions).

## Rollback Plan

Additive and isolated. To revert: `alembic downgrade -1` (drops the two
permissions + role/override links), unregister the new router in `main.py`, remove
the new page/route/sidebar entry. No shared endpoint or existing page is modified,
so rollback cannot regress the internal dashboard.

## Dependencies

- Existing hybrid permission system (`permisos`, `roles_permisos_base`,
  `usuarios_permisos_override`, `PermisosService.tiene_permiso`).
- Existing `MLVentaMetrica` + `MercadoLibreItemPublicado.mlp_official_store_id`
  linkage and the `aplicar_filtros_comunes` helpers in `dashboard_ml.py`.
- TP-Link official store id confirmed = `2645` (per `dashboard_ml.py:84-87`).

## Success Criteria

- [ ] Brand account with `dashboard_tplink.ver` lands ONLY on the TP-Link page.
- [ ] All brand data is store-2645 only, proven even under query-string tampering.
- [ ] Margins masked with `***` unless `dashboard_tplink.ver_ganancia` is granted.
- [ ] No offsets and no Rentabilidad tab anywhere in the view.
- [ ] Only date + categoría filters; no store/PM/marca selectors.
- [ ] Backend tests pass for permission gate, store lock, and margin gating.

## Next Phase

`sdd-spec` and `sdd-design` (can run in parallel). Spec formalizes the
requirements (two-permission contract, server-side store lock, margin masking
rules, excluded surfaces). Design decides the exact router/endpoint set to clone,
the server-side masking shape (omit vs zero), the theming token-override
mechanism, and reconfirms the sensitive-margin disclosure decision.

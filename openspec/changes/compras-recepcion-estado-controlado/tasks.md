# Tasks — compras-recepcion-estado-controlado

**Change:** compras-recepcion-estado-controlado
**Phase:** tasks
**Date:** 2026-06-24
**Strict TDD:** enabled (`cd backend && source venv/bin/activate && pytest tests/ -v --tb=short`)
**Slices:** Slice A = Backend (T01–T14) · Slice B = Frontend (T15–T19, depends on T01–T14 merged)

---

## Execution Order

```
T01 → T02 → T03
              ↓
T04 → T05 → T06 → T07 (tests, TDD red — written before/with implementation)
              ↓
T08 → T09 → T10 → T11 → T12 → T13 → T14 (green — impl makes tests pass)
                                            ↓
                                     T15 → T16 → T17 → T18 → T19
```

Sequential within each group. T04–T07 (test stubs) can be written in parallel with T02–T03 once T01 is done.

---

## Slice A — Backend

### Group 1: Data model + migration

- [ ] **T01** — Create Alembic migration `20260624_recepcion_estado_controlado.py`
  - **File:** `backend/alembic/versions/20260624_recepcion_estado_controlado.py`
  - **down_revision:** `"20260623_permiso_reescribir_lh"`
  - **upgrade():** (1) `UPDATE pedidos_compra SET estado='controlado' WHERE estado='recibido'` — BEFORE constraint swap; (2) `DROP CONSTRAINT IF EXISTS ck_pedidos_compra_estado`; (3) `ADD CONSTRAINT ck_pedidos_compra_estado CHECK (estado IN ('borrador','pendiente_aprobacion','aprobado','rechazado','cancelado','pagado_parcial','pagado','recibido','con_faltantes','controlado'))`
  - **downgrade():** DROP constraint; ADD prior 9-state constraint (without `controlado`); docstring MUST note data is one-way (downgrade does not restore `recibido` semantics)
  - **Satisfies:** REQ-EC-008
  - **Depends on:** none (first task)

- [ ] **T02** — Add `controlado` to `CheckConstraint` literal in model
  - **File:** `backend/app/models/pedido_compra.py` L144-148
  - Append `'controlado'` to the `IN (…)` list in the SQLAlchemy `CheckConstraint`
  - **Satisfies:** REQ-EC-011 (model layer)
  - **Depends on:** T01 (migration establishes schema contract)

- [ ] **T03** — Add `"controlado"` to `ESTADOS_PEDIDO` in schema
  - **File:** `backend/app/schemas/pedido_compra.py` L19-29
  - Append `"controlado"` to the `ESTADOS_PEDIDO` tuple/literal
  - **Satisfies:** REQ-EC-011 (Pydantic layer)
  - **Depends on:** T01

---

### Group 2: TDD — write failing tests first (before or alongside service changes)

- [ ] **T04** — RENAME + INVERT: terminal guard tests
  - **File:** `backend/tests/integration/test_recepcion_deposito_endpoints.py`
  - Rename `test_validar_estado_receptivo_rechaza_recibido` → `test_validar_estado_receptivo_rechaza_controlado`; change assertion: `controlado` → 409, `recibido` → ACCEPTED (201 or allowed)
  - Rename `test_state_recibido_rechaza_ingreso_409` → `test_state_controlado_rechaza_ingreso_409`; change fixture estado from `recibido` to `controlado`
  - Add new sibling: `test_state_recibido_acepta_ingreso_201` — asserts HTTP 201 on `POST /ingresos` when estado=recibido
  - **Satisfies:** REQ-EC-012 (INVERT cluster), REQ-EC-001 (controlado→409), REQ-EC-002 (recibido accepts)
  - **Depends on:** T01, T02, T03 (schema must know `controlado` for fixtures to build)

- [ ] **T05** — INVERT: `recalcular_estado` all-zero test
  - **File:** `backend/tests/integration/test_recepcion_deposito_endpoints.py`
  - Rename `test_recalcular_estado_todos_cero_da_recibido` → `test_recalcular_estado_todos_cero_da_controlado`; assert `estado_nuevo == "controlado"` (not `"recibido"`)
  - Rename/invert `complete_batch_da_recibido` → `complete_batch_da_controlado`; assert `controlado`
  - Rename/invert `test_ingresos_201_complete` → assert estado=`controlado` in response
  - **Satisfies:** REQ-EC-012 (INVERT cluster), REQ-EC-002 (control step CON-OC)
  - **Depends on:** T04

- [ ] **T06** — INVERT: SIN-OC control step tests
  - **File:** `backend/tests/integration/test_recepcion_deposito_endpoints.py`
  - Rename/invert `test_confirmar_sin_oc_completo_true_da_recibido` → `…completo_true_en_estado_recibido_da_controlado`; fixture must set pedido to estado=`recibido` before calling; assert `controlado`
  - Verify any other SIN-OC test referencing old terminal `recibido` and invert
  - **Satisfies:** REQ-EC-012 (INVERT cluster), REQ-EC-003 (recibido→controlado SIN-OC)
  - **Depends on:** T04

- [ ] **T07** — NEW tests: full state machine transitions
  - **File:** `backend/tests/integration/test_recepcion_deposito_endpoints.py`
  - Add tests (all initially failing — TDD red):
    1. `test_pagado_arrival_sin_oc_da_recibido` — POST /confirmar-pedido on estado=pagado; assert estado=recibido, event=recepcion_arribo, no ingresos row created (REQ-EC-003)
    2. `test_pagado_arrival_con_oc_da_recibido` — POST /confirmar-pedido on pagado CON-OC; assert estado=recibido, event=recepcion_arribo, no ingresos line (REQ-EC-002)
    3. `test_recibido_to_controlado_sin_oc` — POST /confirmar-pedido on estado=recibido, completo=true; assert estado=controlado (REQ-EC-003)
    4. `test_recibido_to_con_faltantes_sin_oc` — POST /confirmar-pedido on recibido, completo=false+obs; assert con_faltantes (REQ-EC-003)
    5. `test_con_faltantes_to_controlado_sin_oc` — POST /confirmar-pedido on con_faltantes, completo=true; assert controlado (REQ-EC-003)
    6. `test_controlado_rejects_confirmar_409` — POST /confirmar-pedido on controlado; assert 409 (REQ-EC-001, REQ-EC-003)
    7. `test_migration_accepts_controlado` — direct DB insert estado=controlado succeeds; insert estado='en_camino' rejected (REQ-EC-008)
    8. `test_saldo_recibido_200` — GET /saldos on recibido; assert 200 (REQ-EC-009)
    9. `test_saldo_controlado_200` — GET /saldos on controlado; assert 200 audit (REQ-EC-009)
  - **Satisfies:** REQ-EC-012 (new tests cluster)
  - **Depends on:** T04, T05, T06

---

### Group 3: Service implementation (makes red tests green)

- [ ] **T08** — Update `_ESTADOS_RECEPTIVOS` set
  - **File:** `backend/app/services/recepcion_service.py` L50
  - Change `_ESTADOS_RECEPTIVOS = {"pagado", "con_faltantes"}` → `{"pagado", "recibido", "con_faltantes"}`
  - **Satisfies:** REQ-EC-001 (recibido is now receptive)
  - **Depends on:** T04 (test written first)

- [ ] **T09** — Invert terminal guard in `_validar_estado_receptivo`
  - **File:** `backend/app/services/recepcion_service.py` L58-74
  - Change guard: reject `"controlado"` (409 "Pedido already controlled") instead of `"recibido"`. The `recibido` case falls through to normal receptive logic.
  - **Satisfies:** REQ-EC-001, REQ-EC-012 (INVERT terminal guard)
  - **Depends on:** T08

- [ ] **T10** — Update `recalcular_estado`: all-zero → `controlado`
  - **File:** `backend/app/services/recepcion_service.py` L199-215
  - Replace `"recibido"` with `"controlado"` as the all-zero outcome. `con_faltantes` branch unchanged.
  - Update event branch at L336: event `recepcion_registrada` now maps to `controlado` (not `recibido`)
  - **Satisfies:** REQ-EC-002 (CON-OC control step), REQ-EC-012 (INVERT recalcular)
  - **Depends on:** T09

- [ ] **T11** — Add arrival branch to `confirmar_pedido_sin_oc` + new event `recepcion_arribo`
  - **File:** `backend/app/services/recepcion_service.py` L399-461
  - Implement D-SINOC truth table: if `pedido.estado == "pagado"` → ARRIVAL path (`estado_nuevo="recibido"`, emit `recepcion_arribo`, write sentinel row, ignore `completo`). Else if `estado in {"recibido","con_faltantes"}` → CONTROL path (existing completo→controlado/con_faltantes logic). Else → 409.
  - Add `"recepcion_arribo"` to event-type filter at L485
  - **Satisfies:** REQ-EC-003, REQ-EC-001 (SIN-OC full truth table)
  - **Depends on:** T10

- [ ] **T12** — Add CON-OC arrival path: `confirmar_arribo_con_oc` helper (or fold into shared `_transicionar`)
  - **File:** `backend/app/services/recepcion_service.py` (new helper or expansion of existing)
  - State-only `pagado→recibido` transition for CON-OC: no `registrar_ingresos` call; writes estado=recibido + event=`recepcion_arribo`
  - **Satisfies:** REQ-EC-002 (CON-OC arrival), D-CONOC resolution
  - **Depends on:** T11

---

### Group 4: Endpoint routing

- [ ] **T13** — Update `confirmar-pedido` endpoint to route arrival/control by estado (both paths)
  - **File:** `backend/app/routers/administracion_compras.py` L4959+
  - For CON-OC path: if estado=pagado → call arrival helper (T12); else → existing control flow
  - For SIN-OC path: delegates to updated `confirmar_pedido_sin_oc` (T11) which already handles routing
  - **Satisfies:** REQ-EC-002, REQ-EC-003
  - **Depends on:** T11, T12

- [ ] **T14** — Verify saldo-visibility guard at L4917 (no-op or confirm unchanged)
  - **File:** `backend/app/routers/administracion_compras.py` L4917
  - Confirm the saldo-set is `{pagado, recibido, con_faltantes, controlado}` per REQ-EC-009. Design note: `recibido` was already present; add `controlado` for audit access.
  - **Satisfies:** REQ-EC-009
  - **Depends on:** T13

---

## Slice B — Frontend (depends on Slice A merged)

- [ ] **T15** — Update `FILTER_TABS` to 4 tabs + `?estado=` mapping
  - **File:** `frontend/src/components/compras/TabRecepcionDeposito.jsx` L18-22, L536-540
  - Replace existing tabs with: `[{label:"Por recibir", estado:"pagado"}, {label:"Recibidos sin controlar", estado:"recibido"}, {label:"Controlados", estado:"controlado"}, {label:"Con faltantes", estado:"con_faltantes"}]`
  - Update `?estado=` query param mapping at L536-540 to use each tab's `estado` value
  - **Satisfies:** REQ-EC-005
  - **Depends on:** Slice A (T01–T14)

- [ ] **T16** — Update button gating in `AccordionBodyConOc` (CON-OC branch)
  - **File:** `frontend/src/components/compras/TabRecepcionDeposito.jsx` L313
  - Render buttons conditionally by `pedido.estado`: pagado→"Recibido" only; recibido→"Controlado"+"Con faltantes"; con_faltantes→"Controlado" only; controlado→no buttons
  - Update success messages to reflect new state names where needed
  - **Satisfies:** REQ-EC-006
  - **Depends on:** T15

- [ ] **T17** — Update button gating in `AccordionBodySinOc` (SIN-OC branch)
  - **File:** `frontend/src/components/compras/TabRecepcionDeposito.jsx` L386
  - Same gating logic as T16 applied to the SIN-OC accordion body
  - Button for pagado→"Recibido" calls `confirmar-pedido` (arrival path); button for recibido→"Controlado"/"Con faltantes" calls `confirmar-pedido` (control path)
  - **Satisfies:** REQ-EC-006
  - **Depends on:** T15, T16

- [ ] **T18** — Update `estadoBadge` inline case in `TabRecepcionDeposito.jsx`
  - **File:** `frontend/src/components/compras/TabRecepcionDeposito.jsx` L24-35
  - `recibido` → amber/"parcial" tone; add `controlado` → green/"pagado" tone (same as old `recibido` entry)
  - **Satisfies:** REQ-EC-007
  - **Depends on:** T15

- [ ] **T19** — Update `MAPPING_PEDIDO` in `EstadoBadge.jsx`
  - **File:** `frontend/src/_shared/EstadoBadge.jsx` L36-48 (approx L41)
  - `recibido`: change tone to amber/"parcial"; label stays "Recibido"
  - Add `controlado`: tone green/"pagado"; label "Controlado"
  - `con_faltantes`: unchanged
  - **Satisfies:** REQ-EC-007
  - **Depends on:** T15

---

## Out-of-scope guard

- [ ] **T20** — Confirm `cheques_service.py` is NOT modified
  - **File:** `backend/app/services/cheques_service.py`
  - Read-only verification: ensure no references to `pedido_compra.estado` were inadvertently changed
  - **Satisfies:** REQ-EC-010
  - **Depends on:** T08–T14 (post-implementation review)

---

## REQ → Task Coverage Matrix

| REQ | Tasks |
|-----|-------|
| REQ-EC-001 | T01, T02, T08, T09, T04, T07 |
| REQ-EC-002 | T01, T10, T12, T13, T05, T07 |
| REQ-EC-003 | T11, T13, T06, T07 |
| REQ-EC-004 | no new tasks — existing permission gate unchanged |
| REQ-EC-005 | T15 |
| REQ-EC-006 | T16, T17 |
| REQ-EC-007 | T18, T19 |
| REQ-EC-008 | T01 |
| REQ-EC-009 | T14, T07 |
| REQ-EC-010 | T20 |
| REQ-EC-011 | T02, T03 |
| REQ-EC-012 | T04, T05, T06, T07 |

---

## Review Workload Forecast

| Metric | Estimate |
|--------|----------|
| Slice A — backend changed lines | ~300–360 |
| Slice B — frontend changed lines | ~80–120 |
| Total estimated changed lines | ~380–480 |
| Chained PRs recommended | **Yes** |
| 400-line budget risk | **High** (total exceeds 400 at upper bound; backend alone may approach 360) |
| Decision needed before apply | **Yes** — confirm 2-slice stacked-to-main (Slice A PR → merge → Slice B PR) vs single PR with `size:exception` |

**Recommendation:** 2-slice stacked-to-main. Slice A (backend) is self-contained and testable independently. Slice B (frontend) depends on Slice A state names being merged so the FE tab/badge labels match the running API. Splitting avoids a 480-line monster PR and keeps review diffs focused.

# Tasks — Modelo de Moneda del Módulo de Compras

> Change: `compras-modelo-moneda`
> Artifact store: openspec
> TDD: Strict (backend) · ESLint only (frontend)
> No Alembic migrations in v1 (all schema fields already exist)
> tc_fuente: DEFERRED — no column exists yet; tag is informational only; adding it
>   would require a migration, which is out-of-scope for v1. Tasks below treat
>   tc_fuente as display-only, deferred to a subsequent change.

---

## Sequencing Notes

- Tasks are strictly **sequential within each area** (TDD: test → impl → green).
- Areas A and C can proceed **in parallel** once B.1 is done (fx_service is the shared
  foundation for both CC backend work and imputaciones validation).
- Frontend (D) is independent of all backend areas; can run in parallel.
- E (validation) runs last, after A + B + C + D are complete.

---

## Area A — `fx_service`: Módulo de derivación y redondeo (NEW)

> Crea el módulo `backend/app/services/fx_service.py` con la regla única de derivación
> a pesos, helpers de redondeo centralizados, y cómputo de varianza visible.
> Satisface: ADR-7, ADR-3, REQ-MM-006 §4.1, REQ-MM-002, design §2 + §3.

- [x] **A.1 — [TEST] Helpers de redondeo HALF_UP centralizados**
  - Escribe `backend/tests/unit/test_fx_service.py`
  - Tests: `test_q_ars_redondea_half_up`, `test_q_usd_redondea_half_up`,
    `test_q_tc_seis_decimales_half_up`, `test_redondeo_half_up_ars_usd_tc`
  - Deben fallar (módulo no existe aún)
  - Spec: ADR-3 / design §3

- [x] **A.2 — [IMPL] Crear `fx_service.py` con helpers de redondeo**
  - Archivo: `backend/app/services/fx_service.py`
  - Implementar: `q_ars(x: Decimal) -> Decimal`, `q_usd(x: Decimal) -> Decimal`,
    `q_tc(x: Decimal) -> Decimal` con `ROUND_HALF_UP` y precisiones correctas
  - Green: `cd backend && venv/bin/pytest tests/unit/test_fx_service.py -x`

- [x] **A.3 — [TEST] `derivar_ars` — regla única por estado de liquidación**
  - Agrega en `test_fx_service.py`:
    - `test_derivar_ars_deuda_viva_usa_tc_snapshot` (contexto i — deuda no pagada)
    - `test_derivar_ars_porcion_pagada_usa_tc_op` (contexto ii — porción liquidada)
    - `test_derivar_ars_mixto_por_imputacion` (contexto iii — pagos parciales)
    - `test_invariante_ars_nunca_se_repega` (moneda ARS → factor 1, no se re-pega)
  - Spec: REQ-MM-002, REQ-MM-006, design §2.1 (tabla de regla única)

- [x] **A.4 — [IMPL] `derivar_ars` en `fx_service`**
  - Firma: `derivar_ars(monto: Decimal, moneda: str, tc: Decimal | None) -> Decimal`
  - ARS → devuelve `monto` intacto (invariante). USD → `monto * tc` con `q_ars`.
  - Green: todos los tests de A.3

- [x] **A.5 — [TEST] `derivar_varianza_visible` — fórmula display-only**
  - Agrega en `test_fx_service.py`:
    - `test_varianza_tc_display_calculo_correcto`
    - `test_varianza_tc_cero_cuando_tc_iguales`
    - `test_varianza_tc_none_cuando_pedido_ars` (pedido ARS → no aplica)
  - Spec: REQ-MM-006 §4.1, design §4.1

- [x] **A.6 — [IMPL] `derivar_varianza_visible` en `fx_service`**
  - Firma: `derivar_varianza_visible(tc_op: Decimal | None, tc_snapshot: Decimal | None, usd_imputado: Decimal) -> Decimal | None`
  - Retorna `None` si `tc_snapshot` es None (pedido ARS). Cero si `tc_op == tc_snapshot`.
  - Green: todos los tests de A.5

---

## Area B — Backend: validaciones de modelo canónico

> Ajusta las validaciones en servicios de imputaciones y ordenes_pago.
> Satisface: REQ-MM-003, REQ-MM-004, design §2.

- [x] **B.1 — [TEST] Cross-moneda nunca bloquea; TC requerido si cross-moneda**
  - Archivo: `backend/tests/unit/test_imputaciones_service.py` (nuevo o existente)
  - Tests:
    - `test_cross_moneda_con_tc_procede` (OP ARS + pedido USD + TC → OK)
    - `test_cross_moneda_sin_tc_devuelve_422` (sin `tipo_cambio` → HTTP 422)
    - `test_same_moneda_ars_sin_tc_procede` (same ARS → OK)
  - Spec: REQ-MM-004, design §2; elimina el bloqueo duro de REQ-IMP-003 párrafo 2

- [x] **B.2 — [IMPL] Eliminar bloqueo cross-moneda en `imputaciones_service`**
  - Archivo: `backend/app/services/imputaciones_service.py`
  - Reemplaza el `raise HTTPException(400, "moneda inconsistente")` por la
    validación: si cross-moneda → exigir `tipo_cambio NOT NULL > 0`, else HTTP 422
  - Mantiene la validación de `proveedor_id` consistente (REQ-IMP-003 párrafo 1)
  - Green: tests de B.1

- [x] **B.3 — [TEST] OP ARS pagando deuda USD requiere `tipo_cambio`**
  - Archivo: `backend/tests/unit/test_ordenes_pago_service.py` (existente)
  - Tests:
    - `test_pagar_op_ars_deuda_usd_sin_tc_devuelve_422`
    - `test_pagar_op_ars_deuda_ars_sin_tc_procede`
  - Spec: REQ-MM-003

- [x] **B.4 — [IMPL] Validación de TC en `ordenes_pago_service.ejecutar_pago`**
  - Archivo: `backend/app/services/ordenes_pago_service.py`
  - Si la OP imputa a pedidos USD y `tipo_cambio` es None → HTTP 422
  - No modificar la lógica de persistencia (AD-7 ya aplicado, tests verdes — KEEP)
  - Green: tests de B.3 + tests AD-7 existentes siguen verdes

---

## Area C — Backend: corrección bug #1 (proyección ARS del CC)

> Corrige la prioridad de TC en `_enriquecer_movimientos_cc` para usar el TC de la
> imputación que generó cada HABER, en vez del TC efectivo ponderado del pedido.
> Satisface: REQ-MM-007, design §6.
> Depende de: A.4 (derivar_ars) y A.6 (varianza_visible) implementadas.

- [x] **C.1 — [TEST] CC usa TC de liquidación de la OP por movimiento HABER**
  - Archivo: `backend/tests/unit/test_cc_proveedor_service.py` (nuevo o existente)
  - Tests:
    - `test_cc_proyeccion_ars_usa_tc_liquidacion_por_mov`
      (verifica que HABER de pago usa `imp.tipo_cambio`, no el ponderado)
    - `test_cc_saldo_nativo_no_cambia_por_varianza_tc`
      (saldo USD/ARS nativo intocable tras derivación)
    - `test_cc_por_pedido_expone_varianza_tc_ars`
      (campo `varianza_tc_ars` presente y correcto)
  - Spec: REQ-MM-007, design §6.2 (nueva prioridad de TC)

- [x] **C.2 — [IMPL] Corrección de prioridad TC en `_enriquecer_movimientos_cc`**
  - Archivo: `backend/app/services/cc_proveedor_service.py`
    (o `administracion_compras` si la lógica vive allí — confirmar path exacto)
  - Nueva prioridad por movimiento:
    1. `imp.tipo_cambio` (HABER de pago con imputación cross o same-USD con AD-7)
    2. `pedido.tc_snapshot` / `tipo_cambio_original` (deuda viva — DEBE)
    3. `tipo_cambio_a_ars` persistido (fallback)
    4. None → excluido de `saldo_ars` + log WARNING
  - Extender el hop de imputación existente para traer `Imputacion.tipo_cambio`
  - Agregar campo `varianza_tc_ars` (nullable) en el response, computado con
    `fx_service.derivar_varianza_visible`
  - Reemplazar call-sites de redondeo ad-hoc por `fx_service.q_ars` / `q_tc`
  - Green: tests de C.1

- [x] **C.3 — [TEST] `fx_same_moneda_usd_con_tc_ad7` integrado con CC**
  - Agrega `test_fx_same_moneda_usd_con_tc_ad7` en test suite (verifica que
    same-moneda USD con `imp.tipo_cambio` de AD-7 genera varianza correcta)
  - Spec: ADR-4, design §5.1

- [x] **C.4 — [IMPL] Refactorizar call-sites de redondeo existentes a `fx_service`**
  - Archivos: `backend/app/services/ordenes_pago_service.py`,
    `backend/app/services/cc_proveedor_service.py`
  - Reemplazar `Decimal(...).quantize(...)` ad-hoc por `q_ars(...)`, `q_usd(...)`,
    `q_tc(...)` importados de `fx_service`
  - Los tests AD-7 existentes (`test_tc_ponderado_caso_a.py`) DEBEN seguir verdes
  - Green: full suite `venv/bin/pytest tests/ -x`

---

## Area D — Frontend: revert "Option A" + derive-at-edge correcto

> Revierte la mutación de `items[].monto` al cambiar TC/moneda y la reemplaza por
> `useMemo` de derivación en render. El monto nativo del pedido queda inmutable.
> Satisface: REQ-MM-002, ADR-6, design §8.
> Sin test runner FE → validación por ESLint + QA manual.
> KEEP: auto-fill "pago a cuenta" + `pagoACuentaTouched` flag (ya en el WIP).

- [x] **D.1 — [REVERT] Eliminar conversión de `items[].monto` en `handleChange`**
  - Archivo: `frontend/src/components/compras/ModalOrdenPagoNueva.jsx`
  - Eliminar los bloques `setItems(...)` de conversión de moneda en `handleChange`
    (líneas ~417-433 y ~475-492 según el WIP actual)
  - El cambio de `form.moneda` o `form.tipo_cambio` NO debe tocar `items[].monto`
  - Conservar: limpieza de NCs moneda-específicas al cambiar moneda
  - Lint: `cd frontend && pnpm lint` sin errores

- [x] **D.2 — [IMPL] `montoEnMonedaOP` helper + `itemsDerivados` useMemo**
  - Archivo: `frontend/src/components/compras/ModalOrdenPagoNueva.jsx`
  - Implementar la función `montoEnMonedaOP(item)` según el design §8.2
  - Implementar `const itemsDerivados = useMemo(...)` que mapea items con
    `montoDerivado` calculado al vuelo
  - Si `tc` no es válido (NaN, 0, vacío) → `montoDerivado = null` (no mostrar)
  - Lint: `pnpm lint` sin errores

- [x] **D.3 — [IMPL] Render y submit usan `itemsDerivados`**
  - Archivo: `frontend/src/components/compras/ModalOrdenPagoNueva.jsx`
  - Toda tabla de ítems renderiza `item.montoDerivado` (no `item.monto`)
  - El total de la OP suma `montoDerivado` de todos los ítems
  - El payload de submit usa `montoDerivado` como `monto` en la moneda de la OP
    (derivado en el momento de submit, no almacenado mutado)
  - Lint: `pnpm lint` sin errores

- [x] **D.4 — [IMPL] `TabCCProveedores` — mostrar `varianza_tc_ars`**
  - Archivo: `frontend/src/components/compras/TabCCProveedores.jsx`
    (o el componente que renderiza el detalle de imputaciones del CC del proveedor)
  - Mostrar el campo `varianza_tc_ars` por imputación cuando viene en la respuesta
    (display-only; null → no mostrar nada o "—")
  - Formato sugerido: `+$450.000 ARS` (verde/rojo según signo)
  - No calcular en FE: el campo viene del backend (C.2)
  - Lint: `pnpm lint` sin errores

---

## Area E — Validación final

> Corre la suite completa y verifica que el WIP existente (AD-7 + auto-fill) siga verde.

- [ ] **E.1 — Suite completa verde**
  - Comando: `cd backend && venv/bin/pytest tests/ -x`
  - Todos los tests deben pasar, incluyendo los AD-7 existentes
    (`test_tc_ponderado_caso_a.py`) y los nuevos de A, B, C

- [ ] **E.2 — Lint frontend limpio**
  - Comando: `cd frontend && pnpm lint`
  - Sin errores en `ModalOrdenPagoNueva.jsx` ni `TabCCProveedores.jsx`

- [ ] **E.3 — QA manual frontend (checklist)**
  - Abrir una OP en `ModalOrdenPagoNueva`
  - Agregar un ítem de pedido USD ($1000 USD)
  - Cambiar la moneda de la OP a ARS → verificar que `items[].monto` nativo NO cambia
    (solo el display derivado cambia)
  - Cambiar el TC → verificar que el total se recalcula en display sin mutar el nativo
  - Verificar que el auto-fill "pago a cuenta" y `pagoACuentaTouched` siguen funcionando
  - Abrir CC de un proveedor con pagos USD → verificar `varianza_tc_ars` visible

---

## Decisiones y flags pendientes antes de `apply`

> Estos ítems NO bloquean la generación del task list, pero deben resolverse antes
> de implementar las áreas que los consumen.

| Flag | Pregunta | Área afectada | Recomendación |
|------|----------|---------------|---------------|
| ADR-3 | Confirmar `ROUND_HALF_UP` vs `HALF_EVEN` con el PO contable | A.2 (implementación de helpers) | HALF_UP (ya de facto en código) |
| `tc_fuente` | Confirmar que el tag `bna\|proveedor` queda diferido a v2 (requeriría migración) | — | Diferido; no crear migration en v1 |

---

## Dependency Graph

```
A.1 → A.2 → A.3 → A.4 → A.5 → A.6 ─┐
                                      ├─→ C.1 → C.2 → C.3 → C.4 ─┐
B.1 → B.2 → B.3 → B.4 ───────────────┘                            ├─→ E.1 → E.2 → E.3
D.1 → D.2 → D.3 → D.4 ─────────────────────────────────────────────┘
```

- B puede arrancar en paralelo con A (no depende de fx_service hasta C)
- D puede arrancar en paralelo con A y B (independiente del backend)
- C depende de A.4 y A.6

---

## Review Workload Forecast

| Métrica | Estimado |
|---------|----------|
| Archivos modificados | 6–7 (fx_service new, imputaciones_service, ordenes_pago_service, cc_proveedor_service, ModalOrdenPagoNueva, TabCCProveedores, + test files) |
| Archivos de test nuevos/modificados | 3–4 |
| Líneas cambiadas (impl) | ~350–450 líneas |
| Líneas cambiadas (tests) | ~200–250 líneas |
| Total estimado | **~550–700 líneas** |
| Chained PRs recomendados | **Sí** — presupuesto de 400 líneas en riesgo alto |
| Riesgo presupuesto 400 líneas | **HIGH** |

### Splitting sugerido

| PR | Scope | Líneas est. |
|----|-------|-------------|
| PR #1 | Area A: `fx_service` (nuevo módulo) + tests | ~180 líneas |
| PR #2 | Areas B + C: validaciones + bug #1 CC + refactor redondeo | ~250 líneas |
| PR #3 | Area D: frontend revert Option A + derive-at-edge + varianza visible | ~180 líneas |

> PR #1 mergea a main primero; PR #2 y PR #3 pueden prepararse sobre PR #1
> (strategy: `stacked-to-main`).

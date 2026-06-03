# Design: Modelo de Moneda del Módulo de Compras

> Change: `compras-modelo-moneda`
> Mode: openspec (filesystem) + Engram topic `sdd/compras-modelo-moneda/design`
> Depends on: `proposal.md`
> Subsume/corrige: `compras-cross-moneda-y-ncs-cc` (design §11 open questions)

## Technical Approach

El modelo canónico es **"store-native + derive-at-edge"** con **ARS como moneda
funcional** (la empresa siempre paga en pesos). El change NO re-implementa el
cross-moneda OP↔pedido (ya está en código); lo **formaliza** y agrega lo que
faltaba para cerrar el modelo:

1. **Una regla única de derivación a pesos** (qué TC usar en cada contexto),
   consumida tanto por la proyección ARS del CC como por la UI.
2. **Montos ARS correctos y varianza de TC visible** (display-only): cada
   documento muestra el monto ARS derivado al TC que le corresponde; la diferencia
   entre el TC del pedido y el TC de la OP es observable. No se persiste P&L.
3. **El invariante ARS nominal fijo**: un importe peso-fijo NUNCA se re-pega por
   ningún TC. Esto motiva revertir la "Option A" del frontend.

Pilar arquitectónico (heredado y reforzado): **append-only sagrado**. Cero
`UPDATE`/`DELETE` sobre `imputaciones`, `cc_proveedor_movimientos`,
`compras_eventos`. No se crean tablas nuevas en v1 (sin migración).

Decisión transversal clave: **la conversión a pesos vive SIEMPRE en el backend
(servicio)**. El frontend solo muestra valores ya derivados o pre-deriva para
preview de UX, pero NUNCA persiste el derivado como dato nativo. El monto nativo
de cada ítem es inmutable ante cualquier cambio de TC.

Convención de TC en todo el módulo (ya vigente, se formaliza): **TC = "ARS por 1
USD"**. `monto_ars = monto_usd * tc`; `monto_usd = monto_ars / tc`.

---

## 1. Component Map

```
                         UI (derive-at-edge, solo display)
        ┌─────────────────────────────────────────────────────────┐
        │ ModalOrdenPagoNueva.jsx                                  │
        │  ├── items[].monto = NATIVO del pedido (INMUTABLE)       │
        │  ├── montoDerivado(item) = useMemo(nativo, TC, monedaOP) │  ← NEW (deriva en render)
        │  └── cambio de TC/moneda → NO toca items[].monto         │  ← FIX Option A
        │ TabCCProveedores.jsx                                     │
        │  ├── saldo nativo por moneda (sin tocar)                 │
        │  ├── monto_ars derivado (regla única, backend)           │
        │  └── varianza TC visible por imputación (display-only)   │  ← NEW
        └─────────────────────────────────────────────────────────┘
                                   │
        ──────────────────────────────────────────────── BACKEND ──
                                   ▼
        ┌─────────────────────────────────────────────────────────┐
        │ ordenes_pago_service.ejecutar_pago                       │
        │  ├── crea imputacion (store-native, TC) — YA EXISTE      │
        │  └── aplica a CC (HABER moneda destino) — YA EXISTE      │
        │  (sin hook de persistencia FX — display-only en v1)      │
        └─────────────────────────────────────────────────────────┘
                                   │
                                   ▼
        ┌────────────────────────────────┐
        │ fx_service (NEW)               │
        │  ├── derivar_ars(...)  (regla  │
        │  │   única — §2)               │
        │  └── REDONDEO centralizado §3  │
        └────────────────────────────────┘
                                   │
                                   ▼
        ┌─────────────────────────────────────────────────────────┐
        │ cc_proveedor_service / administracion_compras            │
        │  ├── calcular_saldo_por_moneda (NATIVO — SIN CAMBIOS)    │
        │  └── _enriquecer_movimientos_cc → usa derivar_ars (§2/§6)│  ← FIX bug #1
        │ pedidos_service                                          │
        │  └── resolver_tc_efectivo_pedido(_batch) (ancla registr.)│
        └─────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                              PostgreSQL
              (imputaciones + cc_proveedor_movimientos — append-only;
               sin tabla cc_resultado_cambio en v1)
```

---

## 2. La Regla Única de Derivación a Pesos (derive-at-edge)

Esta es la pieza central. Una SOLA función la implementa y todos los contextos la
consumen. Vive en `fx_service.derivar_ars(...)` (o, si se prefiere no crear un
módulo nuevo, en `cc_proveedor_service`); este design recomienda **`fx_service`
nuevo** para no inflar `cc_proveedor_service` y mantener cohesión.

### 2.1 Definición

> **REGLA ÚNICA**: para derivar el equivalente en pesos de un monto, se usa el TC
> que corresponde al **estado de liquidación** de ese monto:
>
> | Contexto del monto | TC que se usa para derivar ARS |
> |---|---|
> | (i) Obligación USD **no pagada** (deuda viva mostrada en CC/UI antes del pago) | `pedido.tc_snapshot` (TC de **registración**) |
> | (ii) Porción **liquidada** (cancelada por una OP) | TC de la **OP que la paga** (`imp.tipo_cambio`) |
> | (iii) Mixto / parcial (varias OPs a distintos TC) | **por imputación**: cada porción liquidada con el TC de su propia OP; el remanente no pagado con `pedido.tc_snapshot` |
> | Documento **ARS nativo** (cualquier estado) | factor 1 — nunca se re-pega (invariante §4) |

### 2.2 Materialización en código

La derivación del CC ya tiene la forma correcta en
`resolver_tc_efectivo_pedido_batch` + `_enriquecer_movimientos_cc`, PERO hoy el
fallback de prioridad puede elegir el TC equivocado (bug #1). La regla se
materializa así:

- **TC de liquidación por movimiento HABER de pago** = el `imp.tipo_cambio` de la
  imputación que generó ese HABER. Es el dato más exacto: refleja a qué TC esa
  porción de deuda se canceló.
- **TC de la deuda viva (DEBE original del pedido sin cancelar)** =
  `pedido.tc_snapshot` (hoy `tipo_cambio_original` / resolver mode 3).
- El `resolver_tc_efectivo_pedido` ponderado (Caso A) sigue siendo una **métrica
  derivada** útil (TC efectivo promedio), pero NO es la fuente para derivar el ARS
  de un movimiento puntual: cada movimiento HABER se deriva con SU `imp.tipo_cambio`.

> **Corrección concreta del bug #1**: en `_enriquecer_movimientos_cc`, para un
> movimiento HABER que proviene de una imputación cross-moneda, la prioridad de TC
> debe ser **(1) `imp.tipo_cambio` de esa imputación** → (2) `pedido.tc_snapshot`
> → (3) `tipo_cambio_a_ars` persistido. Hoy la prioridad 1 es "TC efectivo del
> pedido", que mezcla el TC de OTRAS OPs y por eso proyecta mal. Ver §5.

### 2.3 Dónde ocurre y dónde NO

- **Ocurre** (escribe ARS derivado, efímero, en el response): `fx_service.derivar_ars`,
  llamado por `_enriquecer_movimientos_cc` (CC) y expuesto en campos `monto_ars` /
  `tc_aplicado` de la respuesta. El frontend lo muestra tal cual.
- **NO ocurre** (jamás se persiste el ARS derivado como fuente de verdad ni se
  re-escribe el monto nativo): ni el saldo nativo del CC
  (`calcular_saldo_por_moneda`), ni `imputaciones.monto_imputado`, ni
  `items[].monto` del frontend. El ARS derivado es columna de respuesta, no de tabla.

---

## 3. Política de Redondeo (DECISIÓN — requiere confirmación del PO)

### 3.1 Recomendación

> **DECISIÓN RECOMENDADA (requiere confirmación del product owner)**:
> **`ROUND_HALF_UP` a 2 decimales para ARS y 2 decimales para USD**; TC con
> **6 decimales** (precisión de la columna `Numeric(18,6)`).

| Magnitud | Precisión | Modo |
|---|---|---|
| ARS (montos, resultado FX) | 2 decimales | `ROUND_HALF_UP` |
| USD (montos imputados) | 2 decimales | `ROUND_HALF_UP` |
| TC (tipo de cambio) | 6 decimales | `ROUND_HALF_UP` |
| TC ponderado (métrica derivada) | 4 decimales | `ROUND_HALF_UP` |

### 3.2 Rationale

- El código YA aplica `ROUND_HALF_UP` de forma explícita en los puntos críticos:
  `ejecutar_pago` (líneas 1173-1177, comentario textual "Política contable
  explícita del SDD: ROUND_HALF_UP"), `registrar_ajuste_revaluacion_tc`,
  `_enriquecer_movimientos_cc` (línea 2369), `calcular_tc_ponderado_caso_a`. La
  open question §11 de `compras-cross-moneda-y-ncs-cc` decía "HALF_EVEN por
  default de Decimal" pero el código **ya migró a HALF_UP**. Elegir HALF_UP
  **alinea spec con el código existente** — cero churn.
- HALF_UP ("round half away from zero" para positivos) es la práctica contable
  esperada por usuarios no técnicos en Argentina (redondeo comercial). HALF_EVEN
  (banker's rounding) es estadísticamente más neutro pero contraintuitivo para
  conciliación manual contra el ERP.
- **Debe aplicarse consistentemente** en: derivación a ARS (§2), cómputo del
  resultado FX (§4), conversión de montos en `ejecutar_pago`, y la métrica TC
  ponderado. Para garantizarlo, `fx_service` expone helpers centralizados
  `q_ars(x)`, `q_usd(x)`, `q_tc(x)` y TODO redondeo del modelo de moneda pasa por
  ellos (los call-sites existentes se refactorizan a usarlos en `apply`).

> **FLAG PO**: confirmar HALF_UP vs HALF_EVEN antes de implementar. Si el equipo
> contable exige HALF_EVEN, solo cambia el `rounding=` de los 3 helpers — el resto
> del diseño no se toca. Recomendación firme: **HALF_UP** (ya es el de facto).

---

## 4. Varianza de TC — Display-Only (v1)

> **DECISIÓN (lean scope):** No se persiste ningún ledger de resultado FX realizado en v1.
> La tabla `cc_resultado_cambio` y su migración Alembic quedan **fuera de scope**.
> Ver propuesta Out-of-Scope.
>
> La varianza entre el TC de registración del pedido y el TC de liquidación de la OP es
> **computable en el momento de mostrar** y se expone como campo derivado en la respuesta
> de la API (display-only). No requiere tabla nueva.

### 4.1 Fórmula de varianza visible (display, no persistida)

Para una imputación cross-moneda OP↔pedido USD:

```
varianza_ars = (tc_op - tc_pedido_snapshot) * usd_imputado
```

- `tc_op` = `imp.tipo_cambio` (TC de liquidación de la OP)
- `tc_pedido_snapshot` = `pedido.tc_snapshot` (TC de registración del pedido)
- `usd_imputado` = `imp.monto_imputado` (USD)

Esta fórmula se aplica en `fx_service.derivar_varianza_visible(...)` (helper puro, sin
side-effects de BD) y se incluye en el response de endpoints de CC/imputación como campo
`varianza_tc_ars` (nullable — solo presente cuando moneda del pedido es USD y hay TC en la
imputación).

El `fx_service` sigue existiendo como módulo de lógica de derivación (`derivar_ars`,
helpers de redondeo `q_ars/q_usd/q_tc`), pero **sin** `computar_resultado_fx` ni
`registrar_resultado_fx`.

> **Diferido:** La persistencia del ledger FX (`cc_resultado_cambio`, modelo SQLAlchemy,
> migración Alembic, hook en `ejecutar_pago`, reversals) queda para un change posterior.

---

## 5. AD-7 y `ejecutar_pago` — sin hook de persistencia FX

> **DECISIÓN (lean scope):** No se agrega hook de persistencia FX en `ejecutar_pago`.
> La rama que graba `tc_imp = tc_op` en imputaciones (AD-7, ya committed) permanece
> intacta — es el dato que habilita la varianza visible (§4) y la regla de derivación (§2).

### 5.1 Relación con AD-7

El fix AD-7 (imputaciones same-moneda USD→USD guardan `op.tipo_cambio`) es el primer
paso coherente del modelo. El campo `imp.tipo_cambio` es la fuente para:
- Derivar el monto ARS correcto de la porción pagada (regla única §2).
- Calcular la varianza visible `(tc_op - tc_pedido_snapshot) * usd_imputado` (§4.1).

No se agrega ningún código nuevo a `ejecutar_pago` para persistencia de FX.

### 5.2 Nota sobre pedido ARS pagado por OP USD

El pedido ARS es peso-fijo; no tiene `tc_snapshot` → no hay varianza de TC de ese lado.
El invariante ARS (§2 del modelo) manda: el ARS no se revalúa. Documentado como out-of-scope
coherente con "ARS nominal fijo".

---

## 6. CC Projection Change (corrige bug #1)

### 6.1 Qué cambia y qué NO

- **NO cambia**: `calcular_saldo_por_moneda` — el saldo del proveedor sigue siendo
  **nativo por moneda** (USD cuadra en USD, ARS en ARS). Intocable. El FX NO entra
  acá (decisión 8).
- **Cambia**: la **proyección ARS derivada** en `_enriquecer_movimientos_cc`
  (`monto_ars`, `tc_aplicado`) para usar la regla única §2.

### 6.2 Corrección de la prioridad de TC

Hoy (líneas 2358-2381) para un movimiento USD:
1. TC efectivo del pedido (`resolver_tc_efectivo_pedido_batch`) ← **mezcla TCs de
   varias OPs → bug #1**
2. `tipo_cambio_a_ars` persistido
3. None

Nueva prioridad por movimiento:
1. **Si el movimiento proviene de una imputación con `tipo_cambio` propio** (HABER
   de pago/NC cross-moneda) → usar **ese `imp.tipo_cambio`** (TC de liquidación de
   esa porción puntual). Se obtiene en el hop de imputación que el código ya hace
   (`imps_resueltos` / `imps_destino_pedido`); extender el hop para traer también
   `Imputacion.tipo_cambio`.
2. **Si es el DEBE original del pedido (deuda viva)** → `pedido.tc_snapshot`
   (`tipo_cambio_original`).
3. Fallback → `tipo_cambio_a_ars` persistido al momento del movimiento.
4. None → excluido de `saldo_ars` + log WARNING (igual que hoy).

Esto hace que cada porción de deuda se muestre en ARS al TC al que efectivamente se
liquidó, y la deuda viva al TC de registración — **una sola regla, dos contextos**.

> El `saldo_ars` resultante deja de "saltar" cuando entra una OP a TC distinto:
> antes re-derivaba TODA la historia del pedido al último TC efectivo; ahora cada
> movimiento conserva su TC de liquidación. Esto es lo que corrige el bug #1.

---

## 7. Flag NC/ND — REMOVED (Out-of-Scope v1)

> **DECISIÓN (lean scope):** El flag "falta NC/ND" + botón de creación manual
> no se implementa en v1. Queda diferido a un change posterior.
>
> ADR-5 (criterio de trigger NC/ND) eliminado de este change.
> Ver Out-of-Scope en §10.

---

## 8. Frontend "Option A" Revert — derive-at-edge correcto

### 8.1 El anti-patrón actual

`ModalOrdenPagoNueva.jsx` reescribe `items[].monto` (el monto NATIVO del pedido) al
cambiar la moneda de la OP o el TC (líneas 417-433 y 471-492: `setItems(... it.monto
= convertido.toFixed(2))`). Esto **destruye el monto nativo** y permite re-expandir
un importe peso-fijo — viola el invariante ARS (§4) y acumula error de redondeo.

### 8.2 Diseño correcto

> **PRINCIPIO**: `items[].monto` guarda SIEMPRE el monto **nativo del pedido**
> (en `pedido.moneda`) y es **inmutable** ante cambios de TC o moneda de la OP. La
> conversión a la moneda del flujo de pago se **deriva en render**, nunca se escribe.

**Estado**:
- `items[].monto` → monto nativo del pedido (USD si el pedido es USD). No se toca
  jamás por cambios de `form.moneda` / `form.tipo_cambio`.
- `form.moneda`, `form.tipo_cambio` → estado del flujo de pago (la OP).

**Derivación (nuevo, reemplaza los `setItems` de conversión)**:
```jsx
// Deriva el monto del item en la moneda de la OP, para mostrar y para el submit.
const montoEnMonedaOP = (item) => {
  const pedido = pedidoDe(item.id);
  const nativo = Number(item.monto);                 // INMUTABLE
  if (!pedido || pedido.moneda === form.moneda) return nativo;
  const tc = parseFloat(form.tipo_cambio);
  if (!(Number.isFinite(tc) && tc > 0)) return null; // sin TC válido: no se puede derivar
  return form.moneda === 'ARS' && pedido.moneda === 'USD'
    ? nativo * tc                                     // mostrar deuda USD en ARS
    : form.moneda === 'USD' && pedido.moneda === 'ARS'
      ? nativo / tc
      : nativo;
};
const itemsDerivados = useMemo(
  () => items.map((it) => ({ ...it, montoDerivado: montoEnMonedaOP(it) })),
  [items, form.moneda, form.tipo_cambio]
);
```

- El render usa `itemsDerivados[].montoDerivado` para mostrar y para sumar el total.
- Al cambiar TC o moneda, `useMemo` re-deriva la vista; **`items[].monto` no cambia**.
  Esto **arregla el bug de reactividad de la forma correcta**: la vista reacciona,
  el dato nativo no se corrompe.
- El **payload de submit** envía el monto en la moneda de la OP (`montoDerivado`)
  —que es lo que `ejecutar_pago` espera como `item["monto"]` "en moneda OP"— pero
  ese valor se **deriva en el momento del submit**, no se almacena mutado.

**Se elimina**: toda la lógica `setItems(...)` de conversión en `handleChange`
(líneas 417-433 y 475-492). El cambio de moneda solo limpia NCs (moneda-específicas)
y resetea errores de TC; no toca montos nativos. El `confirmMoneda` destructivo deja
de tener sentido para items cross-moneda (ya no se destruye nada) — se conserva solo
si quedara algún caso de pérdida real de datos (revisar en apply).

### 8.3 TabCCProveedores

- Saldos nativos por moneda: sin cambios.
- `monto_ars` derivado: viene del backend con la regla única (§6) — el frontend
  solo lo muestra, no calcula.
- Varianza de TC visible: muestra `varianza_tc_ars` por imputación cuando está
  presente en la respuesta del backend (display-only — §4.1).
- Flag NC/ND: **no implementado en v1** (§7 — out-of-scope).

---

## 9. Data Model — resumen de cambios

| Tabla/Modelo | Cambio | Migración |
|---|---|---|
| `imputaciones` | sin cambios de schema (ya tiene `tipo_cambio`) | No |
| `cc_proveedor_movimientos` | sin cambios de schema | No |
| `ordenes_pago` / `pedidos_compra` | sin cambios de schema (`tc_snapshot` = `tipo_cambio_original` ya existe) | No |

> **Sin migraciones Alembic en v1.** Todos los campos requeridos por el modelo
> (moneda, tc_snapshot/tipo_cambio_original, tipo_cambio en imputaciones) ya existen
> en el schema.

> **Tag de origen del TC** (`'bna' | 'proveedor'`): diferido — sin consumidor ni
> requisito duro en v1. Columna nullable en `ordenes_pago` en un change posterior.

> **`cc_resultado_cambio` (ledger FX)**: tabla y migración Alembic eliminados de
> este change. Diferido a un change posterior (ver Out-of-Scope).

---

## 10. Architecture Decisions (ADR)

### ADR-1: REMOVED — Ledger FX `cc_resultado_cambio` diferido a v2
> La tabla append-only de resultado FX realizado y su migración Alembic quedan fuera
> de scope en v1. La varianza de TC es display-only (§4). Se documenta el diseño para
> retomarlo en un change posterior, sin perder el trabajo de análisis.
>
> Rationale del diferimiento: el PO priorizó los fixes observables (montos correctos,
> varianza visible) sobre la contabilización P&L. La complejidad de la tabla nueva +
> migración + hook + reversals se justifica cuando el equipo contable lo requiera.

### ADR-2: Regla única de derivación a pesos por estado de liquidación
**Choice**: deuda viva → `tc_snapshot` del pedido; porción pagada → `imp.tipo_cambio`
de la OP; mixto → por imputación.
**Alternatives**: usar siempre el TC efectivo ponderado del pedido (status quo, bug
#1); usar siempre el TC del día.
**Rationale**: el ponderado mezcla TCs de OPs distintas y proyecta mal; el TC del día
re-pega contra volatilidad (impracticable en Argentina). Por-imputación es exacto y
es lo que IAS 21 espera (reconocimiento vs liquidación). El ponderado queda como
métrica derivada, no como fuente de derivación puntual.

### ADR-3: Redondeo `ROUND_HALF_UP` 2 dec (ARS/USD), 6 dec (TC) — PO CONFIRM
**Choice**: HALF_UP, centralizado en helpers `q_ars/q_usd/q_tc` de `fx_service`.
**Alternatives**: HALF_EVEN (banker's) — el que decía la open question §11.
**Rationale**: el código YA usa HALF_UP en todos los puntos críticos; elegirlo
alinea spec↔código con cero churn y coincide con el redondeo comercial esperado por
contaduría. **FLAG: requiere confirmación del PO**; si exigen HALF_EVEN, solo cambia
el `rounding=` de 3 helpers.

### ADR-4: FX se construye sobre AD-7 (same-moneda USD con TC también genera FX)
**Choice**: el hook dispara para todo pedido USD con `imp.tipo_cambio` presente,
cubriendo cross-moneda y same-moneda USD (habilitado por AD-7).
**Alternatives**: limitar FX solo a cross-moneda ARS↔USD.
**Rationale**: un pedido USD pagado por OP USD a TC distinto del de registración
igual liquida ARS reales a otro TC → hay diferencia de cambio real. Limitarlo a
cross-moneda perdería ese resultado. AD-7 deja de ser excepción y se vuelve el
primer paso coherente del modelo.

### ADR-5: REMOVED — Flag NC/ND diferido a v2 (§7)
> El criterio de trigger y la señalización "falta NC/ND" quedan fuera de scope en v1.
> El análisis del §7 original (fórmula de diferencia_obligacion, distinción NC vs ND,
> tolerancias de reconciliación) se conserva como referencia para cuando el PO lo
> retome.

### ADR-6: Frontend deriva en render (useMemo), nunca muta el monto nativo
**Choice**: `items[].monto` inmutable; `montoDerivado` calculado con `useMemo` sobre
(items, moneda, TC); submit deriva en el momento.
**Alternatives**: "Option A" actual (mutar `items[].monto` al cambiar TC/moneda).
**Rationale**: mutar el nativo viola el invariante ARS, permite re-expandir
peso-fijos y acumula error de redondeo. Derivar en render arregla la reactividad de
la forma correcta y preserva el dato nativo como fuente de verdad.

### ADR-7: `fx_service` nuevo módulo, no engordar `cc_proveedor_service`
**Choice**: módulo `fx_service` con `derivar_ars`, `computar_resultado_fx`,
`registrar_resultado_fx`, helpers de redondeo.
**Alternatives**: meter todo en `cc_proveedor_service`.
**Rationale**: cohesión — el FX y la regla de derivación son un concern propio
(diferencia de cambio) que cruza CC, OP y pedidos. Un módulo dedicado evita
dependencias circulares y centraliza el redondeo y la regla única.

---

## 11. Testing Strategy (Strict TDD — pytest backend)

| Layer | Test | Cubre |
|---|---|---|
| Unit | `test_derivar_ars_deuda_viva_usa_tc_snapshot` | §2 regla (i) |
| Unit | `test_derivar_ars_porcion_pagada_usa_tc_op` | §2 regla (ii) |
| Unit | `test_derivar_ars_mixto_por_imputacion` | §2 regla (iii) |
| Unit | `test_invariante_ars_nunca_se_repega` | §2 invariante ARS (factor 1 a cualquier TC) |
| Unit | `test_varianza_tc_display_calculo_correcto` | §4.1 fórmula varianza visible |
| Unit | `test_varianza_tc_cero_cuando_tc_iguales` | §4.1 no-op |
| Unit | `test_fx_same_moneda_usd_con_tc_ad7` | ADR-4 / §5.1 |
| Unit | `test_redondeo_half_up_ars_usd_tc` | §3 / ADR-3 |
| Unit | `test_cc_saldo_nativo_no_cambia_por_varianza_tc` | §6.1 (varianza no toca saldo) |
| Unit | `test_cc_proyeccion_ars_usa_tc_liquidacion_por_mov` | §6.2 (bug #1) |
| Integration | `test_cc_por_pedido_expone_monto_ars_correcto_y_varianza` | §6 endpoint |
| Manual QA FE | revert Option A: cambiar TC/moneda NO altera monto nativo; vista deriva | §8 (sin test runner FE) |

Comando: `cd backend && venv/bin/pytest tests/ -x`. Test-first por servicio.

---

## 12. Open Questions (a confirmar)

- [ ] **ADR-3 Redondeo** — confirmar `HALF_UP` (recomendado, ya de facto) vs
      `HALF_EVEN`. **Bloquea**: define el `rounding=` de los helpers centralizados.
- [ ] **Tag de origen del TC** (`bna|proveedor`) — diferido en v1 (sin consumidor);
      confirmar que no se necesita ya para auditoría.
- [ ] **Varianza TC en pedido ARS pagado por OP USD** — v1: no aplica (invariante ARS).
      Confirmar que la varianza del lado del dinero USD no se requiere en v1.

## Out-of-Scope (deferred from this change)

- **Ledger de resultado FX realizado / tabla `cc_resultado_cambio`** (ADR-1 removed):
  la contabilización P&L de diferencia de cambio queda diferida. En v1 la varianza es
  solo visible en display (§4).
- **Flag "falta NC/ND" + botón de creación manual** (ADR-5 removed, §7): diferido a un
  change posterior. La señalización de NC/ND pendiente no se implementa en v1.

# Proposal: Modelo de Moneda del Módulo de Compras

> Change: `compras-modelo-moneda`
> Establece el modelo canónico de moneda para todo el módulo de compras y
> **resuelve las open questions** dejadas por `compras-cross-moneda-y-ncs-cc`
> (ver su `design.md §11` y los `OPEN_QUESTION-IMP-02`, `OPEN_QUESTION-OP-02`,
> `OPEN_QUESTION-CC-*` de `modulo-compras/specs/`).

## Why

Una implementación previa (`compras-cross-moneda-y-ncs-cc`, ya aplicada en
código) atacó síntomas puntuales de cross-moneda OP↔pedido pero **nunca
documentó un modelo de moneda coherente**. La consecuencia fueron bugs de plata
concretos y patrones contradictorios conviviendo en el mismo módulo:

1. **Proyección ARS del CC mal calculada**: la cuenta corriente del proveedor
   muestra una deuda USD usando un TC inadecuado (el del pedido en origen) en
   vez del TC explícito de la OP que la cancela. El "estimado consolidado ARS"
   (`cc-proveedor-mayor` REQ-CC-002) y la proyección por pedido no comparten una
   regla única sobre *qué TC usar para derivar pesos*.
2. **Bloqueo muerto "cross-moneda no soportado en v1"**: `imputaciones`
   REQ-IMP-003 y `ordenes-pago` `OPEN_QUESTION-OP-02` aún declaran prohibición
   cross-moneda; el código ya la relajó parcialmente, dejando spec y código en
   contradicción.
3. **Dolarización de montos peso-fijos (anti-patrón)**: el frontend
   `ModalOrdenPagoNueva.jsx` ("Option A", líneas ~417-433 y ~471-485) **reescribe
   el `monto` nativo de un ítem** al cambiar la moneda de la OP, multiplicando o
   dividiendo por el TC. Eso destruye el monto nativo del documento y abre la
   puerta a re-expandir un importe peso-fijo — exactamente lo prohibido.
4. **Varianza de TC invisible**: cuando el TC de registración del pedido difiere
   del TC de pago de la OP, esa diferencia se pierde visualmente — el usuario no
   puede observar cuánto pagó de más o de menos al tipo del pedido original.

La raíz es una sola: **falta un modelo de moneda canónico y documentado**. Este
change lo establece, alinea spec con código, y elimina los anti-patrones.

Éxito = un único modelo escrito ("store-native + derive-at-edge"), CC ARS
derivada con el TC correcto, sin bloqueos cross-moneda, sin dolarización de
peso-fijos, y la diferencia de TC visible en pantalla (observable, no contabilizada).

## What Changes

Este change es **fundacional y de definición** (modelo + invariantes). No
re-implementa el cross-moneda OP↔pedido que `compras-cross-moneda-y-ncs-cc` ya
dejó en código; lo **subsume, formaliza y corrige** donde contradice el modelo.

### Decisiones confirmadas (product owner — encodear, NO reabrir)

1. **Moneda funcional = ARS.** La empresa siempre **paga en ARS**. El peso es la
   unidad de medida de los resultados.
2. **Store-native.** Todo documento (pedido, OP, NC, ND) guarda su importe en su
   **propia moneda nativa** (`ARS` | `USD`) + un tag `moneda` + un
   `tc_snapshot` (el TC explícito del momento de ese documento). El equivalente
   en pesos se **deriva al borde** (al mostrar / al pagar), **nunca** se
   persiste como fuente de verdad.
3. **ARS = nominal fijo (invariante duro).** Un documento en pesos ($100 ARS)
   vale $100 ARS para siempre; **jamás** se re-pega por ningún TC.
   Dolarizar un importe peso-fijo y re-expandirlo después es el anti-patrón
   prohibido (ítem monetario / moneda funcional, IAS 21).
4. **USD lleva `tc_snapshot`.** Un pedido USD guarda USD + su TC al registrarse;
   no se re-pega diariamente (impracticable con la volatilidad cambiaria
   argentina). Se muestra en pesos al TC relevante según el contexto.
5. **La OP lleva su propio TC** = el TC al que el pago en ARS liquida la
   obligación USD. Es el TC de liquidación, distinto del TC de registración del
   pedido.
6. **Fuente del TC**: default = BNA (Banco Nación), **overridable** por TC del
   proveedor; en la práctica se **ingresa manualmente por documento**. Se
   almacena el TC numérico + un tag opcional de origen/tipo
   (`'bna' | 'proveedor'`) para auditoría.
7. **Cross-moneda NUNCA bloquea.** Se elimina el bloqueo duro por completo.
8. **Varianza de TC = display-only (decisión clave).** La diferencia entre el
   TC de registración del pedido y el TC de pago de la OP es **visible en
   pantalla** (observable por el usuario en cada documento), pero **NO se
   persiste como resultado contable P&L** en v1. Cada documento muestra el
   monto ARS correcto derivado al TC que le corresponde según su estado de
   liquidación (porción pagada al TC de la OP, porción pendiente al TC del
   pedido); la diferencia entre ambos es simplemente observable.
   — **REMOVED: Persistencia de resultado FX realizado / ledger `cc_resultado_cambio`
   — movido a Out-of-Scope.**
9. ~~**NC/ND = flag humano.**~~ **REMOVED — movido a Out-of-Scope.** No existe
   flag "falta NC/ND" ni botón de creación manual en v1.

### Trabajo concreto previsto (alto nivel — el detalle va a spec/design)

- **Modelo de datos store-native**: confirmar/formalizar `moneda` + `tc_snapshot`
  (+ tag de origen del TC) en pedido, OP, NC/ND; documentar que el equivalente
  ARS no se persiste.
- **Conversión derive-at-edge**: una regla única de derivación a pesos
  (qué TC usar en cada contexto: registración vs liquidación), consumida por la
  proyección del CC y por la UI.
- **Invariante ARS nominal fijo**: garantizar que ningún flujo re-pega un importe
  ARS por un TC; los ítems peso-fijos viajan intactos.
- **Eliminar el bloqueo cross-moneda** en spec y normalizar el código que ya lo
  relajó.
- **Varianza de TC visible**: cada documento muestra el monto ARS correcto al TC
  relevante; la diferencia entre el TC del pedido y el TC de la OP que paga es
  observable en pantalla. No se persiste como resultado P&L.
- **Proyección ARS del CC con el TC correcto**: la deuda USD se proyecta a pesos
  con el TC explícito que corresponde (el de la OP que paga, no el del pedido en
  origen).

### Estado del trabajo previo (a integrar bajo este modelo)

- **Fix AD-7 ya aplicado (sin commitear), tests verdes**: hace que las
  imputaciones USD same-moneda guarden el `tipo_cambio` de la OP (antes diferido
  como "AD-7"). Es **consistente con este modelo y queda subsumido** — se trata
  como primer paso coherente, no como excepción.
- **Frontend "Option A" — CONTRADICE el modelo**: la reescritura del `monto`
  nativo del ítem al cambiar la moneda de la OP
  (`ModalOrdenPagoNueva.jsx`, conversión de `items[].monto`) **debe revertirse /
  rediseñarse** bajo este change: el ítem conserva su monto nativo; la
  conversión a la moneda del flujo de pago se **deriva** para mostrar/liquidar,
  nunca se escribe sobre el dato nativo.

## Scope / Non-Goals

### In Scope (v1)

- Modelo de datos store-native (moneda nativa + `tc_snapshot` + tag de origen).
- Conversión derive-at-edge (regla única de derivación a pesos).
- Invariante ARS nominal fijo (peso-fijo nunca re-pegado).
- Snapshot de TC en USD por documento.
- Eliminación del bloqueo cross-moneda.
- Montos ARS **correctos y derivados** en cada documento al TC relevante; varianza de TC **visible** en pantalla.
- Proyección ARS del CC con el TC explícito correcto.

### Out of Scope (diferido explícitamente)

- **Revaluación de fin de período (diferencia de cambio NO realizada)** de saldos
  USD abiertos — es capa contable/reporting, no operativa.
- **Ajuste por inflación / RT 6 FACPCE** — concern de estados contables.
- **Auto-generación de NC/ND** — siempre decisión humana.
- **Migración de datos históricos** — los documentos viejos conservan su
  semántica original; no se reescriben imputaciones existentes.
- **Ledger de resultado FX realizado / tabla `cc_resultado_cambio`** — diferido.
  La diferencia de TC es observable en display; la contabilización P&L queda para
  un change posterior.
- **Flag "falta NC/ND" + botón de creación manual** — diferido. Sin trigger de
  señalización en v1.

## Impact

| Área | Impacto | Descripción |
|------|---------|-------------|
| `backend/app/services/imputaciones_service.py` | Modified | Formalizar store-native + TC por imputación |
| `backend/app/services/ordenes_pago_service.py` | Modified | `ejecutar_pago` deriva montos ARS correctos al TC de liquidación; varianza visible, no persistida |
| `backend/app/services/cc_proveedor_service.py` | Modified | Proyección ARS derivada con el TC correcto (porción pagada al TC de la OP, pendiente al tc_snapshot) |
| `backend/app/services/pedidos_service.py` | Modified | `tc_snapshot` del pedido como ancla de registración para derivación |
| `frontend/src/components/compras/ModalOrdenPagoNueva.jsx` | Modified | **Revertir "Option A"**: el ítem conserva monto nativo; conversión solo derivada |
| `frontend/.../TabCCProveedores.jsx` (CC) | Modified | Mostrar ARS derivado correcto con varianza de TC visible |
| Specs `modulo-compras/{imputaciones,ordenes-pago,cc-proveedor-mayor}.md` | Modified | Reemplazar la prohibición cross-moneda y el `OPEN_QUESTION-OP-02` por el modelo canónico |
| `backend/tests/` (pytest, strict TDD) | Modified + New | Tests del invariante ARS, derive-at-edge, proyección CC correcta |

### Compatibilidad y comportamiento

- **Aditivo en datos**: store-native ya es la forma de los documentos; lo que se
  agrega es el resultado FX y la formalización de la derivación. Sin reescritura
  de imputaciones históricas.
- **Spec ↔ código**: este change cierra la contradicción donde la spec decía
  "cross-moneda prohibido en v1" y el código ya lo permite con TC.
- **Strict TDD activo (backend)**: pytest, ~1226 tests, comando
  `cd backend && venv/bin/pytest tests/ -x`. Todo cambio de servicio entra con
  test primero. **Frontend**: solo ESLint (sin test runner) → la reversión de
  "Option A" se valida por QA manual + lint.

## Risks

| Riesgo | Likelihood | Mitigación |
|--------|-----------|------------|
| Re-introducir dolarización de peso-fijo en algún flujo de derivación | Med | Invariante explícito + tests que verifican que un ítem ARS nunca cambia su `monto` nativo ante cualquier TC |
| Elegir el TC equivocado al derivar ARS en el CC (origen vs liquidación) | High | Regla única documentada: deuda pagada se proyecta con el TC de la OP que la cancela; deuda viva usa `tc_snapshot` del pedido |
| Política de redondeo (HALF_EVEN vs HALF_UP) no definida — heredada de `compras-cross-moneda-y-ncs-cc §11` | Med | Resolver en design con el criterio contable; aplicar consistentemente en toda derivación |

## Open Questions resueltas de `compras-cross-moneda-y-ncs-cc`

- **§11 "TC ponderado / reversals"** → el modelo canónico define que la deuda se
  proyecta con TC explícito y el delta TC es resultado FX por imputación; el TC
  ponderado pasa a ser métrica derivada, no fuente de verdad.
- **`OPEN_QUESTION-OP-02` (prohibir cross-moneda v1)** → **resuelto**:
  cross-moneda nunca bloquea (decisión 7).
- **`OPEN_QUESTION-IMP` moneda inconsistente** → **resuelto**: cross-moneda con
  TC explícito es válido; la consistencia se verifica vía `tc_snapshot`, no
  prohibiendo la combinación.
- **§11 redondeo** → queda como única open question técnica a cerrar en design
  (HALF_EVEN vs HALF_UP), con criterio contable.

## Dependencies

- Ninguna externa. Todo dentro del módulo `compras`.
- Reutiliza el campo `tipo_cambio` en `ordenes_pago` e `imputaciones` (ya existe
  desde `compras-cross-moneda-y-ncs-cc`).
- El fix AD-7 (uncommitted) es el primer paso consistente y se integra acá.

## Next Phase

`sdd-spec` y `sdd-design` (pueden correr en paralelo). Spec formaliza los
requisitos del modelo (invariante ARS, derive-at-edge, montos ARS correctos con
varianza visible, proyección CC). Design decide la regla de derivación a pesos
y la política de redondeo.

# Spec Delta — Modelo de Moneda del Módulo de Compras

**Change:** compras-modelo-moneda
**Capability:** modelo-moneda (fundacional — cubre pedidos, OPs, imputaciones, CC proveedor)
**Status:** draft

## Purpose

Formalizar el modelo canónico de moneda "store-native + derive-at-edge" para todo el módulo
de compras. Establece los invariantes, reglas de derivación, montos ARS correctos con
varianza de TC visible en pantalla (no contabilizada en v1). Cierra los open questions
`OPEN_QUESTION-OP-02` y `OPEN_QUESTION-IMP-02` (cross-moneda) y **supersede** las
restricciones de `REQ-IMP-003` (prohibición de moneda inconsistente) y del borrador
`OPEN_QUESTION-OP-02` (prohibir cross-moneda v1) de `modulo-compras`.

## Supersessions

> Estos requisitos REEMPLAZAN parcialmente texto de la spec `modulo-compras`:
>
> - **REQ-IMP-003 § párrafo 2** ("moneda_imputada == moneda del origen == moneda del destino"):
>   supersedido por **REQ-MM-004** (cross-moneda con TC explícito es válido).
>   La validación de proveedor consistente (párrafo 1) y `monto_imputado > 0` (párrafo 3)
>   permanecen vigentes.
> - **OPEN_QUESTION-OP-02** ("prohibir cross-moneda en v1"): resuelto y cerrado.
>   El nuevo requisito es **REQ-MM-004**: cross-moneda nunca bloquea si hay TC explícito.

---

## ADDED Requirements

### Requirement: REQ-MM-001 — Store-native: cada documento guarda su moneda nativa

**Priority:** must
**Type:** functional

Todo documento del módulo de compras (pedido, OP, NC, ND) MUST persistir:

- `monto` en su **moneda nativa** (`ARS` | `USD`).
- `moneda` (VARCHAR NOT NULL, `ARS` | `USD`).
- `tc_snapshot` (NUMERIC NULL): TC explícito al momento de creación del documento.
  - Para documentos `moneda='ARS'`: `tc_snapshot = NULL` (no aplica — el peso no lleva TC).
  - Para documentos `moneda='USD'`: `tc_snapshot` MUST ser NOT NULL y > 0.
- `tc_fuente` (VARCHAR NULL, `'bna'` | `'proveedor'`): tag de origen del TC, para auditoría.
  Solo relevante cuando `tc_snapshot IS NOT NULL`.

El equivalente en pesos de un documento USD MUST derivarse al borde (en servicio o UI);
NO SHALL persistirse como fuente de verdad en ninguna tabla.

#### Scenario: Pedido ARS — tc_snapshot nulo

- GIVEN un pedido con `monto=50000`, `moneda='ARS'`
- WHEN se registra el pedido
- THEN `tc_snapshot IS NULL`
- AND `tc_fuente IS NULL`
- AND el valor $50 000 ARS no varía ante ningún cambio de TC posterior

#### Scenario: Pedido USD — tc_snapshot requerido

- GIVEN un pedido con `monto=1000`, `moneda='USD'`, `tc_snapshot=1000.00`, `tc_fuente='bna'`
- WHEN se registra el pedido
- THEN `tc_snapshot = 1000.00` persiste en la fila del pedido
- AND `tc_fuente = 'bna'`
- AND el equivalente ARS proyectado al momento de registración = `1000 × 1000.00 = 1 000 000 ARS`
  (solo para display; no se persiste)

#### Scenario: Intento de registrar pedido USD sin tc_snapshot

- GIVEN un request de creación de pedido con `moneda='USD'` y `tc_snapshot` ausente o nulo
- WHEN se invoca el endpoint de creación
- THEN el sistema MUST responder HTTP 422 con `"tc_snapshot es requerido para documentos USD"`
- AND el pedido NO SHALL persistirse

---

### Requirement: REQ-MM-002 — Invariante ARS nominal fijo (duro)

**Priority:** must
**Type:** constraint

Un documento con `moneda='ARS'` representa un importe en pesos **fijo y definitivo**.
Su `monto` nativo NO SHALL modificarse por ningún flujo que involucre TC (cambio de moneda
de la OP, actualización de TC de referencia, cambio de `tc_fuente`, ni ninguna otra razón).

El anti-patrón prohibido es: tomar un ítem ARS, dividirlo por un TC para "dolarizarlo",
luego multiplicarlo por otro TC para re-expandirlo. Esto destruye el monto nativo.

Cualquier código que reciba un documento con `moneda='ARS'` MUST tratar `monto` como opaco
y pasarlo intacto. La conversión a otra moneda es solo derivada (display/liquidación).

#### Scenario: Cambio de TC de la OP no altera monto de ítem ARS

- GIVEN una OP con un ítem (pedido o línea) con `moneda='ARS'`, `monto=50000`
- WHEN el usuario cambia la moneda de la OP de `ARS` a `USD` (o viceversa)
- THEN el `monto` nativo del ítem MUST seguir siendo `50000 ARS`
- AND NO SHALL reescribirse como `50000 / TC` ni como `50000 * TC`
- AND el frontend MUST derivar el equivalente para mostrar, no persistirlo

#### Scenario: Re-peg prohibido explícito

- GIVEN un pedido con `id=10`, `moneda='ARS'`, `monto=80000`, `tc_snapshot=NULL`
- WHEN se actualiza cualquier TC de referencia en el sistema (BNA, proveedor, etc.)
- THEN `pedidos_compra.monto WHERE id=10` MUST seguir siendo `80000`
- AND `pedidos_compra.tc_snapshot WHERE id=10` MUST seguir siendo `NULL`

---

### Requirement: REQ-MM-003 — La OP lleva su propio TC de liquidación

**Priority:** must
**Type:** functional

La OP MUST almacenar `tipo_cambio` (ya existente en el modelo `ordenes_pago`) como el
**TC de liquidación**: la tasa a la que el pago en ARS cancela la obligación USD en el
momento de ejecutar el pago.

Este TC es conceptualmente distinto del `tc_snapshot` del pedido (TC de registración).
Ambos pueden diferir; esa diferencia es la base del resultado por diferencia de cambio
(ver REQ-MM-006).

- Para una OP `moneda='ARS'` que paga obligaciones ARS: `tipo_cambio = NULL`.
- Para una OP `moneda='ARS'` que paga obligaciones USD (cross-moneda): `tipo_cambio` MUST
  ser NOT NULL y > 0 al momento de ejecutar el pago.
- Para una OP `moneda='USD'`: `tipo_cambio` MUST ser NOT NULL (TC del pedido USD al momento
  del pago; puede diferir del `tc_snapshot` del pedido).

#### Scenario: OP ARS pagando deuda USD — TC de liquidación requerido

- GIVEN una OP con `moneda='ARS'`, `monto_total=1 450 000` que imputa a un pedido con
  `moneda='USD'`, `monto=1000`, `tc_snapshot=1000.00`
- WHEN se invoca `POST /ordenes-pago/{id}/pagar` sin `tipo_cambio`
- THEN el sistema MUST responder HTTP 422 con
  `"tipo_cambio es requerido para OPs que liquidan obligaciones USD"`
- AND el pago NO SHALL ejecutarse

#### Scenario: OP ARS pagando deuda ARS — TC de liquidación nulo

- GIVEN una OP con `moneda='ARS'` que imputa exclusivamente a pedidos `moneda='ARS'`
- WHEN se invoca `/pagar` sin `tipo_cambio`
- THEN el sistema MUST proceder (TC nulo es válido para este caso)

---

### Requirement: REQ-MM-004 — Cross-moneda nunca bloquea con TC explícito

**Priority:** must
**Type:** constraint

> **Supersede:** REQ-IMP-003 párrafo 2 (moneda inconsistente → HTTP 400) y
> OPEN_QUESTION-OP-02 de `modulo-compras/specs/ordenes-pago.md`.

El sistema MUST NOT rechazar una operación de imputación o pago únicamente porque la
moneda del origen difiera de la moneda del destino.

Una imputación cross-moneda (ej. OP `ARS` → pedido `USD`) es válida si y solo si:
- `tipo_cambio` en la imputación es NOT NULL y > 0.

Si se recibe una imputación cross-moneda sin `tipo_cambio`, el sistema MUST responder
HTTP 422 con `"tipo_cambio es requerido para imputaciones cross-moneda"`.

La validación de `proveedor_id` consistente entre origen y destino (REQ-IMP-003 párrafo 1)
continúa vigente.

#### Scenario: Imputación cross-moneda con TC — procede

- GIVEN una OP con `id=200`, `moneda='ARS'`, `monto_total=1 450 000`, `proveedor_id=7`
- AND un pedido con `id=55`, `moneda='USD'`, `monto=1000`, `proveedor_id=7`
- AND la imputación incluye `tipo_cambio=1450.00`
- WHEN se crea la imputación `(OP=200, pedido=55, monto_imputado=1000, moneda_imputada='USD', tipo_cambio=1450.00)`
- THEN la imputación MUST persistirse exitosamente
- AND NO SHALL responderse HTTP 400 por moneda inconsistente

#### Scenario: Imputación cross-moneda sin TC — rechazada

- GIVEN el mismo par (OP ARS + pedido USD)
- WHEN se intenta crear la imputación sin `tipo_cambio` (o `tipo_cambio=null`)
- THEN el sistema MUST responder HTTP 422 con
  `"tipo_cambio es requerido para imputaciones cross-moneda"`
- AND la imputación NO SHALL persistirse

#### Scenario: Imputación same-moneda ARS — TC no requerido

- GIVEN una OP `moneda='ARS'` y un pedido `moneda='ARS'`
- WHEN se crea la imputación sin `tipo_cambio`
- THEN la imputación MUST persistirse exitosamente

---

### Requirement: REQ-MM-005 — Fuente del TC: BNA por defecto, overridable

**Priority:** must
**Type:** functional

El sistema MUST aceptar un TC ingresado manualmente por documento, acompañado del tag
de fuente:

- `tc_fuente = 'bna'`: TC del Banco Nación Argentina (default sugerido).
- `tc_fuente = 'proveedor'`: TC acordado con el proveedor para esa operación.

El tag es informativo y de auditoría. No altera la lógica de cómputo; el TC numérico es
el único valor operativo.

No existe un servicio de cotización automática en v1; el TC siempre se ingresa
manualmente por documento.

#### Scenario: TC con fuente BNA

- GIVEN un pedido USD con `tc_snapshot=1000.00`, `tc_fuente='bna'`
- WHEN se consulta el pedido
- THEN `tc_snapshot = 1000.00` y `tc_fuente = 'bna'` son accesibles en la respuesta

#### Scenario: TC con fuente proveedor

- GIVEN una OP con `tipo_cambio=1410.00`, `tc_fuente='proveedor'`
- WHEN se ejecuta el pago
- THEN el sistema MUST persistir `tc_fuente='proveedor'` en el registro de la OP
- AND el cómputo del resultado FX MUST usar `1410.00` como TC de liquidación (ver REQ-MM-006)

---

### Requirement: REQ-MM-006 — Varianza de TC visible; montos ARS correctos en todo documento

**Priority:** must
**Type:** functional

> **Scope note (v1):** La varianza entre el TC de registración del pedido y el TC de pago
> de la OP es **display-only**: cada documento muestra el monto ARS derivado al TC que le
> corresponde, y la diferencia es **observable en pantalla**. NO se persiste ningún ledger
> de resultado P&L de diferencia de cambio en v1.
> (La contabilización P&L queda diferida — ver Out-of-Scope del proposal.)

Cuando una OP liquida una deuda USD, el sistema MUST derivar y mostrar montos ARS correctos:

- **Porción pagada** de la deuda USD: mostrar el equivalente ARS usando el `tipo_cambio` de
  la OP que ejecutó el pago (TC de liquidación efectiva).
- **Porción pendiente** (deuda viva no pagada): mostrar usando el `tc_snapshot` del pedido
  (TC de registración).
- La diferencia entre `(TC_OP − TC_pedido_snapshot) × USD_imputado` MUST ser computable y
  **visible en la UI** al consultar el detalle de imputación o el CC del proveedor, para que
  el usuario pueda observar cuánto pagó de más o de menos respecto del TC original.
- El saldo del proveedor en `cc_proveedor_movimientos` MUST NOT verse afectado por esta
  diferencia (no es deuda, no es NC/ND).

#### Scenario: Montos ARS correctos — cada porción al TC que le corresponde

- GIVEN un pedido con `id=55`, `moneda='USD'`, `monto=1000`, `tc_snapshot=1000.00`
- AND una OP con `tipo_cambio=1450.00` que imputa USD 1000 a ese pedido
- WHEN se consulta el CC o el detalle de la imputación
- THEN el monto ARS de la porción pagada se muestra como `1000 × 1450.00 = 1 450 000 ARS`
- AND la varianza respecto del TC original es visible: `(1450.00 − 1000.00) × 1000 = 450 000 ARS`
- AND el saldo del proveedor NO cambia por esta observación

#### Scenario: TCs iguales — sin varianza visible

- GIVEN un pedido con `id=56`, `moneda='USD'`, `monto=1000`, `tc_snapshot=1000.00`
- AND una OP con `tipo_cambio=1000.00` que imputa USD 1000 a ese pedido
- WHEN se consulta la imputación
- THEN el monto ARS derivado = `1000 × 1000.00 = 1 000 000 ARS`
- AND la varianza visible = 0 (sin diferencia de TC)

#### Scenario: Pagos parciales — cada porción al TC de su propia OP

- GIVEN un pedido con `id=60`, `moneda='USD'`, `monto=2000`, `tc_snapshot=1000.00`
- AND una primera OP con `tipo_cambio=1410.00` imputa USD 1000 (pago parcial)
- AND una segunda OP con `tipo_cambio=1450.00` imputa USD 1000 (pago del remanente)
- WHEN se consulta el CC del proveedor
- THEN primera porción: `1000 × 1410.00 = 1 410 000 ARS` (con varianza visible: +410 000)
- AND segunda porción: `1000 × 1450.00 = 1 450 000 ARS` (con varianza visible: +450 000)
- AND el saldo USD del proveedor queda en 0 (deuda cancelada)

---

### Requirement: REQ-MM-007 — Proyección ARS del CC usa TC de la OP que cancela

**Priority:** must
**Type:** functional

Al proyectar el saldo USD de un proveedor a pesos (para el campo
`saldo_consolidado_estimado_ars` de REQ-CC-002), la regla de derivación MUST ser:

- **Porción ya pagada** de una deuda USD: proyectar con el `tipo_cambio` de la OP que
  ejecutó el pago (TC de liquidación efectiva).
- **Porción pendiente** (deuda USD abierta, no pagada): proyectar con el TC de referencia
  del momento de consulta (BNA del día, ingresado o disponible).

El TC de registración del pedido (`tc_snapshot`) NO SHALL usarse para proyectar el ARS
del saldo consolidado de CC, salvo que sea el único TC disponible para una deuda no pagada.

#### Scenario: Deuda USD pagada — proyectada con TC de liquidación

- GIVEN un pedido con `monto=1000 USD`, `tc_snapshot=1000.00`
- AND una OP que pagó USD 800 con `tipo_cambio=1410.00`
- WHEN se calcula la proyección ARS del CC del proveedor
- THEN los USD 800 pagados se valorizan a `800 × 1410.00 = 1 128 000 ARS` (costo real)
- AND los USD 200 pendientes se valorizan al TC del día (o al disponible en consulta)

#### Scenario: Proyección NO usa tc_snapshot del pedido para porción pagada

- GIVEN el escenario anterior
- WHEN se consulta el CC del proveedor
- THEN el sistema MUST NOT calcular la porción pagada como `800 × 1000.00 = 800 000 ARS`
  (eso usaría el TC de registración, que no refleja el costo real)

---

---
> **REQ-MM-008 — REMOVED (moved to Out-of-Scope)**
> El flag "falta NC/ND" + botón de creación manual no se implementa en v1.
> La varianza de TC visible (REQ-MM-006) no es NC/ND; son conceptos distintos.
> La señalización de NC/ND pendiente queda diferida a un change posterior.
---

## OPEN POINTS

- **OPEN_POINT-MM-01:** ~~Criterio de disparo del flag "falta NC/ND"~~ — **REMOVED**.
  REQ-MM-008 se movió a Out-of-Scope; este open point queda cerrado/diferido.

- **OPEN_POINT-MM-02:** Política de redondeo para la derivación ARS y la varianza de TC
  visible (HALF_EVEN vs HALF_UP vs HALF_UP-contable). Heredado de
  `compras-cross-moneda-y-ncs-cc §11`. A resolver en `sdd-design` con criterio contable;
  aplicar consistentemente en toda derivación.

## Out-of-Scope (deferred from this change)

- **Ledger de resultado FX realizado / tabla `cc_resultado_cambio`**: la contabilización
  P&L de diferencia de cambio queda diferida. En v1 la varianza es solo visible (REQ-MM-006).
- **Flag "falta NC/ND" + botón de creación manual** (REQ-MM-008): diferido a un change
  posterior. La señalización de NC/ND pendiente no se implementa en v1.

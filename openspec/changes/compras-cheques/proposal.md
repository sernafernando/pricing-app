# Proposal — Módulo de Cheques como medio de pago

**Change ID:** `compras-cheques`
**Fase:** proposal
**Status:** draft
**Owner:** Compras + Tesorería
**Fecha:** 2026-06-19
**Persistence:** hybrid (este archivo + engram `sdd/compras-cheques/proposal`)
**Research base:** engram `learning/deep-research-...` (Odoo l10n_latam_check, BCRA ECHEQ, Xubio, Colppy, Tango) — 23 claims verificados.
**Depende de:** OP existente (`ordenes_pago`) con caja/banco como fuente de fondos; `cc_proveedor_movimiento`; `banco_empresa`/`banco_movimiento`.

---

## Why

Hoy la Orden de Pago (OP) solo permite pagar a proveedores con **caja** o **banco** (transferencia/efectivo). El cheque —el instrumento más usado en compras B2B en Argentina, hoy mayormente **e-cheq**— **no existe** en el sistema. Quedó explícitamente diferido ("los cheques los dejamos para otro sprint").

Problemas concretos:

1. **No se puede pagar con cheque**: el operador paga con cheque por fuera del sistema y después "ajusta" a mano, perdiendo trazabilidad del instrumento (número, banco, fecha, estado).
2. **Cheques de terceros sin circuito**: los cheques que se reciben de clientes no se registran ni se pueden **endosar** a un proveedor. Es plata inmovilizada e invisible.
3. **Diferidos sin control de fecha**: un cheque a 30/60/90 días no tiene fecha de pago modelada; no se sabe cuándo impacta en el banco.
4. **Sin conciliación**: cuando el banco debita un cheque propio o acredita un cheque depositado, no hay forma de conciliar ese movimiento real contra el instrumento.

El negocio necesita: **registrar cheques (propios y de terceros, físicos y e-cheq, al día y diferidos), usarlos como medio de pago en la OP —combinables con caja/banco—, y conciliar el cobro/débito real contra el banco.**

---

## What

Un **módulo de cheques** con dos categorías operativamente separadas (decisión central del dominio, compartida por Odoo/Tango/Xubio/Colppy):

- **Cheques PROPIOS** — los emitimos contra nuestro `banco_empresa`, con **chequera** y numeración. Se usan para **pagar** una OP.
- **Cheques de TERCEROS** — los recibimos de clientes, quedan **en cartera**, y se **endosan** a un proveedor en una OP.

Cada categoría tiene su propia **máquina de estados**. Ambas comparten una entidad `cheque` con un campo `instrumento` (`fisico` | `echeq`) — el e-cheq NO es un módulo aparte, es un tipo del mismo cheque (suma estados aceptado/rechazado/custodia).

El cheque entra a la OP como un **medio de pago más**, vía una tabla de enlace, de modo que una OP pueda combinar **cheque + caja + banco**. El alcance contable se integra a la **tesorería existente** (no hay GL de doble partida — ver LD7).

**Frontend (con Stitch):**
- Pantalla de **gestión de cheques** (cartera de terceros + emitidos propios), con filtros por estado/tipo/banco/fecha.
- Pantalla de **recepción de cheque de tercero** (alta en cartera).
- Pantalla de **emisión de cheque propio** (contra chequera).
- Integración en el **modal de OP**: selector "Cheque" como fuente, listando cheques de cartera (terceros) o emitiendo uno propio.
- Pantalla de **conciliación** (marcar cobrado/debitado contra el banco).

---

## Locked Product Decisions

Cerradas con el usuario (ronda de scope) + la investigación.

### LD1 — Propios vs Terceros: dos máquinas de estado separadas
La separación es la decisión de modelado más importante (compartida por TODOS los ERP relevados). Una sola entidad `cheque` con `tipo ∈ {propio, tercero}`, pero **transiciones y validaciones distintas** por tipo.

- **Propios:** `emitido` | `diferido` → `debitado` (cobrado por el banco). Excepción: `rechazado`, `anulado`.
- **Terceros:** `en_cartera` → `entregado` (endosado a proveedor) | `depositado` → `acreditado`. Excepción: `rechazado`, `anulado`. (Estados e-cheq adicionales: ver LD3.)

### LD2 — Scope completo (4 ejes confirmados)
- **Ambos** tipos (propios + terceros).
- **Físico + e-cheq** desde el arranque (`instrumento`).
- **Diferidos** incluidos (`fecha_emision` ≠ `fecha_pago`).
- **Full contable + conciliación** (interpretado como tesorería existente — ver LD7).

### LD3 — e-cheq como `instrumento`, no módulo aparte
`instrumento ∈ {fisico, echeq}` sobre la misma entidad. El e-cheq suma estados/atributos:
- Estados extra: `aceptado` / `rechazado_emision` (el receptor acepta/rechaza hasta el vencimiento), `en_custodia`.
- La numeración del e-cheq **la asigna el banco** (no la chequera local).
- **Sin integración con rieles bancarios** (API del banco) en este change: el e-cheq se carga/actualiza manualmente. La integración automática (callbacks de estado, número del banco) es follow-up. Ver D-ECHEQ.

### LD4 — Diferidos: dos fechas
Todo cheque lleva `fecha_emision` y `fecha_pago`. `es_diferido = fecha_pago > fecha_emision`. **No se puede depositar/cobrar/debitar un cheque antes de su `fecha_pago`** (validación dura).

### LD5 — El cheque es un medio de pago de la OP (combinable)
Tabla de enlace `orden_pago_cheque` (o medio de pago genérico) entre OP y cheque, NO una columna `medio_pago` única en la OP. Permite **cheque + caja + banco** en una sola OP. La cobertura/balance de la OP (ya existente, `validar_balance_op`) suma el cheque como un componente más.

- Pagar con **propio** → se **emite** un cheque nuevo (estado `emitido`/`diferido`) asociado a la OP.
- Pagar con **tercero** → se **endosa** un cheque de cartera (estado `en_cartera` → `entregado`) asociado a la OP.

### LD6 — Chequera para propios
Entidad `chequera` (banco_empresa + rango de numeración + próximo número sugerido editable). Un cheque propio físico toma su número de la chequera. El e-cheq propio no usa chequera (número del banco).

### LD7 — "Full contable" = tesorería existente, NO general ledger
**No existe** módulo de contabilidad de doble partida (ni plan de cuentas ni asientos) en el sistema. Lo que hay: `caja`, `banco_empresa`/`banco_movimiento`, `cc_proveedor_movimiento`. Por lo tanto "full contable" se implementa como:
- El cheque refleja **dónde está la plata** vía su estado (cartera / entregado / depositado / debitado).
- El **movimiento bancario real** (`banco_movimiento`) se genera en el momento correcto del ciclo de vida: cheque propio **debitado** → egreso de banco; cheque de tercero **acreditado** (depositado y cobrado) → ingreso de banco.
- **Conciliación = paso EXPLÍCITO** (no automático al depositar — verificado en la investigación). El usuario marca el cobro/débito real contra el extracto.
- La imputación al proveedor (reducción de saldo en `cc_proveedor`) ocurre al **entregar/emitir** el cheque en la OP (igual que hoy con caja/banco), no al cobrarse.

> ✅ **Confirmado con el usuario:** "full contable" = integración a la tesorería existente + conciliación. NO se construye libro mayor de doble partida ahora. El usuario lo deja como **posible a futuro**, así que el diseño debe **no impedirlo**: los eventos del ciclo de vida del cheque (emitido/entregado/depositado/debitado/acreditado) se modelan de forma limpia y auditable, de modo que un módulo de GL futuro pueda engancharse a esos eventos sin rehacer el módulo de cheques.

### LD8 — Validaciones mínimas
Por cheque: `numero`, `banco`, `cuit_librador` (terceros), `monto`, `moneda`, `fecha_emision`, `fecha_pago`. Numeración única por chequera (propios). `rechazado`/`anulado` son terminales con transición guardada. No depositar diferido antes de `fecha_pago`.

---

## Slices (PRs encadenados)

El scope completo NO entra en un PR. Se entrega en slices con valor incremental:

- **Slice 1 — Núcleo + cheque PROPIO en la OP.** Entidad `cheque` + `chequera` + migración + estados propios (emitido/diferido/debitado/rechazado/anulado). Emitir un cheque propio como medio de pago en la OP (combinable con caja/banco). Físico. Imputación a `cc_proveedor` al emitir. Frontend: emisión + selector en OP. **Entrega valor real: pagar proveedores con cheque propio.**
- **Slice 2 — Cheques de TERCEROS + cartera + endoso.** Recepción de cheque de cliente (alta en cartera) + endoso a proveedor en la OP. Pantalla de cartera. Estados terceros.
- **Slice 3 — e-cheq.** `instrumento=echeq` + estados aceptado/rechazado_emision/custodia (carga manual). Aplica a propios y terceros.
- **Slice 4 — Conciliación bancaria.** Marcar debitado (propio) / acreditado (tercero) contra `banco_movimiento`, paso explícito de conciliación. Reporte de cheques por estado.

Cada slice respeta el presupuesto de ~400 líneas; si excede, se sub-divide (skill `chained-pr`).

---

## Risks

- **R1 — Balance de la OP:** sumar el cheque a `validar_balance_op` sin romper el modelo net-item/tolerancia actual. Mitigación: el cheque es un componente de cobertura más, en moneda OP, con la misma tolerancia de medio centavo.
- **R2 — Cross-moneda:** un cheque puede estar en ARS y la OP en USD (o viceversa), igual que pasó con facturas. Mitigación: aplicar el mismo derive-at-edge por TC ya establecido.
- **R3 — Doble cobro/anulación:** evitar que un cheque entregado se reuse o que un anulado siga activo. Mitigación: estados terminales + constraint de unicidad de cheque por OP activa.
- **R4 — Terceros sin circuito de cobranzas:** el sistema no tiene módulo de ventas/cobranzas; la recepción de cheque de tercero será un alta directa a cartera (no atada a una cobranza). Aceptado para este scope.
- **R5 — Scope grande:** 4 slices encadenados. Riesgo de scope creep. Mitigación: cada slice es shippable y verificable solo.

---

## Open Decisions (a resolver en spec/design)

- **D1 — "Full contable":** ✅ RESUELTO. Tesorería + conciliación ahora; GL de doble partida queda como posible follow-up futuro. El diseño no debe impedir engancharlo después (LD7).
- **D2 — Permiso:** ✅ RESUELTO. Permiso **nuevo** `tesoreria.gestionar_cheques` (gatea carga, listado y uso de cheques). No se reusa `gestionar_ordenes_compra`.
- **D3 — UI de cheques:** ✅ RESUELTO. **Modal nuevo** para la carga/alta de cheques + **página nueva** para ver los cheques disponibles (cartera/listado con filtros). Es un área propia de cheques, no embebida en compras.
- **D-ECHEQ — Integración bancaria:** e-cheq manual en este change; ¿hay apetito/feasibility de integrar rieles del banco (número, callbacks de estado) como follow-up?
- **D4 — Estados intermedios terceros:** ¿`depositado` y `acreditado` son dos estados o uno con sub-estado? (depende de cuánto control de conciliación se quiera).

---

## Non-Goals

- Construir un libro mayor / plan de cuentas de doble partida.
- Integración automática con APIs bancarias / ECHEQ rails (follow-up).
- Módulo de ventas/cobranzas (la recepción de tercero es alta directa a cartera).
- Descuento/negociación de cheques en mercado (mencionado por BCRA, fuera de scope).

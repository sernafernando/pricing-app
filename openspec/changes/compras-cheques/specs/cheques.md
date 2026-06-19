# Spec — Módulo de Cheques

**Change ID:** `compras-cheques`
**Fase:** spec
**Status:** draft
**Scope de este spec:** Slice 1 detallado (cheque propio como medio de pago en la OP); Slices 2-4 esbozados.

---

## Glosario

- **Cheque propio:** lo emite la empresa contra su `banco_empresa`, con chequera/numeración. Sirve para pagar.
- **Cheque de tercero:** recibido de un cliente, en cartera; se endosa a un proveedor.
- **Instrumento:** `fisico` | `echeq`.
- **Diferido:** `fecha_pago > fecha_emision`.
- **Cartera:** cheques de tercero disponibles para endosar.

---

## Slice 1 — Cheque propio como medio de pago

### FR-1.1 — Chequera de banco propio
El sistema DEBE permitir registrar **chequeras** asociadas a un `banco_empresa`, con: descripción, número desde / hasta, próximo número (sugerido, editable), `instrumento` por default (`fisico`), activa.

**Escenario 1.1.a — Alta de chequera**
- DADO un `banco_empresa` activo
- CUANDO se crea una chequera con rango 00000001–00000050
- ENTONCES el próximo número sugerido es 00000001 y la chequera queda activa.

**Escenario 1.1.b — Próximo número avanza al emitir**
- DADO una chequera con próximo número 00000010
- CUANDO se emite un cheque propio tomando esa chequera
- ENTONCES el cheque toma 00000010 y el próximo número pasa a 00000011.

### FR-1.2 — Emitir cheque propio como medio de pago en la OP
El sistema DEBE permitir, al crear/pagar una OP, **emitir un cheque propio** como (uno de los) medios de pago, combinable con caja/banco.

Datos del cheque propio: `banco_empresa_id`, `chequera_id` (físico), `numero`, `monto`, `moneda`, `fecha_emision`, `fecha_pago`, `beneficiario` (= proveedor de la OP), `instrumento`.

**Escenario 1.2.a — Pago total con un cheque propio al día**
- DADO una OP en ARS por 1.000.000 a un proveedor
- CUANDO se emite un cheque propio ARS por 1.000.000 con `fecha_pago = fecha_emision`
- ENTONCES el cheque queda en estado `emitido`, la OP queda cubierta (diferencia 0), y se imputa al `cc_proveedor` (reduce saldo).

**Escenario 1.2.b — Pago combinado cheque + caja**
- DADO una OP por 1.000.000
- CUANDO se emite un cheque propio por 700.000 y se paga 300.000 con caja
- ENTONCES la cobertura suma 1.000.000 (diferencia 0) y se registran ambos medios.

**Escenario 1.2.c — Cheque diferido**
- DADO una OP por 500.000
- CUANDO se emite un cheque propio con `fecha_pago = fecha_emision + 60 días`
- ENTONCES el cheque queda en estado `diferido` (no `emitido`), con su `fecha_pago` registrada.

**Escenario 1.2.d — Cross-moneda (cheque ARS, OP USD)**
- DADO una OP en USD con TC explícito
- CUANDO se emite un cheque ARS
- ENTONCES la cobertura se deriva por TC (mismo derive-at-edge que el resto), una sola conversión.

### FR-1.3 — Balance de la OP incluye el cheque
`validar_balance_op` DEBE contar el/los cheque(s) como componente de cobertura, en moneda OP, con la misma tolerancia de medio centavo.

**Escenario 1.3.a — Falta cubrir**
- DADO una OP por 1.000.000 y un cheque por 600.000 sin otro medio
- CUANDO se intenta confirmar el pago
- ENTONCES falla con diferencia 400.000 (FALTA CUBRIR).

### FR-1.4 — Estados del cheque propio
`emitido` | `diferido` → `debitado` · excepción `rechazado`, `anulado`. Transiciones guardadas (rechaza saltos inválidos). `anulado` libera la numeración solo si es el último de la chequera (regla a confirmar en design).

**Escenario 1.4.a — Anular cheque emitido**
- DADO un cheque `emitido` asociado a una OP pendiente
- CUANDO se anula (con motivo)
- ENTONCES pasa a `anulado`, se revierte la imputación al `cc_proveedor`, y la OP vuelve a quedar sin cubrir por ese monto.

### FR-1.5 — Permiso `tesoreria.gestionar_cheques`
Todos los endpoints de cheques (chequeras, emisión, listado, transiciones) DEBEN exigir el permiso nuevo `tesoreria.gestionar_cheques`. Se crea en migración, sin asignar a ningún rol por default.

**Escenario 1.5.a — Sin permiso → 403**
- DADO un usuario sin `tesoreria.gestionar_cheques`
- CUANDO llama a cualquier endpoint de cheques
- ENTONCES recibe 403.

### FR-1.6 — UI: modal de carga + página de listado
- **Modal nuevo** de alta/emisión de cheque (propio en Slice 1), invocable desde la OP y desde la página de cheques.
- **Página nueva** de cheques con filtros (estado, tipo, banco, fecha, moneda) y acciones por estado.

**Escenario 1.6.a — Listar emitidos**
- DADO 3 cheques propios emitidos
- CUANDO se abre la página de cheques filtrando por tipo=propio
- ENTONCES se listan los 3 con número, banco, monto, fecha_pago y estado.

---

## Slice 2 — Cheques de terceros (esbozo)

- **FR-2.1** Alta de cheque de tercero a **cartera** (modal de carga): `banco`, `cuit_librador`, `numero`, `monto`, `moneda`, `fecha_emision`, `fecha_pago`. Estado inicial `en_cartera`.
- **FR-2.2** Endosar un cheque de cartera a un proveedor en la OP (medio de pago): `en_cartera → entregado`, imputa a `cc_proveedor`.
- **FR-2.3** Página de cartera: cheques `en_cartera` disponibles para endosar/depositar.
- **FR-2.4** Estados terceros: `en_cartera → entregado | depositado → acreditado` · `rechazado`, `anulado`.

## Slice 3 — e-cheq (esbozo)

- **FR-3.1** `instrumento=echeq` en propios y terceros. Número del banco (no chequera).
- **FR-3.2** Estados extra: `aceptado`, `rechazado_emision`, `en_custodia`. Carga/actualización manual.

## Slice 4 — Conciliación bancaria (esbozo)

- **FR-4.1** Marcar cheque propio `debitado` → genera/concilia `banco_movimiento` (egreso).
- **FR-4.2** Marcar cheque de tercero `acreditado` → genera/concilia `banco_movimiento` (ingreso).
- **FR-4.3** Validación: no debitar/cobrar antes de `fecha_pago`.
- **FR-4.4** Reporte de cheques por estado (cartera, a debitar, vencidos).

---

## No-Goals (recordatorio)

GL de doble partida; integración automática con rieles bancarios/ECHEQ; módulo de cobranzas; descuento de cheques en mercado.

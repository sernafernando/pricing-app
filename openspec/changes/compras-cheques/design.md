# Design — Módulo de Cheques

**Change ID:** `compras-cheques`
**Fase:** design
**Status:** draft
**Decide:** modelo de datos (completo, para los 4 slices), máquinas de estado, integración con OP/tesorería, endpoints del Slice 1.

---

## Principios

1. **Una entidad `cheque`** con `tipo` (propio/tercero) e `instrumento` (físico/echeq). Esquema completo desde el inicio para no re-migrar entre slices (los slices habilitan código/UI, no agregan columnas críticas).
2. **Eventos de ciclo de vida auditables** (tabla `cheque_evento`, append-only) → futuro GL puede engancharse acá sin tocar el resto.
3. **Reusar tesorería existente**: imputación a `cc_proveedor_movimiento` al entregar/emitir (igual que caja/banco hoy); `banco_movimiento` al debitar/acreditar (Slice 4).
4. **El cheque es cobertura de la OP** vía tabla de enlace, sumado en `validar_balance_op`.

---

## Modelo de datos

### Tabla `chequeras` (Slice 1)
```
id                PK
banco_empresa_id  FK banco_empresa            NOT NULL
descripcion       String(120)
instrumento       String(10)  default 'fisico'  -- fisico | echeq
numero_desde      BigInteger
numero_hasta      BigInteger
proximo_numero    BigInteger                   -- sugerido, editable
activa            Boolean default True
created_at / created_by
```

### Tabla `cheques` (esquema COMPLETO, todos los slices)
```
id                PK
tipo              String(10)  NOT NULL          -- 'propio' | 'tercero'        (LD1)
instrumento       String(10)  NOT NULL default 'fisico'  -- 'fisico' | 'echeq' (LD3)
estado            String(20)  NOT NULL          -- ver máquina de estados      (LD1)
numero            String(40)  NOT NULL          -- NÚMERO REAL del cheque (siempre editable, es la fuente de verdad)
monto             Numeric(18,2) NOT NULL
moneda            String(3)   NOT NULL          -- 'ARS' | 'USD'
fecha_emision     Date        NOT NULL
fecha_pago        Date        NOT NULL          -- = emision si al día         (LD4)
es_diferido       Boolean     (generado: fecha_pago > fecha_emision)

-- Propios:
banco_empresa_id  FK banco_empresa  NULL        -- requerido si tipo='propio'
chequera_id       FK chequeras      NULL        -- requerido si propio+fisico  (LD6)

-- Terceros:
banco_nombre      String(120) NULL              -- banco librador (texto)
cuit_librador     String(13)  NULL              -- requerido si tipo='tercero'
librador_nombre   String(160) NULL

-- Pago / imputación:
proveedor_id      FK proveedores    NULL        -- beneficiario (propio) / endosatario (tercero)
orden_pago_id     FK ordenes_pago   NULL        -- OP donde se usó (denormalizado; ver tabla link)

-- Auditoría:
created_at / created_by / updated_at
motivo_anulacion  Text NULL
```

**Constraints:**
- `CheckConstraint("tipo IN ('propio','tercero')")`
- `CheckConstraint("instrumento IN ('fisico','echeq')")`
- `CheckConstraint("moneda IN ('ARS','USD')")`
- `CheckConstraint("fecha_pago >= fecha_emision")`
- Unicidad propio físico: `UNIQUE(chequera_id, numero)` (parcial, donde chequera_id NOT NULL).
- Índices: `(tipo, estado)`, `(proveedor_id)`, `(estado, fecha_pago)` (para vencimientos), `(banco_empresa_id)`.

### Tabla `orden_pago_cheque` (link, Slice 1) (LD5)
```
id              PK
orden_pago_id   FK ordenes_pago  NOT NULL
cheque_id       FK cheques       NOT NULL
monto_op_moneda Numeric(18,2)    NOT NULL   -- cobertura derivada a moneda OP (cross-moneda por TC)
created_at
UNIQUE(cheque_id)  -- un cheque cubre una sola OP activa
```
> Permite que una OP combine N cheques + caja + banco. La cobertura de la OP = Σ(montos de medios), con el cheque aportando `monto_op_moneda`.

### Tabla `cheque_evento` (append-only, auditoría + hook futuro GL)
```
id  PK · cheque_id FK · tipo String(30) · payload JSON · usuario_id · created_at
```
Tipos: `emitido`, `entregado`, `depositado`, `debitado`, `acreditado`, `rechazado`, `anulado`, `aceptado`, `en_custodia`, `imputado_cc`, `revertido_cc`.

---

## Máquinas de estado (LD1)

`TRANSICIONES_CHEQUE: dict[(tipo, estado_origen, accion), estado_destino]`

**Propios (Slice 1):**
```
(propio, —,          emitir)        -> emitido        (fecha_pago == emision)
(propio, —,          emitir)        -> diferido       (fecha_pago >  emision)
(propio, emitido,    debitar)       -> debitado       (Slice 4, no antes de fecha_pago)
(propio, diferido,   debitar)       -> debitado       (Slice 4)
(propio, emitido,    rechazar)      -> rechazado
(propio, diferido,   rechazar)      -> rechazado
(propio, {emitido,diferido}, anular)-> anulado        (revierte imputación CC)
```

**Terceros (Slice 2):**
```
(tercero, —,          recibir)   -> en_cartera
(tercero, en_cartera, entregar)  -> entregado     (endoso a proveedor, imputa CC)
(tercero, en_cartera, depositar) -> depositado    (Slice 4)
(tercero, depositado, acreditar) -> acreditado    (Slice 4, concilia banco)
(tercero, {en_cartera,entregado,depositado}, rechazar) -> rechazado
(tercero, en_cartera, anular)    -> anulado
```

**e-cheq extra (Slice 3):** `aceptado`, `rechazado_emision`, `en_custodia` sobre la misma máquina, gateados por `instrumento='echeq'`.

Validaciones transversales: `rechazado`/`anulado` terminales; no `debitar`/`acreditar` antes de `fecha_pago` (LD4); transición inválida → 422.

---

## Integración con la OP (Slice 1) — el cheque es un VALOR (se comporta como la NC)

**Decisión del usuario:** en la OP el cheque NO es una "fuente de fondos" (caja/banco). Es un **valor** que se aplica igual que una **NC**: se selecciona/emite desde un panel, **cubre parte del Total a pagar** y por lo tanto **reduce el efectivo (caja/banco) necesario**. Aparece en el "Resumen de pago" como una línea que descuenta, junto a NC y dinero a cuenta.

1. **Panel de valores:** el modal de OP tiene un panel de cheques (espejo del `PanelNCsProveedor`): para **propios** = emitir un cheque nuevo; para **terceros** (Slice 2) = elegir uno de la cartera. Se pueden aplicar uno o más.
2. **Cobertura (como NC/DAC):** el monto del cheque (derivado a moneda OP por TC) es un componente de cobertura que **descuenta del monto a pagar**, igual que `sumaNCsOP`/`sumaDAC` hoy. La caja/banco cubre el resto. `validar_balance_op` incluye `Σ orden_pago_cheque.monto_op_moneda` en la cobertura, con tolerancia `< 0.005`.
   - Cobertura total = items(pedidos) cubiertos por: **valores** (NC + dinero a cuenta + **cheques**) + efectivo (caja/banco) + excedente. La diferencia debe dar 0 al confirmar.
3. **Imputación — AMBOS casos (decisión del usuario):** el cheque en el payload lleva un `pedido_id` opcional (a qué pedido de la OP se aplica), igual que la NC lleva `nc.pedido_id`:
   - **Con `pedido_id`** (cubre un pedido específico): el cheque **imputa al pedido** (crea una `Imputacion` origen=cheque/orden_pago → destino=pedido), bajando el saldo del pedido — exactamente como `imputar_nc_a_pedido`. El ítem del pedido va NETO del cheque (igual que va neto de NC), así `item_neto + cheque = obligación del pedido` y el saldo llega a cero. La CC del proveedor se actualiza vía esa imputación (no se crea un haber directo aparte → evita doble conteo).
   - **Sin `pedido_id`** ("a cuenta"): el cheque inserta un haber directo en `cc_proveedor_movimiento` (baja solo el saldo global del proveedor). Es el caso ya implementado.
   En ambos: evento `imputado_cc`, se crea `orden_pago_cheque` con `monto_op_moneda`.
   > ⚠️ Cuidado over-imputación (mismo trap que NC): el ítem del pedido DEBE ir neto del cheque y el cheque imputa el resto. NO imputar el cheque al pedido Y además tener el ítem en bruto (doble conteo). Reusar/espejar exactamente el camino de `imputar_nc_a_pedido`.
4. **Anulación:** `anular` un cheque de una OP pendiente revierte el movimiento CC (append-only reversal) y quita la cobertura (vuelve a faltar ese monto).

> El derive-at-edge por TC y la tolerancia de medio centavo ya existen (PRs #781/#782) — se reutilizan. El panel de cheques reusa el patrón de `PanelNCsProveedor` y el resumen reusa las líneas de descuento de NC/DAC.

---

## Endpoints Slice 1 (prefijo `/administracion/tesoreria` o `/administracion/cheques`)

Todos con `require_permiso("tesoreria.gestionar_cheques")`.

```
POST   /chequeras                         crear chequera
GET    /chequeras?banco_empresa_id=       listar
GET    /cheques?tipo=&estado=&banco=&moneda=&desde=&hasta=   listar (página de cheques)
POST   /cheques/propio                    emitir cheque propio (standalone o vía OP)
POST   /cheques/{id}/anular               anular (motivo)  -> revierte CC si corresponde
GET    /cheques/{id}                       detalle + eventos
```

Integración OP: extender el payload de `crear_y_pagar` / `ejecutar_pago` con `cheques: [{banco_empresa_id, chequera_id, numero, monto, moneda, fecha_emision, fecha_pago}]`. El servicio emite + linkea + imputa dentro de la misma transacción.

---

## Frontend (Slice 1) — base para Stitch

- **Modal "Cargar/Emitir cheque"** (`ModalCheque`): tipo (Slice 1 = propio), banco_empresa, chequera (autocompleta próximo número), número, monto, moneda, fecha emisión, fecha pago (diferido si > emisión), beneficiario. Validación de fechas y monto.
- **Página "Cheques"** (`TabCheques` / `PaginaCheques`): tabla con filtros (estado, tipo, banco, moneda, rango fechas), badge de estado (reusar patrón `EstadoBadge`), acciones por estado (anular; debitar en Slice 4). Vista de cartera (terceros) en Slice 2.
- **Integración OP**: en el modal de OP, agregar "Cheque" como fuente de fondos (junto a caja/banco), que abre `ModalCheque` en modo emisión y suma el cheque a la cobertura.
- Tesla Design System + CSS Modules + tokens (convención del proyecto).

---

## Migración (Alembic)

`YYYYMMDD_cheques_modulo.py`: crea `chequeras`, `cheques`, `orden_pago_cheque`, `cheque_evento` + el permiso `tesoreria.gestionar_cheques` (seed sin asignar). Índices y constraints arriba. Sin tocar tablas existentes salvo FKs nuevas (no destructivo).

---

## Estrategia de tests (TDD estricto — backend)

- `validar_balance_op` con cheque (cobertura, falta cubrir, cross-moneda, tolerancia).
- Máquina de estados: emitir→emitido/diferido, anular→revierte CC, transición inválida→422.
- Chequera: próximo número avanza al emitir; unicidad numero/chequera.
- Permiso: sin `tesoreria.gestionar_cheques` → 403.
- Imputación CC al emitir; reversal al anular.

---

## Cómo NO impedir el GL futuro (LD7)

`cheque_evento` registra cada hecho económico (emitido, entregado, debitado, acreditado, imputado_cc, revertido_cc) con monto, moneda, fecha y contraparte. Un módulo de contabilidad futuro consume esos eventos para generar asientos — sin tocar el módulo de cheques.

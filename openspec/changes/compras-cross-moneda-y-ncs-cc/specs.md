# Specs: Compras Cross-Moneda + NCs Visibles en CC

Delta specs para el change `compras-cross-moneda-y-ncs-cc`. Cubre dominios `compras/imputaciones`, `compras/ordenes-pago`, `compras/pedidos`, `compras/ncs` y `compras/cc-proveedor`.

Convenciones:
- RFC 2119: MUST, MUST NOT, SHALL, SHOULD, MAY
- Cada requirement tiene ID estable: `FR-NNN` (functional) o `NFR-NNN` (non-functional)
- Cada requirement tiene al menos un Scenario testeable (Given/When/Then)
- Los Scenarios describen comportamiento observable, no implementación

---

## MODIFIED Requirements

### Requirement: FR-001 — Validación de moneda en imputaciones permite cross-moneda con TC

The system MUST permit cross-moneda imputaciones (origen.moneda ≠ destino.moneda) when a strictly positive `tipo_cambio` is provided. The system MUST continue to reject cross-moneda imputaciones when `tipo_cambio` is missing or not strictly positive.

(Previously: cross-moneda was rejected unconditionally by `_validar_moneda_consistente` and by `_validar_items_misma_moneda_que_op` in PR #624.)

#### Scenario: Cross-moneda con TC válido es aceptada

- GIVEN una OP en moneda ARS y un pedido item en moneda USD
- AND la OP trae `tipo_cambio = 1500`
- WHEN se valida la imputación cross-moneda
- THEN la validación pasa sin error
- AND la imputación queda registrada con `moneda_imputada=USD` y `tipo_cambio=1500`

#### Scenario: Cross-moneda sin TC se rechaza con HTTP 400

- GIVEN una OP en moneda ARS y un pedido item en moneda USD
- AND la OP NO trae `tipo_cambio` (None o 0)
- WHEN se intenta validar la imputación cross-moneda
- THEN el sistema responde HTTP 400
- AND el mensaje de error indica que TC es obligatorio para cross-moneda

#### Scenario: Same-moneda mantiene comportamiento previo

- GIVEN una OP en moneda USD y un pedido item en moneda USD
- WHEN se valida la imputación
- THEN la validación pasa sin requerir `tipo_cambio`
- AND el comportamiento de pedidos pre-existentes same-moneda no cambia

---

### Requirement: FR-002 — `moneda_imputada` registra la moneda destino, no la origen

The system MUST store `moneda_imputada` equal to the destination (pedido) currency in every imputación, regardless of the OP currency. The system MUST store `monto_imputado` expressed in destination currency. The system MUST persist the `tipo_cambio` used whenever origen.moneda ≠ destino.moneda.

(Previously: `moneda_imputada` always equaled `op.moneda`. Same-moneda flows produced identical results; cross-moneda flows were not allowed.)

#### Scenario: OP ARS pagando pedido USD graba imp en USD

- GIVEN una OP ARS con un item para un pedido USD por monto ARS = 1.000.000
- AND TC de la OP = 1500
- WHEN se ejecuta el pago
- THEN se crea una imputación con `moneda_imputada=USD`, `monto_imputado=666.67`, `tipo_cambio=1500`
- AND NO se crea una imputación con `moneda_imputada=ARS`

#### Scenario: OP USD pagando pedido USD graba imp en USD (sin TC)

- GIVEN una OP USD con un item para un pedido USD por monto USD = 500
- WHEN se ejecuta el pago
- THEN se crea una imputación con `moneda_imputada=USD`, `monto_imputado=500`, `tipo_cambio=null`

---

### Requirement: FR-003 — `ordenes_pago_service.ejecutar_pago` convierte montos cross-moneda

The system MUST, for each item processed by `ejecutar_pago`, when `pedido.moneda ≠ op.moneda`:
- Require the item's effective `tipo_cambio` (sourced from the OP) to be strictly positive
- Compute `monto_imputado_destino = item.monto / op.tipo_cambio`, rounded to 2 decimal places (banker's or HALF_UP per project rounding policy)
- Persist the imputación with `moneda_imputada = pedido.moneda`, `monto_imputado = monto_imputado_destino`, `tipo_cambio = op.tipo_cambio`

When `pedido.moneda = op.moneda`, the system MUST persist the imputación with `monto_imputado = item.monto` and `tipo_cambio = null`.

#### Scenario: Ejecutar OP ARS con item USD convierte el monto

- GIVEN una OP ARS con `tipo_cambio=1500`
- AND un item del pedido USD con `monto=1.500.000` (ARS)
- WHEN se llama `ejecutar_pago`
- THEN se persiste una imputación con `moneda_imputada=USD`, `monto_imputado=1000.00`, `tipo_cambio=1500`

#### Scenario: Ejecutar OP cross-moneda sin TC falla

- GIVEN una OP ARS sin `tipo_cambio`
- AND un item del pedido USD
- WHEN se llama `ejecutar_pago`
- THEN el sistema responde HTTP 400
- AND ninguna imputación se persiste
- AND el caja_movimiento de la OP no se ejecuta (transacción se aborta)

---

### Requirement: FR-004 — Crear/Editar OP permite items cross-moneda si la OP trae TC

The system MUST allow `POST /ordenes-pago` and `PUT /ordenes-pago/{id}` to accept items whose `pedido.moneda ≠ op.moneda` when the OP carries a strictly positive `tipo_cambio`. The system MUST reject such requests with HTTP 400 when `tipo_cambio` is missing or not strictly positive.

(Previously: `_validar_items_misma_moneda_que_op` rejected all cross-moneda items regardless of TC.)

#### Scenario: Crear OP ARS con items USD y TC válido

- GIVEN un payload `POST /ordenes-pago` con `op.moneda=ARS`, `tipo_cambio=1500`, e items de pedidos USD
- WHEN se procesa la creación
- THEN la OP se crea exitosamente
- AND queda en estado `pendiente`

#### Scenario: Editar OP a moneda distinta sin TC falla

- GIVEN una OP existente USD con items USD
- WHEN se envía `PUT /ordenes-pago/{id}` cambiando `moneda=ARS` sin `tipo_cambio`
- THEN el sistema responde HTTP 400
- AND la OP NO se modifica

---

## ADDED Requirements

### Requirement: FR-005 — Cálculo de TC ponderado por pedido (server-side, derivado)

The system MUST expose `pedidos_service.calcular_tc_ponderado_pedido(pedido_id)` that computes the weighted average TC for a pedido as:

```
tc_ponderado = sum(monto_origen_en_ars across all imps cross-moneda del pedido)
             / sum(monto_imputado_en_destino across those same imps)
```

The function MUST return `Decimal` when at least one cross-moneda imputación exists on the pedido, and `None` otherwise. The value MUST NOT be persisted (computed at read time). The system MUST also expose a batch variant `calcular_tc_ponderado_pedido_batch(pedido_ids)` that returns a `dict[pedido_id, Optional[Decimal]]` using a single aggregated query (no N+1).

#### Scenario: TC ponderado promedia dos imps con TCs distintos

- GIVEN un pedido USD con dos imputaciones cross-moneda:
  - Imp A: `monto_origen_ars=1.000.000`, `monto_imputado=666.67 USD`, `tipo_cambio=1500`
  - Imp B: `monto_origen_ars=500.000`, `monto_imputado=250 USD`, `tipo_cambio=2000`
- WHEN se llama `calcular_tc_ponderado_pedido(pedido_id)`
- THEN devuelve `Decimal("1636.36")` aproximadamente (1.500.000 / 916.67)

#### Scenario: TC ponderado de pedido same-moneda devuelve None

- GIVEN un pedido USD con sólo imputaciones same-moneda (sin TC)
- WHEN se llama `calcular_tc_ponderado_pedido(pedido_id)`
- THEN devuelve `None`

#### Scenario: TC ponderado batch evita N+1

- GIVEN una lista de 50 `pedido_ids`
- WHEN se llama `calcular_tc_ponderado_pedido_batch(pedido_ids)`
- THEN se ejecuta exactamente 1 query agregada (no 50)
- AND devuelve un `dict` con 50 entries

---

### Requirement: FR-006 — `PedidoCompraResponse` expone `tipo_cambio_ponderado`

The system MUST add a new optional field `tipo_cambio_ponderado: Optional[Decimal]` to the `PedidoCompraResponse` schema. The router MUST populate this field using the batch helper for listados and the single helper for detalle.

#### Scenario: GET pedido USD con imps cross-moneda devuelve TC ponderado

- GIVEN un pedido USD con imputaciones cross-moneda
- WHEN se llama `GET /pedidos-compra/{id}`
- THEN el response incluye `tipo_cambio_ponderado` con valor `Decimal`

#### Scenario: GET pedido same-moneda devuelve TC ponderado null

- GIVEN un pedido USD sin imputaciones cross-moneda
- WHEN se llama `GET /pedidos-compra/{id}`
- THEN el response incluye `tipo_cambio_ponderado = null`

#### Scenario: Listado de pedidos no genera N+1

- GIVEN un listado de 100 pedidos
- WHEN se llama el endpoint de listado
- THEN el TC ponderado de cada pedido se calcula vía batch helper (1 query agregada)

---

### Requirement: FR-007 — Endpoint `GET /administracion/compras/ncs-locales/disponibles` filtra por proveedor y saldo

The system MUST expose `GET /administracion/compras/ncs-locales/disponibles?proveedor_id=X` that returns NCs locales matching ALL of:
- `proveedor_id = X`
- `estado IN ('aprobado', 'aplicada_parcial')`
- `saldo_pendiente > 0`

The endpoint MUST support pagination via `limit` and `offset` query params, with a default `limit=100` and a maximum `limit` enforced by the project's pagination policy.

#### Scenario: NCs aprobadas con saldo se incluyen

- GIVEN un proveedor X con 3 NCs: estado=`aprobado` saldo=500, estado=`aplicada_parcial` saldo=200, estado=`aprobado` saldo=0
- WHEN se llama `GET /ncs-locales/disponibles?proveedor_id=X`
- THEN el response incluye las 2 NCs con saldo > 0 (no la de saldo=0)
- AND ambos estados (`aprobado` y `aplicada_parcial`) se incluyen

#### Scenario: NC aplicada totalmente se excluye

- GIVEN un proveedor X con una NC `aplicada` (saldo=0)
- WHEN se llama `GET /ncs-locales/disponibles?proveedor_id=X`
- THEN la NC `aplicada` NO se incluye en el response

#### Scenario: Falta proveedor_id devuelve HTTP 422

- WHEN se llama `GET /ncs-locales/disponibles` sin `proveedor_id`
- THEN el sistema responde HTTP 422 (validación)

#### Scenario: Paginación por defecto y override

- GIVEN un proveedor con 250 NCs disponibles
- WHEN se llama `GET /ncs-locales/disponibles?proveedor_id=X` sin `limit`
- THEN se devuelven 100 NCs
- WHEN se llama con `limit=50&offset=100`
- THEN se devuelven NCs 101–150

---

### Requirement: FR-008 — Endpoint `/cc-proveedor/{id}/por-pedido` enriquecido con TC ponderado y NCs disponibles

The system MUST extend `GET /administracion/compras/cc-proveedor/{proveedor_id}/por-pedido` to include:
- Per pedido: `tc_ponderado: Optional[Decimal]`
- At root level (or proveedor-level): `ncs_disponibles: list` containing a lightweight summary (`id`, `numero`, `fecha`, `importe`, `saldo_pendiente`) of NCs returned by FR-007 filter.

Both fields MUST be additive and backward compatible (existing consumers ignoring unknown fields continue to work).

#### Scenario: Por-pedido response incluye TC ponderado y NCs

- GIVEN un proveedor X con pedidos USD que tienen imps cross-moneda y 2 NCs disponibles
- WHEN se llama `GET /cc-proveedor/X/por-pedido`
- THEN cada pedido USD con imps cross-moneda trae `tc_ponderado` con valor Decimal
- AND el response trae `ncs_disponibles` con 2 entradas resumidas

#### Scenario: Proveedor sin NCs disponibles

- GIVEN un proveedor X sin NCs disponibles
- WHEN se llama `GET /cc-proveedor/X/por-pedido`
- THEN `ncs_disponibles` es una lista vacía (no null)

---

### Requirement: FR-009 — Frontend `ModalOrdenPagoNueva` habilita cross-moneda con campo TC

The frontend MUST, in `ModalOrdenPagoNueva.jsx`:
- NOT block (no destructive confirm) when the user changes the OP currency to one distinct from the currently loaded items.
- Show a numeric input labeled "TC OP→Items" (or equivalent) whenever `OP.moneda ≠ items[].moneda` (at least one item differs).
- Validate before submit that the TC value is strictly greater than 0 when cross-moneda is detected.
- Submit `tipo_cambio` as part of the OP payload.

#### Scenario: User cambia moneda OP y aparece campo TC

- GIVEN el modal abierto con items pre-cargados de pedidos USD
- WHEN el user cambia la moneda de la OP a ARS
- THEN aparece el campo "TC OP→Items" (visible)
- AND el campo previo de confirm destructivo de moneda NO se dispara

#### Scenario: Submit sin TC válido es bloqueado

- GIVEN el modal con OP.moneda=ARS, items USD, y el campo TC vacío
- WHEN el user presiona "Crear OP"
- THEN el submit se aborta
- AND se muestra un mensaje "TC debe ser > 0"

#### Scenario: Submit con TC válido envía el payload

- GIVEN el modal con OP.moneda=ARS, items USD, TC=1500
- WHEN el user presiona "Crear OP"
- THEN se hace `POST /ordenes-pago` con `tipo_cambio: 1500`
- AND el modal se cierra al recibir 201

---

### Requirement: FR-010 — Frontend `TabCCProveedores` muestra NCs disponibles y acciones por pedido

The frontend MUST, in `TabCCProveedores.jsx`:
- Render a "NCs disponibles" section in the hero area showing a mini-table with columns `número`, `fecha`, `importe`, `saldo`.
- Render, on each `GrupoPedidoCard` (vista por-pedido), two action buttons next to the existing "Desimputar" button:
  - **"Aplicar NC"** → opens `ModalAplicarNC` with `pedidoDestinoId` pre-loaded.
  - **"Imputar pago"** → opens `ModalOrdenPagoNueva` with the pedido pre-loaded and the proveedor pre-loaded.
- Render the `tc_ponderado` value below the header of any pedido USD with cross-moneda imps.

#### Scenario: Hero muestra NCs disponibles del proveedor

- GIVEN un proveedor seleccionado con 2 NCs disponibles
- WHEN se navega al tab CC del proveedor
- THEN el hero muestra una sección "NCs disponibles"
- AND la tabla mini lista las 2 NCs con número, fecha, importe, saldo

#### Scenario: Click en "Aplicar NC" preselecciona pedido

- GIVEN un pedido en la lista con botón "Aplicar NC" visible
- WHEN el user hace click en "Aplicar NC"
- THEN se abre `ModalAplicarNC`
- AND el destino está pre-cargado con el `pedido_id` del card

#### Scenario: Click en "Imputar pago" preselecciona pedido y proveedor

- GIVEN un pedido en la lista con botón "Imputar pago" visible
- WHEN el user hace click en "Imputar pago"
- THEN se abre `ModalOrdenPagoNueva`
- AND el modal arranca con el pedido pre-cargado como item
- AND el proveedor del CC ya está seleccionado

#### Scenario: TC ponderado se renderiza debajo del header

- GIVEN un pedido USD con `tc_ponderado=1636.36`
- WHEN se renderiza el card del pedido
- THEN se muestra "TC ponderado: 1636.36" (o formato equivalente) debajo del header
- AND para pedidos sin `tc_ponderado` (null) no se renderiza esa línea

---

### Requirement: FR-011 — `ModalAplicarNC` acepta `pedidoDestinoId` para pre-cargar destino

The frontend MUST extend `ModalAplicarNC.jsx` to accept a new prop `pedidoDestinoId: number | string | null`. When provided, the modal MUST pre-select that pedido as the destino on mount and SHOULD disable the destino selector (or display the pedido as read-only) to prevent accidental change.

#### Scenario: Modal recibe pedidoDestinoId y pre-carga

- GIVEN el modal montado con prop `pedidoDestinoId=42`
- WHEN el modal termina de cargar
- THEN el destino aparece pre-cargado con el pedido 42
- AND el user puede continuar el flujo de aplicar NC sin elegir destino

#### Scenario: Modal sin prop opera como antes

- GIVEN el modal montado sin la prop `pedidoDestinoId` (o `null`)
- WHEN el modal termina de cargar
- THEN el destino arranca vacío y el user debe seleccionarlo manualmente

---

## Append-only & Backward Compatibility Requirements

### Requirement: FR-012 — Append-only en `imputaciones`, `cc_proveedor_movimientos`, `compras_eventos`

The system MUST NOT issue `UPDATE` statements that mutate existing rows in `imputaciones`, `cc_proveedor_movimientos`, or `compras_eventos`. All corrections MUST be expressed as a reversal (new row with opposite sign) followed by a new imputación.

#### Scenario: Corrección de imp se hace con reversal + nueva imp

- GIVEN una imp cross-moneda con monto_imputado erróneo
- WHEN el user pide corregirla
- THEN el sistema crea una imp reversal (mismo monto, signo opuesto) y una nueva imp con el valor correcto
- AND la imp original NO se modifica (queda inmutable en BD)

---

### Requirement: FR-013 — Backward compatibility para pedidos pre-existentes same-moneda

The system MUST NOT change the behavior of pedidos created before this change for same-moneda flows. Existing imps with `moneda_imputada = op.moneda` (where op.moneda = pedido.moneda) MUST continue to project to CC and balances as before.

#### Scenario: Pedido pre-existente USD con OP USD no cambia

- GIVEN un pedido USD con imps creadas antes del change (moneda_imputada=USD, tipo_cambio=null)
- WHEN se consulta el CC del proveedor
- THEN el HABER USD y los saldos pendientes se calculan igual que antes
- AND no aparecen efectos colaterales

---

## Non-Functional Requirements

### Requirement: NFR-001 — TC ponderado batch SHALL evitar N+1

The system MUST compute `tc_ponderado` for a list of pedido_ids using exactly ONE aggregated SQL query (e.g., `GROUP BY pedido_id`). Per-pedido looping with separate queries is prohibited in listados.

#### Scenario: 100 pedidos en listado, 1 sola query agregada

- GIVEN un listado solicitando 100 pedidos
- WHEN el router invoca la batch helper
- THEN se ejecuta exactamente 1 query agregada para calcular TCs ponderados
- AND el contador de queries del request (medible vía middleware/log) lo confirma

---

### Requirement: NFR-002 — Endpoint NCs disponibles SHALL ser paginado

The endpoint `GET /ncs-locales/disponibles` MUST support `limit` (default 100, max enforced by project policy) and `offset` (default 0) query params. The endpoint SHALL return results in deterministic order (e.g., `ORDER BY fecha DESC, id DESC`) so pagination is consistent across calls.

#### Scenario: Orden estable entre páginas

- GIVEN 250 NCs disponibles
- WHEN se piden páginas (limit=100, offset=0), (limit=100, offset=100), (limit=100, offset=200)
- THEN las 3 páginas NO repiten NCs
- AND la unión de las 3 páginas cubre las 250 NCs

#### Scenario: Limit por defecto

- WHEN se llama el endpoint sin `limit`
- THEN devuelve a lo sumo 100 NCs

---

### Requirement: NFR-003 — Append-only SHALL ser sagrado en imputaciones

No SQL `UPDATE` MAY mutate rows in `imputaciones`, `cc_proveedor_movimientos`, or `compras_eventos`. Code reviews MUST verify this; automated checks SHOULD detect violations (lint/grep rules SHOULD flag `db.execute(update(Imputacion))` patterns in the service layer).

#### Scenario: Code review rechaza UPDATE en imputaciones

- GIVEN un PR que introduce `db.execute(update(Imputacion)...)` en `imputaciones_service.py`
- WHEN se revisa
- THEN el reviewer lo bloquea referenciando NFR-003
- AND (idealmente) un check automatizado lo detecta

---

### Requirement: NFR-004 — Backward compatibility con consumers existentes

All new response fields (`tipo_cambio_ponderado`, `tc_ponderado` per pedido, `ncs_disponibles`) MUST be additive — optional, default `null` or empty list. The endpoint contracts MUST NOT break clients that ignore unknown fields.

#### Scenario: Cliente legacy ignora campos nuevos

- GIVEN un cliente que consume `GET /pedidos-compra/{id}` sin conocer `tipo_cambio_ponderado`
- WHEN se llama el endpoint después del change
- THEN el cliente sigue funcionando sin error
- AND el campo nuevo es opcional/null para pedidos same-moneda

---

### Requirement: NFR-005 — Cobertura de tests para cross-moneda

The change MUST be covered by the following unit tests (renames + additions):

| Test | Acción | Cobertura |
|------|--------|-----------|
| `test_imputaciones_service.py::test_cross_moneda_sin_tc_raise_400` | Renombrar de `test_cross_moneda_raise_400` | FR-001 (rechazo sin TC) |
| `test_imputaciones_service.py::test_cross_moneda_con_tc_ok` | Nuevo | FR-001 (acepta con TC), FR-002 (moneda_imputada=destino) |
| `test_ordenes_pago_service.py::test_op_cross_moneda_ejecuta_pago_genera_imp_usd` | Nuevo | FR-003 (conversión y persistencia) |
| `test_pedidos_service.py::test_tc_ponderado_calcula_promedio_correcto` | Nuevo | FR-005 (cálculo correcto con 2 imps) |
| `test_administracion_compras_router.py::test_endpoint_ncs_disponibles_filtra_por_proveedor_y_saldo` | Nuevo | FR-007 (filtros + edge saldo=0) |

#### Scenario: Suite de tests pasa sin regresiones

- GIVEN la rama del change con la implementación completa
- WHEN se corre `pytest backend/tests/unit/`
- THEN los 5 tests listados pasan en verde
- AND los tests pre-existentes de cross-moneda caja↔OP (PR #624) siguen pasando

---

## Coverage Summary

| Área | Functional | Non-Functional | Total Requirements |
|------|-----------|----------------|--------------------|
| Imputaciones | FR-001, FR-002 | NFR-003 | 3 |
| Órdenes de pago | FR-003, FR-004 | — | 2 |
| Pedidos | FR-005, FR-006 | NFR-001 | 3 |
| NCs / CC backend | FR-007, FR-008 | NFR-002 | 3 |
| Frontend | FR-009, FR-010, FR-011 | — | 3 |
| Backward compat & append-only | FR-012, FR-013 | NFR-004 | 3 |
| Tests | — | NFR-005 | 1 |
| **TOTAL** | **11 FR** | **5 NFR** | **16** |

Happy paths, edge cases (sin TC, saldo=0, same-moneda backward compat) y error states (HTTP 400/422) están cubiertos. Performance (N+1) y append-only están explicitados en NFRs.

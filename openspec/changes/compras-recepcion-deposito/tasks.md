# Tasks — Recepción de Mercadería por Depósito

**Change:** `compras-recepcion-deposito`
**Fase:** tasks
**Status:** draft
**Persistence mode:** hybrid
**Fecha:** 2026-06-18

---

## 0. Leyenda y convenciones

- **IDs:** `RD-A.<NUM>` (Slice A backend) / `RD-B.<NUM>` (Slice B frontend).
- **Size:** S (<2h), M (2-6h), L (6-12h), XL (12-24h).
- **Depends on:** lista de IDs o `ninguno`.
- **Parallelizable with:** IDs dentro del mismo slice que pueden correr en paralelo, o `no`.
- **[TEST]:** tarea test-first (escribir el test antes de la implementación).
- **[GATE]:** tarea bloqueante; el slice siguiente no arranca hasta que esté ✅.
- **Artifacts:** archivos a crear/modificar — `NEW` / `MODIFIED`.
- **Spec refs:** REQ correspondiente en `specs/recepcion-deposito.md`.
- **Design refs:** sección en `design.md`.

**Conventions:**
- Migraciones Alembic: `YYYYMMDD_<descripcion>.py`, `down_revision` = `20260618_add_oc_link_to_pedidos_compra`.
- Tests de integración: `backend/tests/integration/test_recepcion_deposito_endpoints.py`.
- Todo endpoint nuevo: `require_permiso("deposito.recibir_mercaderia")`.
- ERP tables (`tb_*`, `productos_erp`): estrictamente read-only.
- CSS Modules + Tesla tokens; sin Tailwind en componentes nuevos.

---

## Resumen ejecutivo

| Slice | Tasks | Size total estimado | PR target |
|-------|-------|---------------------|-----------|
| A — Backend | 14 | ~400 líneas, budget ALTO | PR #1 → main |
| B — Frontend | 9 | ~400 líneas, budget ALTO | PR #2 → main (stacked) |
| **TOTAL** | **23** | | |

**Critical path:** A.1 → A.2 → A.3 → A.4 → A.5/A.6 (paralelo) → A.7 → A.8/A.9/A.10 (paralelo) → A.11 → A.12/A.13 → A.14 [GATE] → B.1 [GATE stitch] → B.2/B.3/B.4 (paralelo) → B.5/B.6 (paralelo) → B.7 → B.8/B.9.

**Chained PRs:** Sí. Slice A y Slice B van en PRs separados, stacked-to-main.
**Decisión antes de apply:** confimar `alembic heads` y columna real de `productos_erp` (ver RD-A.1).

---

## Slice A — Backend

### RD-A.1: Pre-flight — confirmar heads y schema ERP [GATE]

**Size:** S
**Depends on:** ninguno
**Parallelizable with:** no (bloquea todo)
**Status:** [x]

**Work:**
1. Ejecutar `cd backend && alembic heads` y confirmar que `20260618_add_oc_link_to_pedidos_compra` sigue siendo head único (o listar si hay múltiples).
2. Confirmar `productos_erp` columnas reales: `item_id` (PK/join key), nombre del ítem (hipótesis: `nombre` ó `descripcion`). Ejecutar `\d productos_erp` o inspeccionar el modelo.
3. Registrar ambos valores en `openspec/changes/compras-recepcion-deposito/state.yaml`.

**Artifacts:**
- `openspec/changes/compras-recepcion-deposito/state.yaml` (MODIFIED — keys `preflight.alembic_head`, `preflight.productos_erp_item_col`, `preflight.productos_erp_nombre_col`)

**Acceptance criteria:**
- [ ] `alembic_head` registrado (o lista de heads si hay divergencia)
- [ ] `productos_erp` join key y nombre-col confirmados
- [ ] Nada de código escrito en esta tarea

**Spec refs:** spec D-PERROERP / D-MIGSPLIT, design §14.

---

### RD-A.2: Migración Alembic — tabla + estados + permiso seed [TEST]

**Size:** M
**Depends on:** RD-A.1
**Parallelizable with:** no (los modelos dependen de la tabla)
**Status:** [x]

**Work (una sola migración, down_revision = head de RD-A.1):**
1. `CREATE TABLE pedido_compra_ingresos` (DDL completo, design §2): columnas, CHECK `ck_pci_cantidad_positiva (cantidad_recibida > 0)`, FK `pedidos_compra ON DELETE RESTRICT`, FK `usuarios ON DELETE RESTRICT`, índices `ix_pci_pedido`, `ix_pci_pod WHERE pod_id IS NOT NULL`, `ix_pci_oc_linea`.
2. `DROP CONSTRAINT ck_pedidos_compra_estado` + `ADD CONSTRAINT` con los 9 estados (design §3): `borrador, pendiente_aprobacion, aprobado, rechazado, cancelado, pagado_parcial, pagado, recibido, con_faltantes`.
3. Seed permiso `deposito.recibir_mercaderia` (INSERT ON CONFLICT DO NOTHING) + asignación SOLO a SUPERADMIN vía `roles_permisos_base` (design §4).
4. `downgrade()`: drop table, drop+add constraint sin los 2 estados nuevos, delete permiso + mapping.

**[TEST] Escrbir primero:**
- `test_migration_creates_pedido_compra_ingresos_table` — verifica existencia de tabla + columnas + índices
- `test_migration_check_cantidad_recibida_gt_zero` — INSERT con `cantidad_recibida=0` rechazado por DB
- `test_migration_new_states_accepted` — INSERT `estado='recibido'` y `estado='con_faltantes'` OK
- `test_migration_invalid_state_rejected` — INSERT `estado='en_camino'` rechazado
- `test_migration_permiso_seed` — `SELECT codigo FROM permisos WHERE codigo='deposito.recibir_mercaderia'` retorna 1 row
- `test_migration_permiso_only_superadmin` — mapping solo para SUPERADMIN, no ADMIN ni GERENTE

**Artifacts:**
- `backend/alembic/versions/YYYYMMDD_recepcion_deposito.py` (NEW)
- `backend/tests/integration/test_recepcion_deposito_endpoints.py` (NEW — solo tests de migración en esta tarea)

**Acceptance criteria:**
- [ ] `alembic upgrade head` sin errores
- [ ] `alembic downgrade -1` + `alembic upgrade head` sin errores
- [ ] Tests de migración verdes

**Spec refs:** REQ-RD-001, REQ-RD-002, REQ-RD-003.
**Design refs:** §2, §3, §4.

---

### RD-A.3: Modelo SQLAlchemy `PedidoCompraIngreso` + actualizar CheckConstraint en `PedidoCompra`

**Size:** S
**Depends on:** RD-A.2
**Parallelizable with:** no
**Status:** [x]

**Work:**
1. Crear `backend/app/models/pedido_compra_ingresos.py`: clase `PedidoCompraIngreso` con columnas tipadas explícitas, `__tablename__ = 'pedido_compra_ingresos'`, `CheckConstraint('cantidad_recibida > 0', name='ck_pci_cantidad_positiva')`, relationships `pedido` y `usuario` (read-only, lazy='select').
2. Actualizar `backend/app/models/pedido_compra.py` L144-148: agregar `'recibido'` y `'con_faltantes'` al literal del `CheckConstraint` de `estado` para que modelo y DB estén en sync.
3. Importar el modelo en `backend/app/models/__init__.py` para que Alembic lo detecte.

**Artifacts:**
- `backend/app/models/pedido_compra_ingresos.py` (NEW)
- `backend/app/models/pedido_compra.py` (MODIFIED — CheckConstraint literal)
- `backend/app/models/__init__.py` (MODIFIED)

**Acceptance criteria:**
- [ ] `from app.models.pedido_compra_ingresos import PedidoCompraIngreso` sin errores
- [ ] `PedidoCompraIngreso.__table__.columns` coincide con DDL de la migración
- [ ] CheckConstraint de `PedidoCompra.estado` incluye `'recibido'` y `'con_faltantes'`

**Spec refs:** REQ-RD-001, REQ-RD-002.
**Design refs:** §2.

---

### RD-A.4: Schemas Pydantic para recepción

**Size:** S
**Depends on:** RD-A.3
**Parallelizable with:** no (servicios y endpoints los necesitan)
**Status:** [x]

**Work:**
Agregar en `backend/app/schemas/oc_ingreso.py` (o crear `recepcion.py` si se prefiere separar):
- `SaldoLineaResponse` — por línea OC: `pod_id, item_id, item_nombre, stor_id, deposito_nombre, pod_qty, cantidad_recibida_total, saldo_pendiente`
- `SaldosResponse` — root: `pedido_id, tiene_oc, estado, requiere_envio, lineas: list[SaldoLineaResponse]`
- `IngresoLinea` — input: `pod_id, cantidad_recibida`
- `RegistrarIngresosRequest` — `lineas: list[IngresoLinea], observaciones: str | None`
- `IngresoCreadoResponse` — `id, pod_id, cantidad_recibida`
- `SaldoPostIngreso` — `pod_id, saldo_pendiente`
- `RegistrarIngresosResponse` — `pedido_id, estado_nuevo, ingresos_creados, saldos`
- `ConfirmarPedidoRequest` — `completo: bool, observaciones: str | None` + validator: si `completo=False` y `observaciones` es None → `ValueError`
- `ConfirmarPedidoResponse` — `pedido_id, estado_nuevo`
- `EventoRecepcionItem` — `id, tipo, created_at, usuario_nombre, payload`
- `EventosRecepcionResponse` — `pedido_id, eventos: list[EventoRecepcionItem]`

Todos con `model_config = ConfigDict(from_attributes=True)`.

**Artifacts:**
- `backend/app/schemas/oc_ingreso.py` (MODIFIED) o `backend/app/schemas/recepcion.py` (NEW)

**Acceptance criteria:**
- [ ] `from app.schemas.oc_ingreso import SaldosResponse, RegistrarIngresosRequest` (o `recepcion`) sin errores
- [ ] `ConfirmarPedidoRequest(completo=False)` levanta `ValidationError` (observaciones ausente)
- [ ] Pydantic v2 syntax en todos los schemas (ConfigDict, no `class Config`)

**Spec refs:** REQ-RD-004, REQ-RD-005, REQ-RD-006, REQ-RD-009.

---

### RD-A.5: Extender `oc_ingresos_service` — JOIN `productos_erp` + `item_nombre`

**Size:** S
**Depends on:** RD-A.3
**Parallelizable with:** RD-A.6
**Status:** [x]

**Work:**
1. En `backend/app/services/oc_ingresos_service.py`, extender `get_orden_compra_detalle` agregando `LEFT JOIN productos_erp p ON p.{item_col} = d.item_id` (usar col confirmada en RD-A.1).
2. Agregar `item_nombre` al resultado (columna `p.{nombre_col}`, NULL si fantasma → retornar `None`; el servicio de saldos convierte a string `str(item_id)`).
3. Actualizar `OrdenCompraLineaResponse` para incluir `item_nombre: str | None`.

**[TEST]:**
- `test_saldos_item_nombre_resolved` — item presente en productos_erp → nombre retornado
- `test_saldos_phantom_item_fallback` — item NO en productos_erp → `item_nombre=None` en servicio, frontend o response lo muestra como `str(item_id)`

**Artifacts:**
- `backend/app/services/oc_ingresos_service.py` (MODIFIED)
- `backend/app/schemas/oc_ingreso.py` (MODIFIED — `item_nombre` en `OrdenCompraLineaResponse`)
- `backend/tests/integration/test_recepcion_deposito_endpoints.py` (MODIFIED)

**Acceptance criteria:**
- [ ] `item_nombre` presente en el response de `GET .../orden-compra/detalle`
- [ ] Ítem fantasma no filtra la línea (LEFT JOIN, línea siempre aparece)
- [ ] Tests verdes

**Spec refs:** REQ-RD-011.
**Design refs:** §7.

---

### RD-A.6: Servicio `recepcion_service.py` — saldos + state guard

**Size:** M
**Depends on:** RD-A.3, RD-A.4
**Parallelizable with:** RD-A.5
**Status:** [x]

**Work:**
Crear `backend/app/services/recepcion_service.py` con:

1. **`computar_saldos(session, pedido) -> SaldosResponse`**
   - Query A: `tb_purchase_order_detail` + `LEFT JOIN tb_storage` + `LEFT JOIN productos_erp` para líneas OC.
   - Query B: `SUM(cantidad_recibida)` de `pedido_compra_ingresos` agrupado por `pod_id WHERE pod_id IS NOT NULL`.
   - Join en Python: `saldo = pod_qty - COALESCE(pod_confirmedqty,0) - recibido_pricing`.
   - `item_nombre`: NULL → fallback `str(item_id)`.
   - Si `tiene_oc=False`: retornar `SaldosResponse` con `lineas=[]`.
   - Guard 409 si `pedido.estado not in {'pagado','con_faltantes','recibido'}`.

2. **`_validar_estado_receptivo(pedido) -> None`** (private)
   - 409 `"Pedido already fully received"` si `recibido`.
   - 409 `"Pedido not in a receivable state"` si otro estado.

3. **`recalcular_estado(session, pedido, oc_lineas_saldos: list[dict]) -> str`** (private)
   - Si ∀ saldo ≤ 0 → `pedido.estado = 'recibido'`, return `'recibido'`.
   - Si ∃ saldo > 0 → `pedido.estado = 'con_faltantes'`, return `'con_faltantes'`.

4. **`PERMISO_RECEPCION = "deposito.recibir_mercaderia"`** — constante en el módulo.

**[TEST]:**
- `test_computar_saldos_con_oc` — saldo = pod_qty - confirmedqty - ingresos previos
- `test_computar_saldos_sin_oc` — `tiene_oc=False`, `lineas=[]`
- `test_recalcular_estado_todos_cero_da_recibido`
- `test_recalcular_estado_alguno_positivo_da_con_faltantes`
- `test_validar_estado_receptivo_rechaza_recibido`
- `test_validar_estado_receptivo_rechaza_borrador`

**Artifacts:**
- `backend/app/services/recepcion_service.py` (NEW)
- `backend/tests/integration/test_recepcion_deposito_endpoints.py` (MODIFIED)

**Acceptance criteria:**
- [ ] Saldo formula correcta en tests
- [ ] `recibido` rechazado por state guard
- [ ] Estado no receptivo (borrador, aprobado, etc.) rechazado
- [ ] ERP tables no escritas en ningún path

**Spec refs:** REQ-RD-004, REQ-RD-007.
**Design refs:** §5, §3.

---

### RD-A.7: Servicio — `registrar_ingresos` (tanda atómica + over-receipt + evento) [TEST]

**Size:** M
**Depends on:** RD-A.6
**Parallelizable with:** no
**Status:** [x]

**Work:**
Agregar a `recepcion_service.py`:

**`registrar_ingresos(session, pedido, user, request: RegistrarIngresosRequest) -> RegistrarIngresosResponse`**:
1. Guard: `_validar_estado_receptivo(pedido)`.
2. Guard: si `pedido.oc_poh_id IS NULL` → 409 `"Pedido has no linked OC"`.
3. Filtrar `lineas` con `cantidad_recibida > 0` (silently ignore zeros).
4. Para cada línea no-cero: verificar `pod_id` existe en `tb_purchase_order_detail` → 422 si no.
5. Computar saldos actuales (pre-insert) para todas las líneas de la tanda.
6. Over-receipt check: si `cantidad_recibida_tanda > saldo_actual[pod_id]` → 409 con detail `"Over-receipt: pod_id {X} — saldo pendiente es {saldo}, solicitado {qty}"`. Check corre ANTES de cualquier INSERT.
7. INSERT atómico: un `PedidoCompraIngreso` por línea válida.
8. `recalcular_estado(session, pedido, saldos_post)`.
9. Emit `compras_eventos`: tipo `recepcion_registrada` o `recepcion_con_faltantes` según estado. Payload CON OC (design §8): `{"modo":"con_oc","lineas":[...],...}`. Para `recepcion_con_faltantes`, payload incluye TODAS las líneas OC (incluso no recibidas en esta tanda con `cantidad_recibida=0`).
10. Retornar `RegistrarIngresosResponse`.

**[TEST]:**
- `test_registrar_ingresos_partial_batch_da_con_faltantes`
- `test_registrar_ingresos_complete_batch_da_recibido`
- `test_registrar_ingresos_second_batch_desde_con_faltantes_da_recibido`
- `test_registrar_ingresos_second_batch_sigue_con_faltantes`
- `test_registrar_ingresos_over_receipt_409_no_inserts`
- `test_registrar_ingresos_atomic_rollback_partial_over_receipt`
- `test_registrar_ingresos_pedido_ya_recibido_409`
- `test_registrar_ingresos_sin_oc_409`
- `test_registrar_ingresos_zero_lines_ignored`
- `test_registrar_ingresos_evento_con_faltantes_incluye_todas_las_lineas`
- `test_registrar_ingresos_no_escribe_erp`

**Artifacts:**
- `backend/app/services/recepcion_service.py` (MODIFIED)
- `backend/tests/integration/test_recepcion_deposito_endpoints.py` (MODIFIED)

**Acceptance criteria:**
- [ ] Over-receipt → 409, cero INSERTs (atómico)
- [ ] `recepcion_con_faltantes` payload incluye líneas no recibidas en esta tanda
- [ ] ERP tables never written (assert en tests)
- [ ] Todos los tests de esta tarea verdes

**Spec refs:** REQ-RD-005, REQ-RD-007, REQ-RD-008, REQ-RD-012.
**Design refs:** §5, §8.

---

### RD-A.8: Servicio — `confirmar_pedido_sin_oc` (modo SIN OC + sentinel) [TEST]

**Size:** S
**Depends on:** RD-A.6
**Parallelizable with:** RD-A.9
**Status:** [x]

**Work:**
Agregar a `recepcion_service.py`:

**`confirmar_pedido_sin_oc(session, pedido, user, request: ConfirmarPedidoRequest) -> ConfirmarPedidoResponse`**:
1. Guard: si `pedido.oc_poh_id IS NOT NULL` → 409 `"Pedido has OC linked. Use /recepcion/ingresos instead."`.
2. Guard: `_validar_estado_receptivo(pedido)`.
3. Insertar 1 row sentinel en `pedido_compra_ingresos`: `pod_id=NULL, oc_*=NULL, item_id=NULL, stor_id=NULL, cantidad_recibida=1, usuario_id=user.id, observaciones=request.observaciones`.
4. `completo=True` → `pedido.estado = 'recibido'`, event `recepcion_registrada`. `completo=False` → `pedido.estado = 'con_faltantes'`, event `recepcion_con_faltantes`. Payload SIN OC (design §8): `{"modo":"sin_oc","completo":bool,"observaciones":str}`.
5. Retornar `ConfirmarPedidoResponse(pedido_id=pedido.id, estado_nuevo=pedido.estado)`.

**[TEST]:**
- `test_confirmar_sin_oc_completo_true_da_recibido`
- `test_confirmar_sin_oc_completo_false_da_con_faltantes`
- `test_confirmar_sin_oc_completo_false_sin_observaciones_422` (schema level)
- `test_confirmar_pedido_con_oc_da_409`
- `test_sentinel_pod_id_null_no_afecta_saldos` — saldos de pedido CON OC no contaminados por sentinelas

**Artifacts:**
- `backend/app/services/recepcion_service.py` (MODIFIED)
- `backend/tests/integration/test_recepcion_deposito_endpoints.py` (MODIFIED)

**Acceptance criteria:**
- [ ] Sentinel insertado con `pod_id=NULL`
- [ ] Saldo de pedido con OC no alterado por sentinel (índice parcial cumple su rol)
- [ ] 409 cuando pedido tiene OC

**Spec refs:** REQ-RD-006.
**Design refs:** §6.

---

### RD-A.9: Servicio — `get_eventos_recepcion` [TEST]

**Size:** S
**Depends on:** RD-A.6
**Parallelizable with:** RD-A.8
**Status:** [x]

**Work:**
Agregar a `recepcion_service.py`:

**`get_eventos_recepcion(session, pedido_id: int) -> EventosRecepcionResponse`**:
- Query `compras_eventos` donde `entidad_tipo='pedido_compra'`, `entidad_id=pedido_id`, `tipo IN ('recepcion_registrada','recepcion_con_faltantes')`.
- Order by `created_at DESC`.
- Resolver `usuario_nombre` via JOIN a `usuarios`.

**[TEST]:**
- `test_get_eventos_retorna_eventos_en_orden_desc`
- `test_get_eventos_lista_vacia`
- `test_get_eventos_filtra_solo_tipos_recepcion`

**Artifacts:**
- `backend/app/services/recepcion_service.py` (MODIFIED)
- `backend/tests/integration/test_recepcion_deposito_endpoints.py` (MODIFIED)

**Acceptance criteria:**
- [ ] Solo eventos de tipo recepción retornados
- [ ] Orden DESC por `created_at`

**Spec refs:** REQ-RD-009.
**Design refs:** §8.

---

### RD-A.10: Ampliar `generar-etiqueta-envio` — aceptar permiso depósito [TEST]

**Size:** S
**Depends on:** RD-A.2
**Parallelizable with:** RD-A.8, RD-A.9
**Status:** [x]

**Work:**
En `backend/app/routers/administracion_compras.py`, endpoint `POST /pedidos/{id}/generar-etiqueta-envio` (actualmente exige `gestionar_ordenes_compra`, L915 aprox.):
1. Cambiar a aceptar `deposito.recibir_mercaderia` OR `administracion.gestionar_ordenes_compra`. Usar helper existente `require_alguno([...])` si existe, o check explícito en el cuerpo del endpoint.
2. Sin cambios al servicio `etiqueta_retiro_service`; solo wiring de permiso en el router.

**[TEST]:**
- `test_generar_etiqueta_envio_con_permiso_deposito_201`
- `test_generar_etiqueta_envio_sin_ningun_permiso_403`
- `test_generar_etiqueta_envio_con_permiso_gestionar_oc_sigue_funcionando`

**Artifacts:**
- `backend/app/routers/administracion_compras.py` (MODIFIED — solo wiring de permiso)
- `backend/tests/integration/test_recepcion_deposito_endpoints.py` (MODIFIED)

**Acceptance criteria:**
- [ ] Operario con solo `deposito.recibir_mercaderia` puede llamar el endpoint → 201
- [ ] Sin ninguno de los dos permisos → 403
- [ ] Comportamiento del servicio sin cambios

**Spec refs:** REQ-RD-010, design D-RETIRO.
**Design refs:** §9.

---

### RD-A.11: Endpoints Batch K en `administracion_compras.py` [TEST]

**Size:** M
**Depends on:** RD-A.7, RD-A.8, RD-A.9, RD-A.10
**Parallelizable with:** no
**Status:** [x]

**Work:**
Agregar Batch K en `backend/app/routers/administracion_compras.py`:

1. **`GET /pedidos/{id}/recepcion/saldos`** — `require_permiso(PERMISO_RECEPCION)`, llama `computar_saldos`, response `SaldosResponse`. 409 si estado no receptivo; 404 si pedido no existe.

2. **`POST /pedidos/{id}/recepcion/ingresos`** — `require_permiso(PERMISO_RECEPCION)`, llama `registrar_ingresos`, response `RegistrarIngresosResponse` 201.

3. **`POST /pedidos/{id}/recepcion/confirmar-pedido`** — `require_permiso(PERMISO_RECEPCION)`, llama `confirmar_pedido_sin_oc`, response `ConfirmarPedidoResponse` 200.

4. **`GET /pedidos/{id}/recepcion/eventos`** — `require_permiso(PERMISO_RECEPCION)`, llama `get_eventos_recepcion`, response `EventosRecepcionResponse`.

Todos: 404 si pedido no existe antes de cualquier otra lógica.

**[TEST]:**
- `test_saldos_403_sin_permiso`
- `test_saldos_403_con_permiso_gestionar_oc_solamente` (D2 LOCKED — solo `deposito.recibir_mercaderia`)
- `test_saldos_404_pedido_inexistente`
- `test_saldos_200_con_oc`
- `test_saldos_200_sin_oc`
- `test_ingresos_403_sin_permiso`
- `test_ingresos_201_partial`
- `test_ingresos_201_complete`
- `test_ingresos_409_over_receipt`
- `test_confirmar_pedido_403`
- `test_confirmar_pedido_200_completo`
- `test_confirmar_pedido_200_con_faltantes`
- `test_confirmar_pedido_409_tiene_oc`
- `test_eventos_403`
- `test_eventos_200`

**Artifacts:**
- `backend/app/routers/administracion_compras.py` (MODIFIED — Batch K)
- `backend/tests/integration/test_recepcion_deposito_endpoints.py` (MODIFIED)

**Acceptance criteria:**
- [ ] `gestionar_ordenes_compra` solo → 403 en los 4 endpoints de recepción
- [ ] 404 devuelto antes que 403 cuando el pedido no existe (REQ-RD-X002)
- [ ] Todos los tests de endpoints verdes

**Spec refs:** REQ-RD-004, REQ-RD-005, REQ-RD-006, REQ-RD-009, REQ-RD-003, REQ-RD-X002.
**Design refs:** §1.

---

### RD-A.12: Tests state machine y ERP read-only [TEST]

**Size:** S
**Depends on:** RD-A.11
**Parallelizable with:** RD-A.13
**Status:** [x]

**Work:**
Agregar al test file los tests de estado y ERP que no quedaron cubiertos en tareas anteriores:

- `test_state_pagado_a_recibido_directo` — una tanda completa
- `test_state_pagado_con_faltantes_con_faltantes_recibido` — 3 tandas sucesivas, cada una con evento
- `test_state_recibido_rechaza_ingreso_409` — terminal
- `test_state_borrador_rechaza_ingreso_409`
- `test_erp_read_only_ingresos` — after successful POST ingresos, assert no writes to `tb_purchase_order_detail`, `tb_storage`, `productos_erp`

**Artifacts:**
- `backend/tests/integration/test_recepcion_deposito_endpoints.py` (MODIFIED)

**Acceptance criteria:**
- [ ] Multi-batch state transitions verified end-to-end
- [ ] ERP mirror tables never written

**Spec refs:** REQ-RD-007, REQ-RD-012, REQ-RD-X001.

---

### RD-A.13: Test — coexistencia de permisos (gestionar_oc + deposito) [TEST]

**Size:** S
**Depends on:** RD-A.11
**Parallelizable with:** RD-A.12
**Status:** [x]

**Work:**
- `test_ingresos_permiso_deposito_acepta` — user solo con `deposito.recibir_mercaderia` → 201 en POST ingresos
- `test_ingresos_permiso_gestionar_oc_rechaza` — user solo con `gestionar_ordenes_compra` → 403 en POST ingresos (D2 LOCKED)
- `test_generar_etiqueta_permiso_deposito_acepta` — ya cubre RD-A.10 pero aquí se valida en contexto de recepción completo

**Artifacts:**
- `backend/tests/integration/test_recepcion_deposito_endpoints.py` (MODIFIED)

**Acceptance criteria:**
- [ ] D2 LOCKED validado: `gestionar_ordenes_compra` NO acepta por sí solo en POST ingresos

**Spec refs:** REQ-RD-003 "Single-permission rule", REQ-RD-X001.

---

### RD-A.14: Smoke test local + `pytest` verde → [GATE Slice A] [GATE]

**Size:** S
**Depends on:** RD-A.12, RD-A.13
**Parallelizable with:** no
**Status:** [x]

**Work:**
1. Ejecutar `cd backend && pytest tests/integration/test_recepcion_deposito_endpoints.py -v --tb=short` → todos verdes.
2. Ejecutar `cd backend && alembic upgrade head` en DB local limpia → sin errores.
3. Ejecutar `cd backend && alembic downgrade -1 && alembic upgrade head` → sin errores.
4. Confirmar que ningún test existente rompió: `pytest tests/ -v --tb=short -x` (primer fallo aborta).

**Artifacts:** ninguno (gate de verificación)

**Acceptance criteria:**
- [ ] `test_recepcion_deposito_endpoints.py` 100% verde
- [ ] Suite completa sin regresiones
- [ ] Migraciones up/down limpias
- [ ] PR Slice A listo para review

---

## Slice B — Frontend

> **Prerequisito:** Slice A PR mergeado a main. Slice B branch hace stack sobre main.

### RD-B.1: [GATE stitch] Generar diseño visual con stitch [GATE]

**Size:** S
**Depends on:** RD-A.14 ✅
**Parallelizable with:** no (bloquea todo Slice B)
**Status:** ☐

**Work:**
Solicitar a **stitch** los siguientes mockups (design §10.1):
1. Acordeón de pedido — fila colapsada + expandida, badges estado `pagado`/`con_faltantes`/`recibido`, flag `requiere_envio`.
2. Tabla de ítems CON OC — checkbox tilde, nombre ítem + fallback fantasma, depósito, pod_qty, recibido previo, saldo, input cantidad, estado error input.
3. Barra de acciones — "Marcar todo", botón primario dinámico ("Marcar recibido" / "Registrar (quedará con faltantes)"), textarea observaciones.
4. Cartelito SIN OC — banner "Falta vincular la orden de compra" + botones "Confirmar recepción" / "Confirmar con faltantes".
5. Mini-modal retiro `ModalCargarRetiro` — lista/radio de direcciones + "Generar retiro" + feedback.
6. (Opcional) Timeline de eventos de recepción — lista read-only.

**Artifacts:**
- Mockups stitch guardados como referencia en `openspec/changes/compras-recepcion-deposito/stitch/` o inline en el PR de Slice B.

**Acceptance criteria:**
- [ ] Los 5 mockups obligatorios generados y aprobados
- [ ] Decisiones visuales (colores de badge, layout de tabla, comportamiento de input error) definidas antes de codear

**Spec refs:** REQ-RD-FE-001 gate note, design §10.1.

---

### RD-B.2: Tab `deposito` en `AdministracionCompras.jsx`

**Size:** S
**Depends on:** RD-B.1
**Parallelizable with:** RD-B.3, RD-B.4
**Status:** ☐

**Work:**
1. Agregar `{ id: 'deposito', label: 'Depósito' }` al array `TABS` en `AdministracionCompras.jsx`.
2. Condicionar la aparición del tab a `usePermisos().tienePermiso('deposito.recibir_mercaderia')` (seguir patrón de otros tabs con permiso).
3. Renderizar `<TabRecepcionDeposito />` cuando `activeTab === 'deposito'`.
4. Import lazy del componente (seguir convención del archivo).

**Artifacts:**
- `frontend/src/components/compras/AdministracionCompras.jsx` (MODIFIED)

**Acceptance criteria:**
- [ ] Tab "Depósito" aparece con permiso, oculto sin permiso
- [ ] No hay regresiones en otros tabs
- [ ] Lazy import correcto

**Spec refs:** REQ-RD-FE-001.

---

### RD-B.3: Servicio y hook `useRecepcionDeposito`

**Size:** S
**Depends on:** RD-B.1
**Parallelizable with:** RD-B.2, RD-B.4
**Status:** ☐

**Work:**
Crear `frontend/src/hooks/useRecepcionDeposito.js` (o extender `useComprasPedidos.js`):
- `getSaldos(pedidoId)` → `GET /pedidos/{id}/recepcion/saldos`
- `registrarIngresos(pedidoId, payload)` → `POST /pedidos/{id}/recepcion/ingresos`
- `confirmarPedido(pedidoId, payload)` → `POST /pedidos/{id}/recepcion/confirmar-pedido`
- `getEventos(pedidoId)` → `GET /pedidos/{id}/recepcion/eventos`
- `getDireccionesProveedor(proveedorId)` → `GET /proveedores/{id}/direcciones`
- `generarRetiro(pedidoId, payload)` → `POST /pedidos/{id}/generar-etiqueta-envio`

Todas via `services/api.js` (axios). No Zustand nuevo (estado tanda es efímero por acordeón, `useState`).

**Artifacts:**
- `frontend/src/hooks/useRecepcionDeposito.js` (NEW)

**Acceptance criteria:**
- [ ] Todas las funciones exportadas y tipadas con JSDoc mínimo
- [ ] Errores axios propagados para que los componentes los manejen

---

### RD-B.4: CSS Module para `TabRecepcionDeposito`

**Size:** S
**Depends on:** RD-B.1
**Parallelizable with:** RD-B.2, RD-B.3
**Status:** ☐

**Work:**
Crear `frontend/src/components/compras/TabRecepcionDeposito.module.css` con tokens Tesla:
- Clases: `.container`, `.accordion`, `.accordionHeader`, `.accordionBody`, `.itemTable`, `.inputCantidad`, `.inputError`, `.actionBar`, `.noOcBanner`, `.badgePagado`, `.badgeConFaltantes`, `.badgeRecibido`, `.retiroButton`.
- Sin Tailwind. Sin estilos inline en el componente.

**Artifacts:**
- `frontend/src/components/compras/TabRecepcionDeposito.module.css` (NEW)

**Acceptance criteria:**
- [ ] Tokens Tesla usados (var(--color-*), var(--spacing-*), etc.)
- [ ] Clases de badge distinguibles visualmente para los 3 estados

---

### RD-B.5: `TabRecepcionDeposito.jsx` — acordeón + modo CON OC

**Size:** L
**Depends on:** RD-B.2, RD-B.3, RD-B.4
**Parallelizable with:** RD-B.6
**Status:** ☐

**Work:**
Crear `frontend/src/components/compras/TabRecepcionDeposito.jsx`:

1. **Lista:** fetch pedidos `estado=pagado,con_faltantes` (query param al endpoint existente de lista de pedidos). Cada pedido = fila acordeón con badge de estado + flag `requiere_envio`.

2. **Al expandir (tiene_oc=true):** `getSaldos(pedidoId)` → tabla de ítems con columnas: [checkbox tilde] · ítem (nombre o `Ítem #${item_id}` si fantasma) · depósito · pod_qty · recibido prev · saldo · [input cantidad].

3. **Estado local de tanda:** `useState({ [pod_id]: value })`.
   - Tilde checked → `input = saldo_pendiente`.
   - Tilde unchecked → `input = 0`.
   - "Marcar todo" → todas las filas con saldo > 0 se tildan.
   - Input manual `> saldo` → borde rojo + botón submit disabled.

4. **Botones:**
   - "Marcar recibido" (habilitado si ∀ inputs == saldo_pendiente y ningún error).
   - "Registrar (quedará con faltantes)" (habilitado si ∃ input > 0 y ningún error pero no todos iguales al saldo).
   - On submit: `registrarIngresos(pedidoId, {lineas: nonZeroLines, observaciones})`. On 409 → toast error con detail. On 201 → toast éxito + refresh saldos.

5. **Botón "Cargar retiro"** (si `requiere_envio=true`) → abre `ModalCargarRetiro`.

**Artifacts:**
- `frontend/src/components/compras/TabRecepcionDeposito.jsx` (NEW)

**Acceptance criteria:**
- [ ] Checkbox tilde auto-llena el input con saldo (REQ-RD-FE-003)
- [ ] "Marcar todo" llena todos los inputs (REQ-RD-FE-003)
- [ ] "Marcar recibido" deshabilitado si queda saldo sin cubrir (REQ-RD-FE-003)
- [ ] Input > saldo → borde rojo + submit disabled
- [ ] P3 (estado recibido) NO aparece en la lista (REQ-RD-FE-002)

**Spec refs:** REQ-RD-FE-002, REQ-RD-FE-003.

---

### RD-B.6: `TabRecepcionDeposito.jsx` — modo SIN OC

**Size:** S
**Depends on:** RD-B.3, RD-B.4
**Parallelizable with:** RD-B.5
**Status:** ☐

**Work:**
En `TabRecepcionDeposito.jsx`, al expandir un pedido con `tiene_oc=false`:
- Mostrar banner: `"Este pedido no tiene OC vinculada. No es posible registrar por ítem."`.
- Botón "Confirmar recibido" → `confirmarPedido(pedidoId, {completo: true})`.
- Botón "Marcar con faltantes" → abre un inline textarea para `observaciones` (required) + botón confirmar → `confirmarPedido(pedidoId, {completo: false, observaciones})`.
- On success: refresh pedido, toast.
- NO mostrar tabla de ítems.

**Artifacts:**
- `frontend/src/components/compras/TabRecepcionDeposito.jsx` (MODIFIED — agrega rama SIN OC)

**Acceptance criteria:**
- [ ] Banner visible, tabla ausente cuando `tiene_oc=false` (REQ-RD-FE-004)
- [ ] "Marcar con faltantes" sin observaciones → textarea en error, no envía
- [ ] Pedido pasa a `con_faltantes` o `recibido` en la UI tras confirmar

**Spec refs:** REQ-RD-FE-004.

---

### RD-B.7: `ModalCargarRetiro.jsx`

**Size:** S
**Depends on:** RD-B.3, RD-B.4
**Parallelizable with:** no (depende de B.5 por el trigger)
**Status:** ☐

**Work:**
Crear `frontend/src/components/compras/ModalCargarRetiro.jsx` (espeja shape de `ModalVincularOC.jsx`):
1. Props: `pedidoId`, `proveedorId`, `isOpen`, `onClose`, `onSuccess`.
2. Al abrir: `getDireccionesProveedor(proveedorId)` → lista radio-select de direcciones activas.
3. Si una sola dirección: pre-seleccionada automáticamente.
4. Botón "Generar retiro" → `generarRetiro(pedidoId, {proveedor_direccion_id: selected})`. On 201 → toast éxito + `onSuccess()`. On 409 → toast error (ya existe etiqueta).
5. NO montar ni importar `TabEnviosFlex`.

**Artifacts:**
- `frontend/src/components/compras/ModalCargarRetiro.jsx` (NEW)

**Acceptance criteria:**
- [ ] Modal lista direcciones del proveedor (REQ-RD-FE-005)
- [ ] Confirmar → `POST generar-etiqueta-envio` con `proveedor_direccion_id` correcto
- [ ] `TabEnviosFlex` no importado (grep confirma)
- [ ] Botón "Cargar retiro" ausente en pedidos con `requiere_envio=false`

**Spec refs:** REQ-RD-FE-005, REQ-RD-010.

---

### RD-B.8: Integración final + smoke test manual

**Size:** S
**Depends on:** RD-B.5, RD-B.6, RD-B.7
**Parallelizable with:** RD-B.9
**Status:** ☐

**Work:**
1. Verificar que tab "Depósito" carga sin errores de consola.
2. Flujo CON OC manual: expandir pedido, marcar todo, registrar → estado `recibido` visible.
3. Flujo SIN OC manual: expandir, confirmar recibido.
4. Flujo retiro manual: abrir modal, seleccionar dirección, confirmar → toast éxito.
5. Verificar que usuario sin permiso no ve el tab.

**Artifacts:** ninguno (QA manual)

**Acceptance criteria:**
- [ ] 0 errores de consola en flujo happy path
- [ ] Estado del pedido actualizado en UI tras recepción
- [ ] Tab oculto sin permiso

---

### RD-B.9: Lint + PR Slice B listo [GATE]

**Size:** S
**Depends on:** RD-B.8
**Parallelizable with:** no
**Status:** ☐

**Work:**
1. `npx eslint frontend/src/components/compras/TabRecepcionDeposito.jsx ModalCargarRetiro.jsx` → 0 errores.
2. Verificar que no hay `import ... from TabEnviosFlex` en ningún archivo nuevo.
3. PR Slice B ready for review (target: main, stacked after Slice A PR).

**Artifacts:** ninguno

**Acceptance criteria:**
- [ ] ESLint limpio
- [ ] TabEnviosFlex ausente de imports nuevos
- [ ] PR abierto con Slice B

---

## Review Workload Forecast

| Slice | Líneas estimadas | Budget 400 | Chained PRs | Decisión antes de apply |
|-------|-----------------|------------|-------------|------------------------|
| A — Backend | ~380-420 líneas | **ALTO** (riesgo real) | Sí (PR #1) | Confirmar `alembic heads` + col real `productos_erp` (RD-A.1) |
| B — Frontend | ~350-400 líneas | **ALTO** | Sí (PR #2) | Gate stitch aprobado (RD-B.1) |

**Chained PRs recomendado: Sí.** Cada slice es un PR independiente, stacked-to-main.

**Decisiones pendientes antes de `sdd-apply`:**
1. RD-A.1: confirmar `alembic heads` (valor concreto de `down_revision` de la migración).
2. RD-A.1: confirmar columna real de `productos_erp` para el JOIN de `item_nombre`.
3. RD-B.1: stitch mockups aprobados antes de codear Slice B.

---

## Dependency summary

```
Slice A (serial backbone):
RD-A.1 → RD-A.2 → RD-A.3 → RD-A.4
                           ↓         ↓
                       RD-A.5    RD-A.6
                       (paralelo) ↓
                              RD-A.7
                                 ↓
                  RD-A.8 ──────┬──────── RD-A.9
                  (paralelo)   │         (paralelo)
                          RD-A.10
                  (paralelo, depende A.2)
                              ↓
                          RD-A.11
                              ↓
                  RD-A.12 ──────── RD-A.13
                  (paralelo)       (paralelo)
                              ↓
                          RD-A.14 [GATE]

Slice B (depende de A.14 ✅):
RD-B.1 [GATE stitch]
    ↓
RD-B.2 ──── RD-B.3 ──── RD-B.4  (paralelo)
    ↓            ↓           ↓
         RD-B.5 ──── RD-B.6     (paralelo)
                 ↓
             RD-B.7
                 ↓
             RD-B.8 ──── RD-B.9 (paralelo)
```

# Tasks — Módulo de Compras (v1)

**Change:** `modulo-compras`
**Fase:** tasks
**Status:** draft
**Persistence mode:** hybrid
**Fecha:** 2026-04-17

---

## 0. Leyenda y convenciones

- **IDs**: `COMPRAS-<FASE>.<NUM>` (ej. `COMPRAS-1.3`). Las fases son de 0 a 8.
- **Size**: S (<2h), M (2-6h), L (6-12h), XL (12-24h). Todo task de >1 día real se parte.
- **Depends on**: lista de IDs o `ninguno` / `fase anterior`.
- **Parallelizable with**: lista de IDs dentro de la misma fase que pueden correr en paralelo, o `no` si requiere serial.
- **Artifacts**: archivos a crear/modificar. Marcados `NEW` / `MODIFIED` / `DELETED`.
- **Acceptance criteria**: checklist binaria verificable.
- **Implementation notes**: referencia a `design.md §X` o `specs/<file>.md#REQ-YYY-ZZZ`.

**Conventions**:
- Migraciones Alembic con prefijo `compras_NNN_<descripcion>.py` (NNN = 001..0XX, orden estricto).
- Tests unitarios en `backend/tests/unit/test_*.py`, integración en `backend/tests/integration/test_*.py`.
- Linter backend: `ruff format --check` + `ruff check`.
- Linter frontend: `npx eslint` (el proyecto ya lo tiene configurado).
- **Nunca** build post-cambio (AGENTS.md rule).
- **Gates entre fases**: no se arranca la siguiente fase hasta que la anterior tenga todos sus tasks marcados ✅ y sus tests verdes.

---

## Resumen ejecutivo

| Fase | Tasks | Size total | Critical path | Gate |
|------|-------|------------|---------------|------|
| 0. Pre-flight checks | 3 activas (0.1 CANCELADA) | S total (~1h) | **BLOQUEANTE** | mapeo ERP + sync verde + cliente_id nullable |
| 1. Foundations (migraciones, modelos, seeds) | 19 | ~3-4 días | alembic + modelos SQLAlchemy + seed estático tb_sale_document | todas las migraciones `upgrade` + `downgrade` OK |
| 2. Servicios base | 8 | ~3 días | clasificador + numeración + cc_proveedor | tests unitarios verdes |
| 3. Matching ERP | 4 | ~1.5 días | vista + hook matching + cron reconciliación | vista JUKEBOX tests verdes + hook no rompe cron |
| 4. Servicios de flujo | 9 | ~4 días | imputaciones + OP + matching service | integración end-to-end en staging |
| 5. Endpoints REST | 12 | ~3 días | routers administracion.compras.* | OpenAPI actualizado, 401/403/422 cubiertos |
| 6. Frontend | 14 | ~5 días | AdministracionCompras + modales + paneles admin | e2e manual pass |
| 7. Tests | 9 | ~3 días | concurrencia, matching, 43 sd_id, state machine | coverage >= 80% en services nuevos |
| 8. Deploy | 6 | ~1 día | seeds críticos, permisos, smoke tests | checklist de DoD cumplido |
| **TOTAL** | **85 tasks activas** (86 - 0.1 cancelada - 3.1 eliminada - 3.2 eliminada + 1.2b nueva) | **~20-23 días dev senior** (ahorro ~2 días por eliminar script sync + endpoint + cron) | | |

Tasks críticos/bloqueantes (**no se pueden saltear**):
- ~~**COMPRAS-0.1**~~ — CANCELADA (tb_sale_document es seed estático, no hay sync ERP)
- **COMPRAS-0.2** — confirmar mapeo `EMPRESA_A_COMP_BRA_MAP` (bloquea F1, F4)
- **COMPRAS-0.3** — confirmar sync ERP en verde (bloquea F3)
- **COMPRAS-8.1** — **PRE-DEPLOY CRITICAL**: seed de cajas USD por empresa
- **COMPRAS-8.2** — **PRE-DEPLOY CRITICAL**: seed permisos críticos sin asignación default

---

## Fase 0 — Pre-flight checks (BLOQUEANTE)

> Esta fase NO escribe código. Son verificaciones humanas + queries que deben responder "OK" antes de habilitar Fase 1. Si CUALQUIERA falla, ABORTAR apply y resolver antes de continuar.

### Task COMPRAS-0.1: ~~Confirmar nombre exacto de tabla catálogo en ERP~~ — **CANCELADA**
**Status:** 🚫 CANCELADA (refinement 2026-04-17, Engram obs #121)
**Razón:** `tb_sale_document` pasó a ser **seed estático Alembic** — ya no hay sync desde el ERP. No se necesita confirmar el nombre de la tabla origen en el ERP porque nunca vamos a consultarla programáticamente. Los ~43 registros se insertan vía migration (ver COMPRAS-1.2b). Tipos nuevos en el futuro → nueva Alembic migration.

**No ejecutar.** Se deja el hueco `COMPRAS-0.1` a propósito para trazabilidad histórica; no renumerar las tasks siguientes para no romper referencias cruzadas en specs/obs.

---

### Task COMPRAS-0.2: Confirmar valores reales de `EMPRESA_A_COMP_BRA_MAP`
**Size:** S
**Depends on:** ninguno
**Parallelizable with:** 0.1, 0.3, 0.4
**Status:** ✅ CONFIRMADO por usuario el 2026-04-17
**Artifacts:**
- `openspec/changes/modulo-compras/state.yaml` (MODIFIED — agregar key `preflight.empresa_comp_bra_map`)

**Valor confirmado:**
```python
EMPRESA_A_COMP_BRA_MAP: dict[int, tuple[int, int]] = {
    1: (1, 1),      # Empresa 1 → comp_id=1, bra_id=1  (sucursal principal)
    2: (1, 45),     # Empresa 2 → comp_id=1, bra_id=45 (Grupo Gauss)
}

# Mapa inverso para resolver desde ct (bra_id del ERP) hacia empresa local
COMP_BRA_A_EMPRESA: dict[tuple[int, int], int] = {
    (1, 1): 1,
    (1, 45): 2,
}
```

**Acceptance criteria:**
- [x] Mapeo confirmado con usuario (2026-04-17): 2 empresas → bra_id 1 y 45.
- [ ] Valor registrado en state.yaml bajo `preflight.empresa_comp_bra_map`.
- [ ] Query de verificación corrida: `SELECT DISTINCT comp_id, bra_id FROM tb_commercial_transactions WHERE supp_id IS NOT NULL AND ct_date >= NOW() - INTERVAL '90 days'` — los valores `(1, 1)` y `(1, 45)` DEBEN aparecer con volumen significativo. Si aparecen otros bra_id con volumen alto (>10 filas) → investigar antes de seguir (posible tercera empresa sin mapear).

**Implementation notes:**
- **Reemplaza D14** ("hardcoded 1:1 v1"). Ahora el mapeo es configurable.
- El mapa vive en `backend/app/core/compras_empresa_erp_map.py` (creado en COMPRAS-1.3).
- Los bra_id `35, 36, 37, 38, 39, 40, 42` (vistos en `tb_document_file`) corresponden a **sucursales de transferencia internas** (solo remitos), NO son empresas comerciales. Si aparecen en ct con `supp_id IS NOT NULL` → LOG WARNING + IGNORAR (implementar `bra_a_empresa_o_ignorar()` en `compras_empresa_erp_map.py`).

---

### Task COMPRAS-0.3: Confirmar sync ERP `tb_commercial_transactions` en verde
**Size:** S
**Depends on:** ninguno
**Parallelizable with:** 0.1, 0.2, 0.4
**Status:** ✅ VERIFICADO 2026-04-17
**Artifacts:** ninguno (verificación)

**Valores medidos (2026-04-17 18:52 ART):**
- Total filas: 458.896 ✅
- ct_date más reciente: 2026-04-17 (mismo día) ✅
- Último sync: 18:40 (minutos atrás) ✅
- Compras últimos 30d: 234 movimientos / 45 proveedores distintos ✅

**Acceptance criteria:**
- [x] `SELECT MAX(ct_date) FROM tb_commercial_transactions` retorna una fecha `>= CURRENT_DATE - 2` — valor real: CURRENT_DATE (0 días de delay).
- [x] Cron `sync_commercial_transactions_guid.py` activo — verificado 88 filas insertadas hoy.
- [x] Tabla tiene >= 10k filas — valor real: 458.896.
- [x] Sync operativo continuo validado (7 días con inserts diarios).

**Implementation notes:**
- Bloqueante porque sin `tb_commercial_transactions` fresco, el hook de matching (F3) no sirve.
- Dataset de 45 proveedores activos + 234 compras en 30d es SUFICIENTE para fixtures de testing (COMPRAS-7.3 JUKEBOX tests).

---

### Task COMPRAS-0.4: Inventariar `etiquetas_envio` — is_nullable de `cliente_id`
**Size:** S
**Depends on:** ninguno
**Parallelizable with:** 0.1, 0.2, 0.3
**Artifacts:**
- `openspec/changes/modulo-compras/state.yaml` (MODIFIED — `preflight.etiquetas_envio_cliente_id_nullable`)

**Acceptance criteria:**
- [ ] Ejecutada: `SELECT is_nullable FROM information_schema.columns WHERE table_name='etiquetas_envio' AND column_name='cliente_id'`.
- [ ] Resultado registrado en state.yaml.
- [ ] Count de filas existentes registrado: `SELECT count(*) FROM etiquetas_envio` (para estimar impacto del backfill).
- [ ] Grep de queries frontend/backend que referencian `etiquetas_envio.cliente_id` con asunción NOT NULL — documentar en state.yaml como lista para revisión post-migración.

**Implementation notes:**
- Determina si la migración de `etiquetas_envio` requiere 1 o 2 pasos (RD1 del design §11).
- Si `is_nullable='NO'`, COMPRAS-1.7 agrega el paso `ALTER COLUMN cliente_id DROP NOT NULL`.

---

## Fase 1 — Foundations (migraciones, modelos, seeds, configuración)

> Una migración Alembic por grupo lógico. Modelos SQLAlchemy en paralelo a cada migración (mismo task cuando son 1:1). Seeds al final (después de que migraciones crearon las tablas destino).

### Task COMPRAS-1.1: Migración `compras_001_numeracion_contadores.py` ✅ (Batch 1A)
**Size:** S
**Depends on:** fase 0
**Parallelizable with:** 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9
**Artifacts:**
- `backend/alembic/versions/compras_001_numeracion_contadores.py` (NEW)
- `backend/app/models/numeracion_contador.py` (NEW)

**Acceptance criteria:**
- [x] Tabla `numeracion_contadores` creada según design §1.6 (PK compuesta `(tipo, empresa_id, anio)`, `ultimo_numero INT NOT NULL DEFAULT 0`, `updated_at TIMESTAMPTZ`).
- [x] Columna `anio` (sin tilde) según decisión de design §1.6.
- [x] FK `empresa_id → empresas(id) ON DELETE RESTRICT`.
- [x] `CHECK (ultimo_numero >= 0)` y `CHECK (anio BETWEEN 2020 AND 2100)`.
- [x] Modelo SQLAlchemy `NumeracionContador` en `app/models/numeracion_contador.py` con `__tablename__ = 'numeracion_contadores'`.
- [ ] `alembic upgrade head` pasa contra DB local limpia. (pendiente — ejecuta usuario)
- [ ] `alembic downgrade -1` revierte correctamente. (pendiente — ejecuta usuario)
- [x] `ruff format --check` pasa.

**Implementation notes:**
- Design §1.6. Es la base de la numeración usada por pedidos y OPs (deps de 1.4 y 1.5).

---

### Task COMPRAS-1.2: Migración `compras_002_tb_sale_document.py` (estructura de tabla, SIN seed) ✅ (Batch 1A)
**Size:** S
**Depends on:** fase 0 (0.2, 0.3, 0.4 — 0.1 cancelada)
**Parallelizable with:** 1.1, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9
**Artifacts:**
- `backend/alembic/versions/compras_002_tb_sale_document.py` (NEW)
- `backend/app/models/tb_sale_document.py` (NEW)

**Acceptance criteria:**
- [x] Tabla `tb_sale_document` creada según design §1.7 (`sd_id INT PK sin autogenerar`, todos los flags booleanos `NOT NULL DEFAULT FALSE`, `sd_plusorminus SMALLINT CHECK IN (1,-1)`, `hacc_group INT NULL`).
- [x] **NO incluir columna `synced_at`** (refinement 2026-04-17: tabla es seed estático, no hay sync).
- [x] Índices: `ix_tb_sale_document_ispurchase WHERE sd_ispurchase=TRUE`, `ix_tb_sale_document_isannul WHERE sd_isannulment=TRUE`, `ix_tb_sale_document_hacc WHERE hacc_group IS NOT NULL`.
- [x] Modelo SQLAlchemy `SaleDocument` (SIN campo `synced_at`).
- [x] Nombres de columnas en Python en snake_case todo lowercase (`sd_iscredit`, `sd_ispurchase`, etc., NO camelCase).
- [ ] `alembic upgrade head` + `alembic downgrade -1` OK. (pendiente — ejecuta usuario)

**Implementation notes:**
- REQ-SDC-001. Este modelo es fuente del clasificador (COMPRAS-2.1).
- Esta task crea solo la **estructura**. El seed con los 43 registros va en COMPRAS-1.2b.

---

### Task COMPRAS-1.2b: Seed estático `tb_sale_document` (Alembic, ~43 registros)
**Size:** M
**Depends on:** 1.2 (tabla creada)
**Parallelizable with:** 1.3..1.9 (independiente después de 1.2)
**Artifacts:**
- `backend/alembic/versions/compras_NNNN_seed_tb_sale_document.py` (NEW — numerar secuencialmente tras 1.2)

**Acceptance criteria:**
- [x] Migración Alembic con `op.bulk_insert()` de los 67 registros conocidos del ERP (el prompt decía ~43 pero el contenido real de las dos tablas son 67 — levantado en batch_1b_riesgos).
- [x] Dos bloques de datos (cubiertos en Engram obs #106):
  - [x] **sd_id 1-80** (catálogo de VENTAS, `sd_issales=TRUE`) — 20 registros.
  - [x] **sd_id 101-500** (catálogo de COMPRAS / BANCOS / OTROS: `sd_ispurchase=TRUE` o `sd_isbanking=TRUE`) — 47 registros.
- [x] Cada fila lleva los flags **inferidos siguiendo reglas explícitas del prompt** (descripción + rango sd_id) — el usuario no pasó las columnas booleanas completas, solo `sd_desc` y `sd_plusOrminus`, el resto se derivó semánticamente. 13 sd_id marcados como AMBIGUO en comentarios inline (7, 15, 31, 33, 80, 125, 131, 145, 205, 301, 302, 350, 500).
- [x] `downgrade()` hace `DELETE FROM tb_sale_document WHERE sd_id = ANY(...)` con la lista explícita de los 67 sd_id insertados.
- [x] **Test de regresión**: creado `backend/tests/unit/test_sale_document_classifier.py` con 67 tests parametrizados por sd_id — actualmente `@pytest.mark.skip` esperando que COMPRAS-2.1 implemente el clasificador en F2. 2 tests activos validan count=67 y unicidad.
- [ ] `alembic upgrade head` + `alembic downgrade -1` idempotente. (pendiente — ejecuta usuario)

**Implementation notes:**
- ⚠ **Fuente de datos**: las dos tablas exactas (sd_id 1-80 ventas + sd_id 101-500 compras/bancos con todos los flags y `hacc_group`) están en **Engram obs #106** (topic_key `sdd/modulo-compras/sale-document-catalog`) y en la conversación original del usuario. **COPIAR EXACTO**, no inventar flags.
- Durante `sdd-apply` de esta task: recuperar obs #106 con `mem_get_observation(id=106)`, parsear las dos tablas, armar los INSERTs.
- **POR QUÉ seed estático** (no sync): decisión usuario post-design (Engram obs #121). La tabla del ERP cambia 1-2 veces por año (tipos de documento). Sincronizar una tabla casi estática es overhead innecesario. Tipos nuevos en el futuro → nueva Alembic migration.
- REQ-SDC-001 + REQ-SDC-003 (reescrito: ya no es cron, es seed estático).

---

### Task COMPRAS-1.3: Archivo `compras_empresa_erp_map.py` + constantes ERP
**Size:** S
**Depends on:** 0.2 (mapeo confirmado)
**Parallelizable with:** 1.1, 1.2, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9
**Artifacts:**
- `backend/app/core/compras_empresa_erp_map.py` (NEW)
- `backend/app/core/compras_erp_constants.py` (NEW)
- `backend/app/core/compras_erp_config.py` (DELETED — ver nota)

**Acceptance criteria:**
- [x] `compras_empresa_erp_map.py` exporta:
  - `EMPRESA_A_COMP_BRA_MAP: dict[int, tuple[int, int]] = {1: (1, 1), 2: (1, 45)}` (valores confirmados por usuario 2026-04-17)
  - `COMP_BRA_A_EMPRESA: dict[tuple[int, int], int] = {(1, 1): 1, (1, 45): 2}` (mapa inverso)
- [x] Función `resolver_comp_bra(empresa_id: int) -> tuple[int, int]` que retorna la tupla; raise `KeyError` con mensaje claro si la empresa no está mapeada.
- [x] Función `bra_a_empresa_o_ignorar(comp_id: int, bra_id: int) -> Optional[int]` que:
  - Retorna `empresa_id` si `(comp_id, bra_id)` está mapeado
  - Retorna `None` si NO está mapeado + log WARNING (`ct con comp_id=X bra_id=Y no mapea a empresa local — ignorada`)
  - Esto maneja el caso de sucursales de transferencia internas (bra_id 35, 36, 37, 38, 39, 40, 42) que NO son empresas comerciales.
- [x] `compras_erp_constants.py` exporta `ERP_SD_ID_ORDEN_PAGO: Final[int] = 106` (design §7.1, única excepción al "no números mágicos" documentada).
- [ ] Si existe `backend/app/core/compras_erp_config.py` del pasado (listas hardcodeadas), ELIMINARLO — ya no se usa (abandonado en favor de clasificación flag-based, proposal §Scope). **Verificado en batch 1B: el archivo NO existe, nada que eliminar.**
- [x] Tests unitarios en `backend/tests/unit/test_compras_empresa_erp_map.py` cubriendo (9/9 pasan):
  - `resolver_comp_bra(1)` → `(1, 1)` ✅
  - `resolver_comp_bra(2)` → `(1, 45)` ✅
  - `resolver_comp_bra(99)` → raise `KeyError` ✅
  - `bra_a_empresa_o_ignorar(1, 1)` → `1` ✅
  - `bra_a_empresa_o_ignorar(1, 45)` → `2` ✅
  - `bra_a_empresa_o_ignorar(1, 35)` → `None` + log WARNING asserted ✅
  - `bra_a_empresa_o_ignorar(1, 999)` → `None` + log WARNING asserted ✅
  - Extras (sanity checks del dict): consistencia entre mapa directo y inverso (2 tests) ✅

**Implementation notes:**
- Cierre 3 del usuario (reemplaza D14 "hardcoded 1:1 v1").
- Valores definitivos confirmados por usuario:
  - Empresa 1 (sucursal principal) → `comp_id=1, bra_id=1`
  - Empresa 2 (Grupo Gauss) → `comp_id=1, bra_id=45`
- Los bra_id 35-42 son sucursales internas de transferencia (solo remitos), NO empresas comerciales.

---

### Task COMPRAS-1.4: Migración `compras_003_pedidos_compra.py` ✅ (Batch 1A)
**Size:** M
**Depends on:** 1.1 (numeracion_contadores), 1.3 (erp map — para FK lógica)
**Parallelizable with:** 1.2, 1.5 (con cuidado), 1.6, 1.7, 1.8, 1.9
**Artifacts:**
- `backend/alembic/versions/compras_003_pedidos_compra.py` (NEW)
- `backend/app/models/pedido_compra.py` (NEW)

**Acceptance criteria:**
- [x] Tabla `pedidos_compra` creada según design §1.1 con TODOS los campos y constraints (CHECK de `estado`, `monto > 0`, `moneda IN ('ARS','USD')`).
- [x] FKs a `empresas`, `proveedores`, `usuarios` (`creado_por_id`, `aprobado_por_id`) con ON DELETE RESTRICT/SET NULL según design §1.1.
- [x] `ct_transaction_id BIGINT NULL` (SIN FK física, por decisión D1).
- [x] `CONSTRAINT uq_pedidos_compra_numero UNIQUE (numero)`.
- [x] 4 índices: `ix_pedidos_compra_empresa_estado`, `ix_pedidos_compra_proveedor_created`, `ix_pedidos_compra_numero_factura` (partial), `ix_pedidos_compra_ct_transaction` (partial).
- [x] Modelo SQLAlchemy `PedidoCompra` con relationships a `Empresa`, `Proveedor`, `Usuario`. (Enum `EstadoPedidoCompra` se mapea con CHECK constraint + string — se declara en servicio en F4, no en el modelo).
- [ ] `alembic upgrade head` + `downgrade -1` OK. (pendiente — ejecuta usuario)

**Implementation notes:**
- REQ-PED-001 + design §1.1. `ct_transaction_id` queda como columna suelta (matching la completa después).
- Los eventos van en `compras_eventos` (ver 1.6), no hay tabla `pedido_compra_eventos` separada.

---

### Task COMPRAS-1.5: Migración `compras_005_ordenes_pago.py` (renumerada desde prompt) ✅ (Batch 1A)
**Size:** M
**Depends on:** 1.1 (numeracion_contadores)
**Parallelizable with:** 1.2, 1.4 (con cuidado), 1.6, 1.7, 1.8, 1.9
**Artifacts:**
- `backend/alembic/versions/compras_005_ordenes_pago.py` (NEW — renumerada de 004 a 005 según prompt user)
- `backend/app/models/orden_pago.py` (NEW)

**Acceptance criteria:**
- [x] Tabla `ordenes_pago` según design §1.3 (16 columnas, CHECK de `estado`, `modo_imputacion`, `moneda`, `monto_total > 0`).
- [x] FKs: `empresa_id`, `proveedor_id`, `caja_id → cajas(id)`, `caja_movimiento_id → caja_movimientos(id)`, `caja_documento_id → caja_documentos(id)` (todas `ON DELETE RESTRICT`).
- [x] Nombres reales de tablas de caja verificados (`caja_movimientos`, `caja_documentos`). **RIESGO**: design dice `caja_movimiento_id BIGINT` pero `caja_movimientos.id` es Integer → se usó Integer en la FK (levantado en contract result).
- [x] `CONSTRAINT uq_ordenes_pago_numero UNIQUE (numero)`.
- [x] 3 índices: `ix_ordenes_pago_proveedor_estado`, `ix_ordenes_pago_empresa_created`, `ix_ordenes_pago_caja_mov` (partial).
- [x] Modelo SQLAlchemy `OrdenPago` con CHECK constraints equivalentes a enums (`EstadoOrdenPago` y `ModoImputacion` se definirán como constantes en F4).
- [ ] Migration idempotente + downgrade OK. (pendiente — ejecuta usuario)

**Implementation notes:**
- REQ-OP-001 + design §1.3. Si los nombres reales de tablas de caja difieren, corregir ANTES de merge.

---

### Task COMPRAS-1.6: Migración `compras_004_compras_eventos.py` (renumerada desde prompt) ✅ (Batch 1A)
**Size:** S
**Depends on:** 1.4, 1.5
**Parallelizable with:** 1.7, 1.8, 1.9
**Artifacts:**
- `backend/alembic/versions/compras_004_compras_eventos.py` (NEW — renumerada de 005 a 004 según prompt user)
- `backend/app/models/compra_evento.py` (NEW — modelo `CompraEvento`)

**Acceptance criteria:**
- [x] Tabla `compras_eventos` polimórfica según design §1.2 (`entidad_tipo IN ('pedido_compra','orden_pago')`, `entidad_id BIGINT`, `tipo VARCHAR(48)`, `payload JSONB`).
- [x] FK `usuario_id → usuarios ON DELETE RESTRICT`.
- [x] Índices: `ix_compras_eventos_entidad` (entidad_tipo, entidad_id, created_at DESC), `ix_compras_eventos_tipo`.
- [x] Modelo `CompraEvento` con constantes `ENTIDAD_TIPO_PEDIDO`, `ENTIDAD_TIPO_ORDEN_PAGO`. Whitelist `TIPO_EVENTO_*` se declarará en F4 junto con los servicios que los emiten.
- [ ] **NO** se expone endpoint PUT/DELETE en routers (verificado en F5).
- [ ] Downgrade OK. (pendiente — ejecuta usuario)

**Implementation notes:**
- D2: polimórfica reemplaza tabla separada `pedido_compra_eventos`. Cierra OP-01.
- Append-only enforcement a nivel servicio (v1 no agregamos trigger BEFORE UPDATE/DELETE; se documenta como tech-debt).

---

### Task COMPRAS-1.7: Migración `compras_006_etiquetas_envio_extend.py` — **CONSOLIDADA con 1.8** ✅ (Batch 1A)
**Size:** S
**Depends on:** 0.4 (inventario), 1.4
**Parallelizable with:** 1.9
**Artifacts:**
- `backend/alembic/versions/compras_006_etiquetas_envio_extend.py` (NEW — 1 paso, no 2)

**Acceptance criteria:**
- [x] Migración en 1 PASO (no 2). COMPRAS-0.4 confirmó que `cliente_id` NO existe como columna en `etiquetas_envio` → no hace falta `DROP NOT NULL`.
- [x] Agrega 4 columnas: `tipo_envio VARCHAR(24) NOT NULL DEFAULT 'cliente'`, `proveedor_id INT NULL`, `proveedor_direccion_id INT NULL`, `pedido_compra_id BIGINT NULL`.
- [x] FKs ON DELETE RESTRICT a `proveedores`, `proveedor_direcciones` (nombre real verificado, no `proveedor_direccion`), `pedidos_compra`.
- [x] CHECK `ck_etiqueta_envio_tipo_envio` (IN cliente/retiro_proveedor) + `chk_etiqueta_envio_tipo_coherencia`.
- [x] Backfill explícito (UPDATE SET tipo_envio='cliente' WHERE NULL) aunque el default ya lo cubre.
- [x] Índice `ix_etiquetas_envio_pedido` partial WHERE pedido_compra_id IS NOT NULL.
- [x] Downgrade: drop constraints + drop columns.

**Implementation notes:**
- El paso A original (DROP NOT NULL cliente_id) fue OMITIDO porque 0.4 determinó que la columna no existe. Ahorro: 1 migración.

---

### Task COMPRAS-1.8: **CONSOLIDADA en COMPRAS-1.7** ✅ (Batch 1A)
**Size:** (absorbida)
**Depends on:** — (ahora parte de 1.7)
**Artifacts:**
- `backend/app/models/etiqueta_envio.py` (MODIFIED — +4 columnas, +relationships, +check constraints)

**Acceptance criteria:**
- [x] Modelo `EtiquetaEnvio` actualizado con los 4 campos nuevos y relationship opcional a `PedidoCompra`, `Proveedor`, `ProveedorDireccion`.
- [x] CheckConstraints `ck_etiqueta_envio_tipo_envio` y `chk_etiqueta_envio_tipo_coherencia` agregados a `__table_args__`.
- [x] Imports refactorizados a orden alfabético.

**Implementation notes:**
- Consolidada con 1.7: al ser 1 paso la migración, no tiene sentido separar las tasks. El modelo cambia junto con la migración.

**Implementation notes:**
- REQ-LOG-001 + design §1.9.
- Verificar durante apply que el backfill procesa todas las filas existentes (count esperado = filas totales).

---

### Task COMPRAS-1.9: Migración `compras_007_imputaciones.py` (renumerada desde prompt) ✅ (Batch 1A)
**Size:** M
**Depends on:** fase 0 (no depende de pedidos/OP a nivel FK: IDs son polimórficos)
**Parallelizable with:** 1.10, 1.11, 1.12
**Artifacts:**
- `backend/alembic/versions/compras_007_imputaciones.py` (NEW — renumerada de 008 a 007 según prompt user)
- `backend/app/models/imputacion.py` (NEW)

**Acceptance criteria:**
- [x] Tabla `imputaciones` según design §1.4 (13 columnas, `origen_tipo`/`destino_tipo` VARCHAR abiertos).
- [x] CHECK `chk_imputacion_saldo_id` según design §1.4.
- [x] FK `proveedor_id` + self-reference `reimputada_desde_id`.
- [x] `es_reversal BOOLEAN NOT NULL DEFAULT FALSE`.
- [x] `moneda_imputada CHECK IN ('ARS','USD')`.
- [x] 4 índices según design §1.4: `ix_imputaciones_proveedor_created`, `ix_imputaciones_origen`, `ix_imputaciones_destino` (partial), `ix_imputaciones_reversal` (partial).
- [x] Modelo `Imputacion` (la constante `COMBOS_VALIDOS_V1` vivirá en el service F4 — COMPRAS-2.5).
- [ ] Downgrade OK. (pendiente — ejecuta usuario)

**Implementation notes:**
- REQ-IMP-001 + design §1.4 + D9 append-only.
- Las FKs no van a pedidos/OP porque `origen_id`/`destino_id` son polimórficos — eso es intencional.

---

### Task COMPRAS-1.10: Migración `compras_008_cc_proveedor_movimientos.py` (renumerada desde prompt) ✅ (Batch 1A)
**Size:** M
**Depends on:** fase 0
**Parallelizable with:** 1.9, 1.11, 1.12
**Artifacts:**
- `backend/alembic/versions/compras_008_cc_proveedor_movimientos.py` (NEW — renumerada de 009 a 008 según prompt user)
- `backend/app/models/cc_proveedor_movimiento.py` (NEW)

**Acceptance criteria:**
- [x] Tabla `cc_proveedor_movimientos` según design §1.5 con todos los campos y CHECKs (`tipo IN ('debe','haber','ajuste')`, `signo_ajuste IN (1,-1) solo si tipo='ajuste'`, `monto > 0`).
- [x] `chk_cc_ajuste_signo` enforcing consistency.
- [x] FKs a `proveedores`, `empresas`, `usuarios` (nullable en creado_por_id según design).
- [x] 4 índices: `ix_ccpm_proveedor_fecha`, `ix_ccpm_origen`, `ix_ccpm_empresa_proveedor`, `ix_ccpm_proveedor_moneda`.
- [x] Modelo `CCProveedorMovimiento`.
- [ ] Downgrade OK. (pendiente — ejecuta usuario)

**Implementation notes:**
- REQ-CC-001 + design §1.5. Append-only enforced a nivel servicio.

---

### Task COMPRAS-1.11: Migración `compras_010_cc_reconciliacion_log.py`
**Size:** S
**Depends on:** fase 0 (FK a alertas + notificaciones existentes)
**Parallelizable with:** 1.9, 1.10, 1.12
**Artifacts:**
- `backend/alembic/versions/compras_010_cc_reconciliacion_log.py` (NEW)
- `backend/app/models/cc_reconciliacion_log.py` (NEW)

**Acceptance criteria:**
- [ ] Tabla `cc_reconciliacion_log` según design §1.8.
- [ ] `uq_reconciliacion_corrida UNIQUE (fecha_corrida, proveedor_id, moneda)`.
- [ ] FKs `alerta_id → alertas ON DELETE SET NULL`, `notificacion_id → notificaciones ON DELETE SET NULL`.
- [ ] CHECK `moneda IN ('ARS','USD')`, `estado IN ('ok','divergencia')`.
- [ ] Índices: `ix_reconciliacion_estado_fecha`, `ix_reconciliacion_proveedor`.
- [ ] Modelo `CCReconciliacionLog` con relationships opcionales.
- [ ] Downgrade OK.

**Implementation notes:**
- REQ-CC-004 + design §1.8.
- Verificar que las tablas `alertas` y `notificaciones` existen antes de correr esta migración (preflight informal).

---

### Task COMPRAS-1.12: Vista SQL `v_facturas_compra_vigentes` (migration aparte)
**Size:** M
**Depends on:** 1.2 (tb_sale_document)
**Parallelizable with:** 1.9, 1.10, 1.11
**Artifacts:**
- `backend/alembic/versions/compras_011_vista_facturas_vigentes.py` (NEW)

**Acceptance criteria:**
- [ ] Migración crea/reemplaza la vista `v_facturas_compra_vigentes` EXACTAMENTE según design §4.1 (CTEs `anuladas`, `base`, `contrapartes`, heurística `sd_id > sd_id` para contraparte).
- [ ] Migración ejecuta `CREATE OR REPLACE VIEW` (idempotente).
- [ ] Downgrade: `DROP VIEW v_facturas_compra_vigentes`.
- [ ] Smoke test: `SELECT COUNT(*) FROM v_facturas_compra_vigentes` retorna un número `>= 0` sin errores sintácticos.
- [ ] Comentario SQL en la vista referenciando design §4.1 y obs #106 (fixture JUKEBOX).

**Implementation notes:**
- D4: vista normal en v1 (no materialized). Si p95 > 500ms en prod, escalar a materialized post-v1.
- RD3: la heurística "sd_id mayor = contraparte" es un convenio frágil — tests de regresión en F7 lo cubren.

---

### Task COMPRAS-1.13: Seed inicial — `caja_tipo_documentos` (`'orden_pago'` + `'orden_pago_anulada'`)
**Size:** S
**Depends on:** 1.5 (OP necesita que existan tipos antes de usarlos)
**Parallelizable with:** 1.14, 1.15, 1.16, 1.17, 1.18
**Artifacts:**
- `backend/alembic/versions/compras_012_seed_caja_tipo_documentos.py` (NEW)

**Acceptance criteria:**
- [x] Migration inserta idempotentemente (`INSERT ... ON CONFLICT (nombre) DO NOTHING`) en `caja_tipo_documentos`:
  - `{nombre: 'Orden de Pago', descripcion: 'Documento que respalda pago a proveedor', activo: true}`
  - `{nombre: 'Orden de Pago Anulada', descripcion: 'Documento que respalda anulación de una OP', activo: true}`
  - **CORRECCIÓN**: la tabla NO tiene columna `codigo` (verificado en `app/models/caja.py::CajaTipoDocumento`). Se usa `nombre` como identificador único.
- [ ] Verificación post-seed: `SELECT count(*) FROM caja_tipo_documentos WHERE nombre IN ('Orden de Pago','Orden de Pago Anulada')` → 2. (pendiente — ejecuta usuario)
- [x] Downgrade elimina SOLO estas 2 filas (DELETE WHERE nombre = ANY(...)).

**Implementation notes:**
- REQ-CAJ-003 + D19 (segundo tipo para anulaciones, preserva trazabilidad bidireccional).
- Verificar columna real de identificación (`codigo` o `nombre`) inspeccionando el modelo `CajaTipoDocumento` existente antes de la migración.

---

### Task COMPRAS-1.14: Seed — permisos críticos nuevos (sin asignación default)
**Size:** S
**Depends on:** fase 0 (tabla `permiso` existente)
**Parallelizable with:** 1.13, 1.15, 1.16, 1.17, 1.18
**Artifacts:**
- `backend/alembic/versions/compras_013_seed_permisos.py` (NEW)

**Acceptance criteria:**
- [x] Migration inserta 2 filas en tabla `permisos` (nombre real en plural) con `es_critico=true`:
  - `{codigo: 'administracion.aprobar_ordenes_compra', nombre: 'Aprobar órdenes de compra', descripcion: 'Aprobar o rechazar pedidos de compra', categoria: 'administracion_sector', orden: 170, es_critico: true}`
  - `{codigo: 'administracion.ejecutar_pagos', nombre: 'Ejecutar pagos', descripcion: 'Marcar una orden de pago como pagada (impacta Caja y CC proveedor)', categoria: 'administracion_sector', orden: 171, es_critico: true}`
  - **CORRECCIÓN**: schema real de `permisos` tiene `nombre` NOT NULL y `categoria` NOT NULL (verificado en `app/models/permiso.py`). NO tiene columna `grupo`. Se completó siguiendo el patrón del catálogo existente (categoría `administracion_sector`).
- [x] Migration NO inserta en `roles_permisos_base` ni `usuarios_permisos_override` — ningún rol ni usuario recibe los permisos por default (R8 del proposal).
- [x] Idempotente (`ON CONFLICT (codigo) DO NOTHING`).
- [x] Downgrade elimina los 2 permisos (cascade de `roles_permisos_base` y `usuarios_permisos_override` automático vía FK ON DELETE CASCADE).

**Implementation notes:**
- REQ-PED-005, REQ-OP-003. R8 del proposal: "Migración **NO** los asigna por default a ningún rol".
- Ver columnas reales de tabla `permiso` antes — ajustar nombres si difieren (ej. `codigo` vs `clave`).

---

### Task COMPRAS-1.15: Seed — `configuracion.compras.cc_reconciliacion_tolerancia_{ars,usd}` (tolerancia por moneda)
**Size:** S
**Depends on:** fase 0 (tabla `configuracion` existente)
**Parallelizable with:** 1.13, 1.14, 1.16, 1.17, 1.18
**Artifacts:**
- `backend/alembic/versions/compras_014_seed_configuracion_tolerancia.py` (NEW)

**Acceptance criteria:**
- [x] Migration inserta idempotentemente 2 filas en `configuracion`:
  - `{clave: 'compras.cc_reconciliacion_tolerancia_ars', valor: '100.00', tipo: 'decimal', descripcion: 'Tolerancia en ARS para diferencias entre libro mayor propio y snapshot CC. Por encima de este umbral se dispara alerta.'}`
  - `{clave: 'compras.cc_reconciliacion_tolerancia_usd', valor: '1.00', tipo: 'decimal', descripcion: 'Tolerancia en USD para diferencias entre libro mayor propio y snapshot CC.'}`
  - **Nota**: el schema real de `configuracion` no tiene `editable_desde_admin`; solo clave/valor/tipo/descripcion/fecha_modificacion (verificado en `app/models/configuracion.py`).
- [x] Idempotente (`ON CONFLICT (clave) DO NOTHING`).
- [x] Downgrade elimina ambas filas.

**Implementation notes:**
- **Cierre 2 del usuario**: tolerancia POR MONEDA, no una sola. Modifica design §8.2 (lectura de tolerancia será `compras.cc_reconciliacion_tolerancia_{moneda.lower()}`).
- Reemplaza la clave única original `compras.cc_reconciliacion_tolerancia` mencionada en D10 — queda cerrada con 2 claves separadas.

---

### Task COMPRAS-1.16: Schemas Pydantic base (v1)
**Size:** M
**Depends on:** 1.4, 1.5, 1.6, 1.9, 1.10, 1.11
**Parallelizable with:** 1.13, 1.14, 1.15, 1.17, 1.18
**Artifacts:**
- `backend/app/schemas/compras.py` (NEW)

**Acceptance criteria:**
- [ ] Schemas declarados: `PedidoCompraCreate`, `PedidoCompraUpdate`, `PedidoCompraResponse`, `PedidoCompraDetalle`, `PedidoCompraPaginated`.
- [ ] Schemas: `OrdenPagoCreate` (incluye `items[]` + `confirmar_duplicado: bool = False`), `OrdenPagoResponse`, `OrdenPagoDetalle`, `OrdenPagoPaginated`, `ImputacionItem`.
- [ ] Schemas: `ImputacionCreate`, `ImputacionResponse`, `ImputacionPaginated`.
- [ ] Schemas: `CCProveedorDetalle`, `CCAgrupadoPorPedido`, `CCReconciliacionLogResponse`.
- [ ] Schemas: `SaleDocumentResponse` (incluye `clasificacion` derivada).
- [ ] Schemas: `CompraEventoResponse`.
- [ ] Validaciones Pydantic: `moneda in {'ARS','USD'}`, `monto > 0`, `modo_imputacion in {'especifica','a_cuenta','mixta'}`.
- [ ] Type hints completos, `from __future__ import annotations` si hace falta.
- [ ] `ruff format --check` + `ruff check` pasan.

**Implementation notes:**
- Listado completo basado en design §9 (Endpoints REST). Agrupar en un solo archivo `compras.py` para v1; partir en v2 si crece.

---

### Task COMPRAS-1.17: Dependencia de auth `require_permiso` extendida (si hace falta)
**Size:** S
**Depends on:** 1.14 (permisos creados)
**Parallelizable with:** 1.13, 1.14, 1.15, 1.16, 1.18
**Artifacts:**
- `backend/app/core/deps.py` (MODIFIED — solo si require_permiso no existe como decorator reusable)

**Acceptance criteria:**
- [ ] Verificar si `app/core/deps.py` ya expone `require_permiso(codigo: str) -> Depends`. Si sí → skip este task (marcar N/A).
- [ ] Si no existe, crear helper que valide permiso via `PermisosContext`/ORM y levante HTTP 403.
- [ ] Test unitario en `test_deps_require_permiso.py` cubriendo: (a) usuario con permiso → pasa, (b) sin permiso → 403, (c) sin auth → 401.

**Implementation notes:**
- Pattern-check: el módulo probablemente ya lo tiene. Task marcado "S" con expected skip. Si se skippea, documentar N/A en state.yaml.

---

### Task COMPRAS-1.18: Documentación — schema relacional diagramado del módulo
**Size:** S
**Depends on:** 1.1..1.12 (todas las migraciones)
**Parallelizable with:** 1.13..1.17
**Artifacts:**
- `backend/docs/modulo_compras_schema.md` (NEW)

**Acceptance criteria:**
- [ ] Documento markdown con diagrama Mermaid de las 8 tablas nuevas + `etiquetas_envio` modificada.
- [ ] Relaciones FK documentadas (sólidas = física, punteadas = lógica como `ct_transaction_id`).
- [ ] Checklist de migraciones orden + nombre + dependencia breve.
- [ ] Link a design §1 y specs.

**Implementation notes:**
- No bloqueante para runtime, pero ayuda al onboarding. Tasks de F6/F7 lo referencian para armar UI.

---

## Fase 2 — Servicios base (clasificador, numeración, cc_proveedor)

> Servicios sin dependencias cruzadas entre ellos que sostienen todo el resto. Tests unitarios por servicio.

### Task COMPRAS-2.1: `sale_document_classifier.py` con 5 predicados
**Size:** M
**Depends on:** 1.2 (modelo SaleDocument)
**Parallelizable with:** 2.2, 2.3, 2.4
**Artifacts:**
- `backend/app/services/sale_document_classifier.py` (NEW)

**Acceptance criteria:**
- [ ] Enum `ClasificacionDocCompra` con 10 valores según design §2.1.
- [ ] 5 funciones públicas según design §2.1: `clasificar_documento_compra`, `afecta_cc_proveedor`, `signo_contable`, `es_anulacion`, `es_contraparte`.
- [ ] `clasificar_documento_compra` implementa EXACTAMENTE el orden de evaluación del design §2.1 (9 reglas secuenciales).
- [ ] `afecta_cc_proveedor` retorna False para `REMITO, PRESUPUESTO, ANULACION, CONTRAPARTE, IGNORAR`; True para el resto.
- [ ] `signo_contable` retorna `sd.sd_plusorminus` directo, sin lógica derivada.
- [ ] `es_contraparte` implementa heurística: `sd.hacc_group == sd_base.hacc_group AND sd.sd_plusorminus == -sd_base.sd_plusorminus AND sd.sd_id != sd_base.sd_id`.
- [ ] **NO HAY NÚMEROS MÁGICOS DE sd_id** en el código (verificado con `rg 'sd_id\s*==\s*[0-9]' backend/app/services/sale_document_classifier.py` → 0 matches).
- [ ] Única excepción: `hacc_group == 20101` para AJUSTE_SALDO (documentada con comentario).
- [ ] `ruff format --check` + `ruff check` pasan.

**Implementation notes:**
- REQ-SDC-004 + design §2.1.
- Los tests de regresión de los 43 sd_id viven en F7 (COMPRAS-7.1), no acá.

---

### Task COMPRAS-2.2: `numeracion_service.py` con SELECT FOR UPDATE + TZ Argentina
**Size:** M
**Depends on:** 1.1 (tabla contadores)
**Parallelizable with:** 2.1, 2.3, 2.4
**Artifacts:**
- `backend/app/services/numeracion_service.py` (NEW)

**Acceptance criteria:**
- [ ] Constante `PREFIX = {'pedido': 'P', 'orden_pago': 'OP'}`.
- [ ] Constante `TZ_ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")` (D18).
- [ ] Función `generar_siguiente_numero(session, *, tipo, empresa_id, anio=None) -> tuple[str, int]` según design §2.6.
- [ ] Si `tipo not in PREFIX` → `raise ValueError(f"Tipo de numeración no soportado en v1: {tipo}")`.
- [ ] Si `anio is None` → `datetime.now(TZ_ARGENTINA).year`.
- [ ] Ejecuta `SELECT ultimo_numero FROM numeracion_contadores WHERE ... FOR UPDATE` dentro de la transacción del caller (NO abre sesión nueva).
- [ ] Si la fila no existe → INSERT con `ultimo_numero=1`.
- [ ] Formato retornado: `f"{PREFIX[tipo]}-{empresa_id:02d}-{anio:04d}-{nuevo:05d}"`.
- [ ] Tests unitarios en `test_numeracion_service.py` cubriendo: (a) first use inserta fila, (b) subsequent use UPDATE +1, (c) formato exacto, (d) tipo inválido raise ValueError, (e) anio None toma TZ Argentina.

**Implementation notes:**
- REQ-NUM-001..006 + design §2.6 + D18.
- El test de concurrencia (10 threads simultáneos) está en F7 (COMPRAS-7.2) — no acá porque requiere fixtures multi-session.
- **Nota monitoring** (Cierre 1 del usuario): documentar en docstring que bajo volumen alto (>100 compras/día) se recomienda monitorear `pg_stat_activity`/`pg_locks` y considerar migración a `UPDATE ... RETURNING` en v2. No migrar en v1.

---

### Task COMPRAS-2.3: `cc_proveedor_service.py` — insertar_mov + calcular_saldo_por_moneda
**Size:** M
**Depends on:** 1.10 (tabla cc_proveedor_movimientos)
**Parallelizable with:** 2.1, 2.2, 2.4
**Artifacts:**
- `backend/app/services/cc_proveedor_service.py` (NEW)

**Acceptance criteria:**
- [ ] Función `insertar_mov(session, *, proveedor_id, empresa_id, fecha_movimiento, tipo, monto, moneda, origen_tipo, origen_id, descripcion=None, creado_por_id=None, signo_ajuste=None) -> CCProveedorMovimiento` según design §2.4.
- [ ] Resuelve `tipo_cambio_a_ars` consultando tabla `tipo_cambio` con patrón `fecha <= fecha_movimiento ORDER BY fecha DESC LIMIT 1`.
- [ ] Valida: si `tipo='ajuste'` entonces `signo_ajuste` es requerido ∈ `{1, -1}`.
- [ ] Función `calcular_saldo_por_moneda(session, *, proveedor_id, hasta_fecha=None) -> dict[str, Decimal]` con la query del design §2.4 (GROUP BY moneda).
- [ ] Función `aplicar_imputacion(session, *, imputacion_id) -> list[CCProveedorMovimiento]` (stub, la lógica completa la llena COMPRAS-4.3; acá solo la signature y un TODO claro).
- [ ] Tests unitarios en `test_cc_proveedor_service.py`: (a) insertar_mov normal, (b) insertar_mov ajuste sin signo raise, (c) calcular saldo proveedor mix ARS+USD, (d) calcular saldo proveedor sin movimientos retorna `{}`.
- [ ] `ruff format --check` + `ruff check` pasan.

**Implementation notes:**
- REQ-CC-001, REQ-CC-002, REQ-CC-006 + design §2.4.
- La función `reconciliar_diario` va en F3 (COMPRAS-3.6) para agrupar con el cron.

---

### Task COMPRAS-2.4: Validador de tolerancia por moneda
**Size:** S
**Depends on:** 1.15 (seeds configuracion)
**Parallelizable with:** 2.1, 2.2, 2.3
**Artifacts:**
- `backend/app/services/configuracion_service.py` (MODIFIED or NEW helper)
- `backend/app/services/cc_proveedor_service.py` (MODIFIED — agrega helper privado)

**Acceptance criteria:**
- [ ] Función `leer_tolerancia_reconciliacion(session, moneda: str) -> Decimal` que lee `configuracion.compras.cc_reconciliacion_tolerancia_{moneda.lower()}` (valida `moneda IN ('ARS','USD')`, si no raise ValueError).
- [ ] Defaults hardcoded como fallback: ARS=Decimal("100.00"), USD=Decimal("1.00") si la clave no existe (pero loggea WARN).
- [ ] Test unitario cubriendo: (a) ARS retorna valor de config, (b) USD retorna valor de config, (c) moneda inválida raise ValueError.

**Implementation notes:**
- **Cierre 2 del usuario**: tolerancia por moneda. Esta función es consumida por `reconciliar_diario` en COMPRAS-3.6.
- Reemplaza la lectura hardcoded `tolerancia_ars` del design §8.2 línea 1133.

---

### Task COMPRAS-2.5: `imputaciones_service.py` — esqueleto + COMBOS_VALIDOS_V1 + validación whitelist
**Size:** M
**Depends on:** 1.9 (tabla imputaciones)
**Parallelizable with:** 2.6, 2.7, 2.8
**Artifacts:**
- `backend/app/services/imputaciones_service.py` (NEW — esqueleto, la lógica de flujo va en F4)

**Acceptance criteria:**
- [ ] Constante `COMBOS_VALIDOS_V1: frozenset[tuple[str, str]]` con los 6 combos del design §1.4.
- [ ] Función `_validar_whitelist(origen_tipo, destino_tipo) -> None` que raise `HTTPException(400, 'Combinación origen/destino no soportada en v1')` si no matchea.
- [ ] Signatures declaradas (stubs con `raise NotImplementedError` si hace falta) para: `crear_imputacion`, `distribuir_fifo`, `desimputar`, `reimputar` según design §2.2.
- [ ] Tests unitarios en `test_imputaciones_service_whitelist.py` cubriendo los 6 combos válidos + al menos 3 combos inválidos.

**Implementation notes:**
- REQ-IMP-002 + design §2.2.
- La implementación completa de `crear_imputacion`/`distribuir_fifo`/`desimputar`/`reimputar` va en F4.

---

### Task COMPRAS-2.6: `ordenes_pago_service.py` — esqueleto + detectar_duplicado_erp
**Size:** M
**Depends on:** 1.5 (tabla ordenes_pago), 1.3 (constante ERP_SD_ID_ORDEN_PAGO)
**Parallelizable with:** 2.5, 2.7, 2.8
**Artifacts:**
- `backend/app/services/ordenes_pago_service.py` (NEW — esqueleto)

**Acceptance criteria:**
- [ ] Función `detectar_duplicado_erp(session, *, proveedor_id, numeros_factura) -> list[dict]` implementada COMPLETA (design §7.1).
- [ ] Query exacta del design §7.1: filtro `supp_id`, `sd_id=ERP_SD_ID_ORDEN_PAGO`, `ct_docnumber IN (...)`, `ct_date >= CURRENT_DATE - 7 days`, `NOT ct_iscancelled`.
- [ ] Usa constante `ERP_SD_ID_ORDEN_PAGO` de `compras_erp_constants.py` (NO literal `106` inline).
- [ ] Resuelve `supp_id` a partir de `proveedor_id` via el modelo `Proveedor` (FK/campo `supp_id` en modelo de proveedores ERP-synced, verificar nombre real).
- [ ] Signatures declaradas: `crear(...)`, `ejecutar_pago(...)`, `anular(...)` según design §2.3 (stubs).
- [ ] Tests unitarios en `test_ordenes_pago_detectar_duplicado.py`: (a) sin match retorna `[]`, (b) con match retorna lista con estructura esperada, (c) ct_iscancelled=True NO entra.

**Implementation notes:**
- REQ-OP-005 + design §7.1.
- La lógica de `ejecutar_pago` completa va en COMPRAS-4.6 (requiere integración con caja).

---

### Task COMPRAS-2.7: `erp_matching_service.py` — esqueleto
**Size:** S
**Depends on:** 1.4 (pedidos), 1.12 (vista)
**Parallelizable with:** 2.5, 2.6, 2.8
**Artifacts:**
- `backend/app/services/erp_matching_service.py` (NEW — esqueleto)

**Acceptance criteria:**
- [ ] Signatures declaradas según design §2.5: `match_forward(session, *, pedido_id) -> Optional[CommercialTransaction]` y `match_backward(session, *, cts_synced: list[int]) -> dict[str, int]`.
- [ ] Esqueleto de `match_backward` INCLUYE el pre-check `SELECT COUNT(*) FROM tb_sale_document > 0` y raise `RuntimeError("catálogo vacío")` si falla.
- [ ] Tests unitarios básicos: (a) match_backward con catálogo vacío raise, (b) match_backward con catálogo poblado no raise (aunque no procese nada).

**Implementation notes:**
- REQ-ERP-004 + design §2.5.
- Implementación completa en COMPRAS-4.8 + COMPRAS-3.5 (hook).

---

### Task COMPRAS-2.8: Helper `caja_service_adapter` (wrapper tipado opcional)
**Size:** S
**Depends on:** fase 0 (caja_service existe)
**Parallelizable with:** 2.5, 2.6, 2.7
**Artifacts:**
- `backend/app/services/caja_service.py` (UNCHANGED — solo inspección)
- `backend/app/services/_compras_caja_adapter.py` (NEW opcional)

**Acceptance criteria:**
- [ ] Inspeccionar `backend/app/services/caja_service.py` y VERIFICAR signatures reales (design §3.1): `registrar_movimiento(caja_id, fecha, detalle, tipo, monto, user_id, categoria_id, observaciones, origen)` y `crear_documento(tipo_documento_id, user_id, numero, entidad_tipo, entidad_id, movimiento_ids, ...)`.
- [ ] Si las signatures difieren del design, ACTUALIZAR design §3.1 antes de continuar (no cambiar caja_service).
- [ ] Opcional: crear adapter tipado `registrar_egreso_orden_pago(caja_id, op, user_id) -> CajaMovimiento` que encapsula los args y evita call sites dispersos. Si se crea, documentar.
- [ ] NO MODIFICAR `caja_service.py`.

**Implementation notes:**
- D8 + design §3.1. Principio: "no tocar cajas".
- Este task es una verificación defensiva para evitar sorpresas en COMPRAS-4.6.

---

## Fase 3 — Matching ERP

> **Refinement 2026-04-17** (Engram obs #121): se eliminaron las tasks COMPRAS-3.1 y COMPRAS-3.2 (script `sync_sale_documents.py` y endpoint `POST /sale-documents/sync`). `tb_sale_document` es seed estático Alembic (ver COMPRAS-1.2b), no hay sync. El endpoint `GET /sale-documents` (read-only) se cubre en F5 dentro del router existente, y `GET /sale-documents/faltantes` se mantiene en COMPRAS-3.4.

### Task COMPRAS-3.1: ~~Script `sync_sale_documents.py`~~ — **ELIMINADA**
**Status:** 🚫 ELIMINADA (refinement 2026-04-17, Engram obs #121)
**Razón:** `tb_sale_document` pasó a ser seed estático Alembic (ver COMPRAS-1.2b). No hay script de sync porque no hay sync. Tipos nuevos en el futuro → nueva Alembic migration.

---

### Task COMPRAS-3.2: ~~Endpoint `POST /sale-documents/sync`~~ — **ELIMINADA**
**Status:** 🚫 ELIMINADA (refinement 2026-04-17, Engram obs #121)
**Razón:** No hay sync, no hay endpoint "forzar sync". El listado read-only del catálogo (`GET /sale-documents`) y el endpoint `GET /sale-documents/faltantes` se cubren en COMPRAS-5.8 (router) + COMPRAS-3.4 (query faltantes).

---

### Task COMPRAS-3.3: Tests de la vista `v_facturas_compra_vigentes`
**Size:** M
**Depends on:** 1.12 (vista creada)
**Parallelizable with:** 3.4, 3.5
**Artifacts:**
- `backend/tests/integration/test_vista_facturas_vigentes.py` (NEW)
- `backend/tests/fixtures/jukebox_facturas.py` (NEW)

**Acceptance criteria:**
- [ ] Fixture `jukebox_facturas` inserta los 3 casos canónicos:
  - Factura sola vigente: `ct_docnumber=00400000`, `sd_id=101`.
  - Factura anulada: `ct_docnumber=00389000`, `sd_id=101` + `sd_id=151` (misma tupla).
  - Factura con contraparte: `ct_docnumber=00400001`, `sd_id=101` + `sd_id=161`.
- [ ] Test `test_factura_sola_vigente_aparece` → vista retorna 1 fila con sd_id=101.
- [ ] Test `test_factura_anulada_no_aparece` → vista retorna 0 filas para esa tupla.
- [ ] Test `test_factura_con_contraparte_aparece_solo_base` → vista retorna 1 fila con sd_id=101 (NO 161).
- [ ] Test `test_multiple_facturas_distintas_tuplas` con 5 facturas distintas → vista retorna las 5.
- [ ] `pytest backend/tests/integration/test_vista_facturas_vigentes.py -v` pasa.

**Implementation notes:**
- REQ-ERP-007 + design §4.1 + RD3.
- Los fixtures también se usan por COMPRAS-3.5 y F7.

---

### Task COMPRAS-3.4: Endpoint `GET /sale-documents/faltantes`
**Size:** S
**Depends on:** 1.2 (tabla creada), 1.2b (seed con 43 filas)
**Parallelizable with:** 3.3, 3.5
**Artifacts:**
- `backend/app/routers/administracion_compras_sale_documents.py` (NEW — ahora este router se crea acá, ya no en 3.2 eliminada)

**Acceptance criteria:**
- [ ] Query: `SELECT sd_id, count(*), min(ct_date) FROM tb_commercial_transactions WHERE sd_id NOT IN (SELECT sd_id FROM tb_sale_document) AND ct_date >= CURRENT_DATE - 30 GROUP BY sd_id`.
- [ ] Response: `list[{sd_id: int, count: int, primera_aparicion: date}]`.
- [ ] Test de integración con fixture de ct_ids faltantes.

**Implementation notes:**
- REQ-SDC-007.

---

### Task COMPRAS-3.5: Hook inline en `sync_commercial_transactions_guid.py`
**Size:** M
**Depends on:** 2.7 (erp_matching_service esqueleto), 1.12 (vista)
**Parallelizable with:** 3.3, 3.4
**Artifacts:**
- `backend/app/scripts/sync_commercial_transactions_guid.py` (MODIFIED)
- `backend/app/services/erp_matching_service.py` (MODIFIED — `match_backward` completa)

**Acceptance criteria:**
- [ ] Se agrega al final del script (antes del exit) el bloque de design §5 (try/except con pre-check catálogo).
- [ ] Si catálogo vacío → log ERROR + `notificacion_service.crear_notificacion(...)` + `session.commit()` + NO raise.
- [ ] Si catálogo OK → `match_backward(session, cts_synced=cts_synced)` + log del resumen.
- [ ] Except catchea TODA excepción del hook, loggea, `session.rollback()`, pero NO hace fallar el cron (cron termina `exit 0`).
- [ ] `match_backward` implementa el filtrado via `v_facturas_compra_vigentes` y setea `pedidos_compra.ct_transaction_id` + inserta evento `matcheado_con_erp` en `compras_eventos`.
- [ ] `match_forward` implementado análogo para pedido → factura.
- [ ] Tests de integración en `test_erp_matching_hook.py`: (a) catálogo vacío → aborta con alert, (b) catálogo poblado + cts con factura nueva → pedido matcheado.

**Implementation notes:**
- REQ-ERP-005, REQ-ERP-006 + design §5.
- Usar `resolver_comp_bra(empresa_id)` para convertir pedido.empresa_id a (comp_id, bra_id) en el filtro de matching.
- El mapeo proveedor_id → supp_id es el típico (campo `supp_id` en modelo `Proveedor` si ya está sync-ed; verificar).

---

### Task COMPRAS-3.6: Cron standalone `reconciliar_cc_proveedor.py`
**Size:** L
**Depends on:** 2.3 (cc_proveedor_service), 2.4 (validador tolerancia por moneda), 1.11 (cc_reconciliacion_log)
**Parallelizable with:** 3.3, 3.4
**Artifacts:**
- `backend/app/scripts/reconciliar_cc_proveedor.py` (NEW)
- `backend/app/services/cc_proveedor_service.py` (MODIFIED — agrega función `reconciliar_diario`)

**Acceptance criteria:**
- [ ] Función `reconciliar_diario(session, *, fecha_corrida) -> dict` en `cc_proveedor_service.py` según design §2.4 + §8.2.
- [ ] **Tolerancia por moneda** (Cierre 2 del usuario): lee `leer_tolerancia_reconciliacion(session, moneda)` (COMPRAS-2.4) — NO hay una sola tolerancia ARS.
- [ ] Itera proveedores activos con movimientos últimos 365 días, calcula saldo por moneda, compara vs `cuentas_corrientes_proveedores` (si existe), persiste fila en `cc_reconciliacion_log` con `tolerancia_aplicada = <tolerancia leída por moneda>`.
- [ ] Si >= 1 divergencia → crea 1 Alerta (banner) + N Notificaciones (una por divergencia) y setea `log.alerta_id`/`notificacion_id`.
- [ ] Retorna `{"proveedores_procesados": N, "divergencias": M, "alertas_creadas": 0|1, "notificaciones_creadas": M}`.
- [ ] Script `reconciliar_cc_proveedor.py` ejecutable vía `python -m backend.app.scripts.reconciliar_cc_proveedor [--fecha YYYY-MM-DD]`. Default: `date.today()`.
- [ ] Cron: `03:00 AM` diario (D5).
- [ ] Pre-check RD6: si `MAX(ct_date) < CURRENT_DATE - 1` → log WARN "sync ERP atrasado" pero CONTINUAR (no abortar).
- [ ] Tests unitarios: (a) sin divergencias → no crea alerta, (b) 2 divergencias ARS → 1 alerta + 2 notificaciones, (c) lee tolerancia correcta por moneda (ARS distinto que USD).

**Implementation notes:**
- REQ-CC-004 + D5 + D6 + D10 + RD6 + Cierre 2.
- No hook post-sync; cron standalone (D5).

---

## Fase 4 — Servicios de flujo (imputaciones, OP, matching completo, state machine de pedidos)

### Task COMPRAS-4.1: `pedidos_service.py` — alta + state machine ✅ (Fase 4)
**Size:** L
**Depends on:** 1.4, 1.6, 2.2 (numeracion)
**Parallelizable with:** 4.2, 4.3
**Artifacts:**
- `backend/app/services/pedidos_service.py` (NEW)

**Acceptance criteria:**
- [x] Función `crear_pedido(session, *, proveedor_id, empresa_id, moneda, monto, creado_por_id, ...) -> PedidoCompra`.
- [x] Llama `numeracion_service.generar_siguiente_numero(session, tipo='pedido', empresa_id=empresa_id)` dentro de la misma transacción.
- [x] Inserta evento `compras_eventos` con `entidad_tipo='pedido_compra'`, `tipo='creado'`.
- [x] Función `transicionar(session, *, pedido_id, accion, user_id, ...) -> PedidoCompra` que valida la matriz de transiciones del design §6.
- [x] Transición inválida → `HTTPException(400, f"Transición no permitida: estado='{origen}' accion='{accion}'")`.
- [x] Función `editar_pedido(session, *, pedido_id, user_id, **campos) -> PedidoCompra`:
  - En estado `borrador` → todos los campos editables.
  - En `aprobado`/`pagado_parcial` → solo `numero_factura` editable; otros → HTTP 409.
  - Cada edición inserta evento `tipo='editado'` con payload del diff.
- [x] Cuando se edita `numero_factura` en aprobado/pagado_parcial → invoca `erp_matching_service.match_forward(session, pedido_compra_id=pedido.id)`.
- [x] Transiciones automáticas `aprobado → pagado_parcial / pagado` disparadas desde `aplicar_imputacion_a_pedido` (COMPRAS-4.9 absorbido acá).
- [x] Si `estado → aprobado` → inserta movimiento `debe` en `cc_proveedor_movimientos`.
- [x] Si `aprobado → cancelado` → inserta movimiento `ajuste` reverso (signo_ajuste=-1) en CC.
- [x] Tests unitarios en `test_pedidos_service.py` cubriendo 16 casos (creación, edición por estado, transiciones válidas/inválidas, side effects CC, auto-match forward, transiciones automáticas).

**Implementation notes:**
- REQ-PED-001..006 + design §6.
- State machine completa; cada transición → evento compras_eventos.

---

### Task COMPRAS-4.2: Generación de etiqueta de retiro — `etiqueta_retiro_service.py` ✅ (Fase 4)
**Size:** M
**Depends on:** 1.8 (etiquetas_envio modificada), 4.1 (pedidos_service)
**Parallelizable with:** 4.1, 4.3
**Artifacts:**
- `backend/app/services/etiqueta_retiro_service.py` (NEW)

**Acceptance criteria:**
- [x] Función `generar_etiqueta_retiro(session, *, pedido_id, proveedor_direccion_id=None, user_id) -> EtiquetaEnvio`.
- [x] Valida `pedido.requiere_envio=true` (HTTP 400).
- [x] Si ya existe etiqueta con `pedido_compra_id=pedido_id` → HTTP 409 (D16).
- [x] Si `proveedor_direccion_id` omitido → elige etiqueta con `%retiro%` (case-insensitive) o primera activa (D17 adaptado: modelo actual no tiene `es_principal`). 400 si no hay direcciones activas.
- [x] Valida `proveedor_direccion.proveedor_id == pedido.proveedor_id` (HTTP 400).
- [x] Inserta `etiquetas_envio` con `tipo_envio='retiro_proveedor'`, `proveedor_id`, `proveedor_direccion_id`, `pedido_compra_id`, `es_manual=true`, shipping_id generado.
- [x] Inserta evento en `compras_eventos` con `tipo='etiqueta_envio_generada'`.
- [x] 10 tests unitarios (happy path con/sin dirección, evento, 400/409, pedido inexistente, fecha=hoy, persistencia).

**Implementation notes:**
- REQ-LOG-002, REQ-LOG-004 + D16, D17.

---

### Task COMPRAS-4.3: `imputaciones_service.py` — crear + aplicar CC (completo) ✅ (Fase 4)
**Size:** L
**Depends on:** 2.5 (esqueleto), 2.3 (cc_proveedor_service)
**Parallelizable with:** 4.1, 4.2
**Artifacts:**
- `backend/app/services/imputaciones_service.py` (MODIFIED — +distribuir_fifo, +desimputar, +reimputar)
- `backend/app/services/cc_proveedor_service.py` (MODIFIED — +aplicar_imputacion + _resolver_empresa_id_para_imputacion)

**Acceptance criteria:**
- [x] `crear_imputacion(...)` ya existía en F2; el caller (ejecutar_pago / distribuir_fifo) orquesta la invocación a `cc_proveedor_service.aplicar_imputacion`.
- [x] `aplicar_imputacion(session, *, imputacion_id) -> list[CCProveedorMovimiento]`:
  - Imputación normal (`es_reversal=False`) → inserta 1 `haber` con `origen_tipo='imputacion'`.
  - Imputación reversal (`es_reversal=True`) → inserta 1 `debe` con `origen_tipo='reimputacion'`.
  - Resuelve empresa_id vía destino (pedido_compra) u origen (orden_pago). Fallback empresa_id=1 con WARNING.
- [x] Tests unitarios en `test_cc_proveedor_service.py` (+3 tests: normal=haber, reversal=debe, saldo final correcto tras flujo completo debe→haber→reversal).

**Implementation notes:**
- REQ-IMP-001..006 + D3 + D9.

---

### Task COMPRAS-4.4: `imputaciones_service.distribuir_fifo` ✅ (Fase 4)
**Size:** M
**Depends on:** 4.3
**Parallelizable with:** 4.5, 4.7
**Artifacts:**
- `backend/app/services/imputaciones_service.py` (MODIFIED)

**Acceptance criteria:**
- [x] Función `distribuir_fifo(session, *, orden_pago_id, user_id) -> list[Imputacion]` según design §2.2.
- [x] Query lista pedidos pendientes (aprobado/pagado_parcial, misma moneda, mismo proveedor) ordenados por `created_at ASC`.
- [x] Aplica remanente de OP a cada deuda en orden; crea imputaciones + dispara `aplicar_imputacion` en CC.
- [x] Si sobra → imputación `(orden_pago, saldo, remanente)`.
- [ ] TODO F4+: distribución sobre facturas ERP vigentes (requiere columna moneda en la vista — RD6).
- [x] Tests unitarios en `test_imputaciones_service.py` (+2 tests: remanente a saldo puro, pedido pendiente + saldo mixto).

**Implementation notes:**
- REQ-IMP-004 + design §2.2.

---

### Task COMPRAS-4.5: `imputaciones_service.desimputar` + `reimputar` (append-only) ✅ (Fase 4)
**Size:** M
**Depends on:** 4.3
**Parallelizable with:** 4.4, 4.7
**Artifacts:**
- `backend/app/services/imputaciones_service.py` (MODIFIED)

**Acceptance criteria:**
- [x] `desimputar(session, *, imputacion_id, user_id, motivo=None) -> Imputacion`:
  - Lee imputación original; valida `es_reversal=False` sino HTTP 400.
  - Inserta fila nueva con `es_reversal=True`, mismo destino/monto/moneda, `reimputada_desde_id=imputacion_original.id`.
  - Invoca `cc_proveedor_service.aplicar_imputacion` para el reversal (genera `debe` en CC).
- [x] `reimputar(session, *, imputacion_id, nuevo_destino_tipo, nuevo_destino_id, user_id) -> tuple[Imputacion, Imputacion]`:
  - Valida `imputacion_original.reimputada_desde_id IS NULL` + no es_reversal + no existe ya otra fila apuntando como reimputada_desde_id (D13).
  - Valida nuevo combo ∈ COMBOS_VALIDOS_V1 + saldo_destino_id.
  - Inserta 2 filas: reversal de la original + nueva con destino nuevo. Dispara CC por ambas.
- [x] Tests unitarios (+5 tests): desimputar happy, desimputar de reversal falla 400, reimputar 2 filas OK, reimputar ya reimputada 400 (D13), reimputar combo inválido 400.

**Implementation notes:**
- REQ-IMP-005 + D9 + D13.

---

### Task COMPRAS-4.6: `ordenes_pago_service.ejecutar_pago` — transacción atómica con cajas + CC ✅ (Fase 4)
**Size:** XL
**Depends on:** 2.6 (esqueleto), 2.8 (adapter cajas), 4.3 (imputaciones_service.crear)
**Parallelizable with:** 4.4, 4.5 (con cuidado)
**Artifacts:**
- `backend/app/services/ordenes_pago_service.py` (MODIFIED — `ejecutar_pago` completa)

**Acceptance criteria:**
- [x] `ejecutar_pago(session, *, orden_pago_id, caja_id, fecha_pago_real, user_id) -> OrdenPago` según design §2.3.
- [x] Transacción única con los 9 pasos:
  1. `SELECT FOR UPDATE` de OP; valida `estado='pendiente'` sino 400.
  2. Valida `caja.moneda == OP.moneda` → sino HTTP 422 `OP_CAJA_MONEDA_MISMATCH`.
  3. Valida `OP.empresa_id == caja.empresa_id` → sino HTTP 409.
  4. Invoca `CajaService.registrar_movimiento(tipo='egreso', origen='orden_pago', ...)`.
  5. Invoca `CajaService.crear_documento(tipo='Orden de Pago', entidad='orden_pago', movimiento_ids=[mov.id], ...)`.
  6. Por cada item de la OP → `imputaciones_service.crear_imputacion` + `cc_proveedor_service.aplicar_imputacion`.
  7. Si `modo='mixta'` y sobra remanente → imputación `(orden_pago, saldo, remanente)`. Si `a_cuenta` → toda la OP a saldo.
  8. Set `op.caja_movimiento_id`, `op.caja_documento_id`, `op.estado='pagado'`, `paid_at`, `pagado_por_id`, `fecha_pago_real`.
  9. Inserta evento `tipo='op_pagada'` en `compras_eventos`.
- [x] Propagación: por cada pedido afectado → `pedidos_service.aplicar_imputacion_a_pedido` (transición automática aprobado → pagado_parcial/pagado).
- [x] Los items se persisten como evento auxiliar `items_registrados` al crear la OP (no hay tabla orden_pago_items en v1).
- [x] Tests de integración en `test_ordenes_pago_service.py`: 5 tests de `ejecutar_pago` (happy path completo, cross-moneda 422, op ya pagada 400, mixta con remanente, a_cuenta todo a saldo).

**Implementation notes:**
- REQ-OP-004 + D7 + D8 + design §2.3 + §3.1.
- Task crítico: si rompe, se rompe el módulo entero. Tests estrictos.

---

### Task COMPRAS-4.7: `ordenes_pago_service.crear` con detección duplicado + confirmar_duplicado ✅ (Fase 4)
**Size:** M
**Depends on:** 2.6 (esqueleto + detectar_duplicado_erp)
**Parallelizable with:** 4.4, 4.5, 4.6
**Artifacts:**
- `backend/app/services/ordenes_pago_service.py` (MODIFIED — `crear` + `detectar_duplicado_erp` + `anular`)

**Acceptance criteria:**
- [x] `crear(session, *, proveedor_id, empresa_id, moneda, monto_total, modo_imputacion, items, observaciones, creado_por_id, confirmar_duplicado=False) -> OrdenPago`.
- [x] Valida `monto_total > 0`.
- [x] Valida constraints por modo: especifica (sum == total), mixta (sum < total), a_cuenta (items vacío).
- [x] Valida TODOS los items cumplen `(orden_pago, destino) ∈ COMBOS_VALIDOS_V1` + saldo_id.
- [x] `detectar_duplicado_erp` con query contra `tb_commercial_transactions` usando `ERP_SD_ID_ORDEN_PAGO=106`. Graceful fallback si tabla inexistente (tests).
- [x] 409 con payload `POSIBLE_DUPLICADO_OP_ERP` si duplicado sin confirmar; evento `op_creada_con_duplicado_confirmado` si flag=True.
- [x] Genera número via `numeracion_service` (tipo='orden_pago').
- [x] **NO** crea imputaciones todavía (ver ejecutar_pago).
- [x] Tests unitarios (8 tests de TestCrear + 5 de TestDetectarDuplicadoErp): especifica OK, suma distinta 400, a_cuenta items vacío OK, a_cuenta con items 400, mixta OK, monto 0 400, combo inválido 400, sin supp_id retorna [], duplicado con/sin flag, etc.

### Task COMPRAS-4.8: Integración `match_forward` en edición de pedido ✅ (Fase 4)
**Size:** S (absorbido en COMPRAS-4.1)
**Depends on:** 4.1
**Artifacts:**
- `backend/app/services/pedidos_service.py` (MODIFIED — `editar_pedido` invoca `erp_matching_service.match_forward`)

**Acceptance criteria:**
- [x] Cuando `editar_pedido` cambia `numero_factura` con valor no-nulo → invoca `erp_matching_service.match_forward(session, pedido_compra_id=..., usuario_id=user_id)`.
- [x] Falla del match_forward NO rollbackea la edición (try/except con log.exception).
- [x] Test: `test_editar_numero_factura_invoca_match_forward` valida la invocación con mock.

**Implementation notes:**
- REQ-OP-001, REQ-OP-002, REQ-OP-005 + design §7.2.

---

### Task COMPRAS-4.8-anular: `ordenes_pago_service.anular` — reverso completo ✅ (Fase 4, agrupada con 4.5)
**Size:** L
**Depends on:** 4.6, 4.5 (desimputar)
**Parallelizable with:** 4.7
**Artifacts:**
- `backend/app/services/ordenes_pago_service.py` (MODIFIED — `anular` completa)

**Acceptance criteria:**
- [x] `anular(session, *, orden_pago_id, motivo, user_id) -> OrdenPago`.
- [x] Valida OP en `estado='pagado'` sino 400. Motivo obligatorio (400 si vacío).
- [x] Crea `CajaMovimiento` ingreso del mismo monto en la misma caja (REQ-CAJ-005).
- [x] Crea `CajaDocumento` con `tipo='Orden de Pago Anulada'` (D19), `entidad_tipo='orden_pago'`, `entidad_id=OP.id`.
- [x] Por cada imputación viva de la OP (`es_reversal=False` AND sin reversal previo apuntando a ella) → invoca `imputaciones_service.desimputar`.
- [x] Re-transiciona pedidos afectados via `pedidos_service.revertir_transicion_por_anulacion_op`: vuelven a `aprobado` (o `pagado_parcial` si otras OPs los cubrían parcialmente).
- [x] Set `OP.estado='anulado'` + evento `tipo='op_anulada'`.
- [x] Tests (3 tests): anular OP pagada happy (caja ingreso + reversals + pedido vuelve a aprobado + evento), anular OP no pagada 400, anular sin motivo 400.

**Implementation notes:**
- REQ-OP-006 + REQ-CAJ-005 + D19.

---

### Task COMPRAS-4.9: Helper `calcular_saldo_pendiente_pedido` + trigger automático de estados ✅ (Fase 4, absorbida en 4.1)
**Size:** M
**Depends on:** 4.1, 4.3
**Parallelizable with:** 4.7, 4.8
**Artifacts:**
- `backend/app/services/pedidos_service.py` (MODIFIED)

**Acceptance criteria:**
- [x] Función `calcular_saldo_pendiente_pedido(session, pedido_id) -> Decimal`:
  - `saldo = monto - (sum(imputaciones es_reversal=False) - sum(imputaciones es_reversal=True))`
  - Los reversals compensan correctamente al anular OPs / desimputar.
- [x] `aplicar_imputacion_a_pedido(session, *, pedido_id, monto_imputado)` maneja transiciones:
  - `aprobado` + saldo > 0 → `pagado_parcial` + evento `pago_parcial_aplicado`.
  - `aprobado`/`pagado_parcial` + saldo == 0 → `pagado` + evento `pago_completado`.
  - `pagado` + saldo > 0 (por reversal) → `pagado_parcial` + evento `reverso_cancelacion`.
- [x] `revertir_transicion_por_anulacion_op` invocado desde `ordenes_pago_service.anular`: pedidos vuelven a `aprobado` o `pagado_parcial` según saldo tras reversal.
- [x] Tests en `test_pedidos_service.py` (2 tests `TestAplicarImputacionAPedido`) + tests indirectos en `test_ordenes_pago_service.py` (anular → pedido vuelve a aprobado).

**Implementation notes:**
- REQ-PED-002 (transiciones automáticas).

---

## Fase 5 — Endpoints REST (routers)

> Todos los routers viven bajo `backend/app/routers/` y usan prefix `/api/administracion/compras`. Se montan en `main.py`.

### Task COMPRAS-5.1: Router `pedidos.py` — listado + detalle + CRUD borrador
**Size:** M
**Depends on:** 4.1, 1.16
**Parallelizable with:** 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8
**Artifacts:**
- `backend/app/routers/administracion_compras_pedidos.py` (NEW)
- `backend/app/main.py` (MODIFIED — registrar router)

**Acceptance criteria:**
- [ ] Endpoints según design §9.1:
  - `GET /pedidos` (paginado, filtros estado/proveedor/empresa/fecha) con `ver_ordenes_compra`.
  - `GET /pedidos/{id}` con detalle + eventos + imputaciones + ct asociada.
  - `POST /pedidos` con `gestionar_ordenes_compra`.
  - `PUT /pedidos/{id}` (solo borrador, con excepción de numero_factura en aprobado — REQ-PED-006).
- [ ] Response models del Pydantic de COMPRAS-1.16.
- [ ] Tests de router cubriendo: (a) 401 sin auth, (b) 403 sin permiso, (c) 404 inexistente, (d) 409 editar aprobado, (e) happy path.

**Implementation notes:**
- REQ-PED-001, REQ-PED-006 + design §9.1.

---

### Task COMPRAS-5.2: Router pedidos — transiciones (enviar/aprobar/rechazar/reabrir/cancelar)
**Size:** M
**Depends on:** 4.1, 5.1
**Parallelizable with:** 5.1, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8
**Artifacts:**
- `backend/app/routers/administracion_compras_pedidos.py` (MODIFIED)

**Acceptance criteria:**
- [ ] 5 endpoints transicionales según design §9.1:
  - `POST /pedidos/{id}/enviar-aprobacion` con `gestionar_ordenes_compra`.
  - `POST /pedidos/{id}/aprobar` con **`aprobar_ordenes_compra`** (crítico). Body: `{fecha_pago_estimada?: date}`.
  - `POST /pedidos/{id}/rechazar` con `aprobar_ordenes_compra`. Body: `{accion: 'devolver_a_borrador'|'cancelar_definitivo', motivo: str}`. Si `accion` falta → 400.
  - `POST /pedidos/{id}/reabrir` con `gestionar_ordenes_compra`.
  - `POST /pedidos/{id}/cancelar` con `gestionar_ordenes_compra` o `aprobar_ordenes_compra` según estado. Body: `{motivo: str}`.
- [ ] Transiciones inválidas → 400 con `"Transición no permitida: {origen} -> {destino}"`.
- [ ] Tests cubriendo las 5 transiciones + rechazos de permiso + body mal formado.

**Implementation notes:**
- REQ-PED-002, REQ-PED-003 + design §6 matriz de transiciones.

---

### Task COMPRAS-5.3: Router pedidos — generar-etiqueta-envio + eventos
**Size:** S
**Depends on:** 4.2 (etiqueta_retiro_service), 5.1
**Parallelizable with:** 5.1, 5.2, 5.4, 5.5, 5.6, 5.7, 5.8
**Artifacts:**
- `backend/app/routers/administracion_compras_pedidos.py` (MODIFIED)

**Acceptance criteria:**
- [ ] `POST /pedidos/{id}/generar-etiqueta-envio` con body `{proveedor_direccion_id?: int}`. Response: `EtiquetaEnvioResponse` (del schema existente de TabEnviosFlex o nuevo DTO).
- [ ] `GET /pedidos/{id}/eventos` retorna `list[CompraEventoResponse]` filtrado por `entidad_tipo='pedido_compra'`, ordenado `created_at DESC`.
- [ ] Tests cubriendo: (a) pedido con requiere_envio=false → 400, (b) ya existe → 409, (c) happy path.

**Implementation notes:**
- REQ-LOG-002, REQ-PED-004 + design §9.1.

---

### Task COMPRAS-5.4: Router `ordenes_pago.py` — listado + detalle + CREATE con 409
**Size:** M
**Depends on:** 4.7
**Parallelizable with:** 5.1, 5.2, 5.3, 5.5, 5.6, 5.7, 5.8
**Artifacts:**
- `backend/app/routers/administracion_compras_ordenes_pago.py` (NEW)

**Acceptance criteria:**
- [ ] Endpoints según design §9.2:
  - `GET /ordenes-pago` paginado con filtros.
  - `GET /ordenes-pago/{id}` detalle con imputaciones.
  - `POST /ordenes-pago` con body `OrdenPagoCreate` (incluye `items[]`, `confirmar_duplicado: bool = False`). Response 201.
- [ ] El endpoint POST captura la HTTPException(409) de `ordenes_pago_service.crear` y la pasa tal cual con payload `POSIBLE_DUPLICADO_OP_ERP` según design §7.2.
- [ ] Permiso: `gestionar_ordenes_compra` para crear.
- [ ] Tests: (a) create happy → 201, (b) duplicado sin flag → 409 con payload completo, (c) duplicado con flag → 201 + evento registrado, (d) combo inválido → 400, (e) sin permiso → 403.

**Implementation notes:**
- REQ-OP-001, REQ-OP-002, REQ-OP-005 + design §9.2 + §7.

---

### Task COMPRAS-5.5: Router ordenes_pago — pagar + anular + distribuir-automatico
**Size:** M
**Depends on:** 4.4, 4.6, 4.8, 5.4
**Parallelizable with:** 5.1, 5.2, 5.3, 5.6, 5.7, 5.8
**Artifacts:**
- `backend/app/routers/administracion_compras_ordenes_pago.py` (MODIFIED)

**Acceptance criteria:**
- [ ] `POST /ordenes-pago/{id}/pagar` con `ejecutar_pagos` (crítico). Body `{caja_id: int, fecha_pago_real: date}`. Captura `OP_CAJA_MONEDA_MISMATCH` → 422 con payload exacto del design §3.2.
- [ ] `POST /ordenes-pago/{id}/anular` con `ejecutar_pagos`. Body `{motivo: str}`.
- [ ] `POST /ordenes-pago/{id}/distribuir-automatico` con `ejecutar_pagos`. Response: `list[ImputacionResponse]`.
- [ ] Tests cubriendo: (a) pagar happy, (b) pagar sin permiso → 403, (c) pagar caja moneda distinta → 422, (d) anular happy, (e) distribuir FIFO → imputaciones creadas.

**Implementation notes:**
- REQ-OP-003, REQ-OP-004, REQ-OP-006 + REQ-IMP-004 + design §9.2.

---

### Task COMPRAS-5.6: Router `imputaciones.py` — GET + desimputar + reimputar
**Size:** M
**Depends on:** 4.5
**Parallelizable with:** 5.1..5.5, 5.7, 5.8
**Artifacts:**
- `backend/app/routers/administracion_compras_imputaciones.py` (NEW)

**Acceptance criteria:**
- [ ] `GET /imputaciones` paginado con filtros (proveedor_id, origen_tipo, destino_tipo, fecha).
- [ ] `POST /imputaciones/{id}/desimputar` body `{motivo: str}`. Response: la imputación compensatoria creada.
- [ ] `POST /imputaciones/{id}/reimputar` body `{destino_tipo, destino_id?}`. Response: `tuple[Imputacion, Imputacion]` (reversal + nueva).
- [ ] Permisos: GET con `ver_ordenes_compra`, desimputar/reimputar con `ejecutar_pagos`.
- [ ] Tests cubriendo: reimputar happy, reimputar en cadena → 400, reimputar combo inválido → 400, desimputar un reversal → 400.

**Implementation notes:**
- REQ-IMP-005 + design §9.3.

---

### Task COMPRAS-5.7: Router `cc_proveedor.py` — detalle + por-pedido + reconciliación
**Size:** M
**Depends on:** 2.3, 3.6
**Parallelizable with:** 5.1..5.6, 5.8
**Artifacts:**
- `backend/app/routers/administracion_compras_cc_proveedor.py` (NEW)

**Acceptance criteria:**
- [ ] `GET /cc-proveedor/{proveedor_id}` con response del design §9.4 (saldos por moneda + movimientos + consolidado estimado con disclaimer).
- [ ] `GET /cc-proveedor/{proveedor_id}/por-pedido` → agrupación por pedido.
- [ ] `GET /reconciliacion` paginado con filtros fecha/estado.
- [ ] `POST /reconciliacion/forzar` body `{fecha?: date}` invoca `cc_proveedor_service.reconciliar_diario(session, fecha_corrida=fecha or today)`. Permiso admin.
- [ ] `GET /reconciliacion/metricas` retorna `{dias_consecutivos_sin_divergencia: int, cobertura_porcentaje: float, criterio_deprecacion: dict}` (REQ-CC-005).
- [ ] Tests cubriendo los 5 endpoints.

**Implementation notes:**
- REQ-CC-002, REQ-CC-003, REQ-CC-004, REQ-CC-005 + design §9.4.

---

### Task COMPRAS-5.8: Router sale-documents (completar) + registro main.py
**Size:** S
**Depends on:** 3.2, 3.4
**Parallelizable with:** 5.1..5.7
**Artifacts:**
- `backend/app/routers/administracion_compras_sale_documents.py` (MODIFIED)
- `backend/app/main.py` (MODIFIED)

**Acceptance criteria:**
- [ ] Registra los 4 routers en `main.py`:
  - `administracion_compras_pedidos.router`
  - `administracion_compras_ordenes_pago.router`
  - `administracion_compras_imputaciones.router`
  - `administracion_compras_cc_proveedor.router`
  - `administracion_compras_sale_documents.router`
- [ ] Todos con prefix `/api/administracion/compras` y tag OpenAPI `compras`.
- [ ] Endpoints `/sale-documents`, `/sale-documents/sync`, `/sale-documents/faltantes` presentes y funcionales.
- [ ] Smoke test: `GET /docs` muestra los nuevos endpoints agrupados bajo `compras`.

**Implementation notes:**
- REQ-SDC-003, REQ-SDC-007 + design §9.5.

---

### Task COMPRAS-5.9: Router tests + OpenAPI snapshot
**Size:** M
**Depends on:** 5.1..5.8
**Parallelizable with:** no (gate de fin de fase 5)
**Artifacts:**
- `backend/tests/integration/test_compras_routers_smoke.py` (NEW)

**Acceptance criteria:**
- [ ] Smoke test que hace GET a cada endpoint (con auth mockeada) y valida: status code esperado, schema del response OK.
- [ ] Test por cada endpoint: unauth (401), sin permiso (403), con permiso (200/201/422/409 según caso).
- [ ] Todos los endpoints del design §9 cubiertos.

**Implementation notes:**
- Gate: si los routers de F5 no pasan este smoke, no se arranca F6.

---

### Task COMPRAS-5.10: Documentación de API (Markdown) para frontend
**Size:** S
**Depends on:** 5.1..5.8
**Parallelizable with:** 5.9
**Artifacts:**
- `backend/docs/modulo_compras_api.md` (NEW)

**Acceptance criteria:**
- [ ] Documento que tabula cada endpoint con: método, path, body, response, errores, permiso requerido.
- [ ] Incluye ejemplos de payload para los casos "especiales": 409 POSIBLE_DUPLICADO_OP_ERP, 422 OP_CAJA_MONEDA_MISMATCH.
- [ ] Link a `/docs` (Swagger auto-generado).

**Implementation notes:**
- Facilita arranque de F6.

---

### Task COMPRAS-5.11: Middleware / handler de excepciones para respuestas estandarizadas
**Size:** S
**Depends on:** 5.9
**Parallelizable with:** 5.10
**Artifacts:**
- `backend/app/main.py` (MODIFIED — verificar exception handler existente)

**Acceptance criteria:**
- [ ] Verificar que las HTTPException levantadas por los servicios llegan al cliente con el payload JSON esperado (ej: `{detail, codigo, duplicados_detectados}` del 409).
- [ ] Si el handler existente pisa el payload, ajustar para que respete `exc.detail` si ya es dict.
- [ ] Test: levantar 409 desde un servicio y verificar que `response.json()` tiene `codigo='POSIBLE_DUPLICADO_OP_ERP'`.

**Implementation notes:**
- Defensivo: asegura que los contratos del design §7.2 y §3.2 se cumplan en el wire.

---

### Task COMPRAS-5.12: Endpoint `GET /cajas/documentos?entidad_tipo=orden_pago` (si hace falta)
**Size:** S
**Depends on:** 5.9
**Parallelizable with:** 5.10, 5.11
**Artifacts:**
- `backend/app/routers/administracion_caja.py` (MODIFIED — verificar si ya existe)

**Acceptance criteria:**
- [ ] Verificar si el router de cajas existente ya expone `GET /caja-documentos` con filtro `entidad_tipo`. Si sí → N/A, marcar skip.
- [ ] Si no existe el filtro, agregarlo: `GET /caja-documentos?entidad_tipo=orden_pago&entidad_id=<id>` para que el frontend de Cajas pueda mostrar el link "Ver OP" (REQ-CAJ-004).
- [ ] Test cubriendo filtrado.

**Implementation notes:**
- REQ-CAJ-004. Task probablemente skippable dependiendo del estado actual del router.

---

## Fase 6 — Frontend

> Todo bajo `frontend/src/` siguiendo el patrón canónico de `AdministracionCaja.jsx`. CSS Modules + Tesla Design System. Auto-invocar skill `pricing-app-frontend` + `pricing-app-design` al codear.

### Task COMPRAS-6.1: Hook `useComprasApi.js` — axios client wrapper
**Size:** S
**Depends on:** F5 (endpoints listos)
**Parallelizable with:** 6.2
**Artifacts:**
- `frontend/src/hooks/useComprasApi.js` (NEW)

**Acceptance criteria:**
- [ ] Funciones tipo: `listarPedidos(params)`, `obtenerPedido(id)`, `crearPedido(data)`, `editarPedido(id, data)`, etc. para CADA endpoint del design §9.
- [ ] Usa axios client existente (`frontend/src/services/api.js`).
- [ ] Manejo de errores: extrae `response.data` y rethrow para que el componente capture.
- [ ] Soporte explícito de 409 POSIBLE_DUPLICADO_OP_ERP: el hook devuelve el payload al caller (no lo enmascara como error genérico).

**Implementation notes:**
- Patrón: revisar `useCajaApi.js` si existe como referencia.

---

### Task COMPRAS-6.2: Página `AdministracionCompras.jsx` — layout con tabs
**Size:** M
**Depends on:** 6.1
**Parallelizable with:** 6.1
**Artifacts:**
- `frontend/src/pages/AdministracionCompras.jsx` (NEW)
- `frontend/src/pages/AdministracionCompras.module.css` (NEW)
- `frontend/src/App.jsx` (MODIFIED — agregar ruta `/administracion/compras` con ProtectedRoute)

**Acceptance criteria:**
- [ ] Ruta `/administracion/compras` protegida (require login + permiso `ver_ordenes_compra`).
- [ ] Layout con tabs: `Pedidos | Órdenes de Pago | CC Proveedor | Reconciliación | Sale Documents`.
- [ ] Cada tab carga un componente separado (lazy load opcional).
- [ ] Sigue el look & feel de `AdministracionCaja.jsx` (referencia).
- [ ] CSS Modules + design tokens (design system Tesla). Dark mode via `ThemeContext`.
- [ ] Navbar existente muestra link "Compras" bajo "Administración" si el usuario tiene permiso.

**Implementation notes:**
- Referencia: `AdministracionCaja.jsx`.
- Cargar skills `pricing-app-frontend` + `pricing-app-design`.

---

### Task COMPRAS-6.3: Listado de pedidos + filtros + paginación
**Size:** M
**Depends on:** 6.2
**Parallelizable with:** 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 6.11, 6.12, 6.13
**Artifacts:**
- `frontend/src/components/compras/PedidosList.jsx` (NEW)
- `frontend/src/components/compras/PedidosList.module.css` (NEW)

**Acceptance criteria:**
- [ ] Tabla con columnas: número, proveedor, empresa, monto/moneda, estado (badge con color), fecha_pago_estimada, creado_por, acciones.
- [ ] Filtros: estado (multi-select), proveedor, empresa, rango de fechas.
- [ ] Paginación server-side usando `useServerPagination.js`.
- [ ] Botones por fila: `Ver detalle`, `Editar` (solo borrador, según permisos).
- [ ] CTA top: `+ Nuevo pedido` (abre modal).
- [ ] Estados en badge: borrador (gris), pendiente_aprobacion (amarillo), aprobado (azul), rechazado (rojo), cancelado (gris oscuro), pagado_parcial (celeste), pagado (verde).
- [ ] No usa emojis como iconos (regla AGENTS.md). Usa `lucide-react`.

**Implementation notes:**
- REQ-PED-001, design §9.1.

---

### Task COMPRAS-6.4: Modal `PedidoFormModal.jsx` — alta/edición
**Size:** L
**Depends on:** 6.3
**Parallelizable with:** 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 6.11, 6.12, 6.13
**Artifacts:**
- `frontend/src/components/compras/PedidoFormModal.jsx` (NEW)
- `frontend/src/components/compras/PedidoFormModal.module.css` (NEW)

**Acceptance criteria:**
- [ ] ModalTesla (componente existente) con título "Nuevo pedido" / "Editar pedido".
- [ ] Campos: empresa (select), proveedor (select async), moneda (ARS/USD), monto (numérico), fecha_pago_texto, fecha_pago_estimada, requiere_envio (switch), numero_factura (opcional), observaciones.
- [ ] Validaciones: monto > 0, moneda requerida, proveedor requerido.
- [ ] Si `estado ≠ 'borrador'` en edición → campos disabled excepto `numero_factura` (REQ-PED-006).
- [ ] Botones: `Cancelar`, `Guardar borrador`, `Guardar y enviar a aprobación` (llama 2 endpoints).
- [ ] Manejo de errores: 400/409 con toast del mensaje del backend.

**Implementation notes:**
- Design §9.1, REQ-PED-001, REQ-PED-006.

---

### Task COMPRAS-6.5: Detalle de pedido con timeline de eventos + transiciones
**Size:** L
**Depends on:** 6.3
**Parallelizable with:** 6.4, 6.6, 6.7, 6.8, 6.9, 6.10, 6.11, 6.12, 6.13
**Artifacts:**
- `frontend/src/components/compras/PedidoDetalle.jsx` (NEW)
- `frontend/src/components/compras/PedidoTimeline.jsx` (NEW)

**Acceptance criteria:**
- [ ] Vista de detalle con:
  - Cabecera con datos básicos + estado + botones de transición según estado y permisos.
  - Botones: `Enviar a aprobación`, `Aprobar`, `Rechazar` (abre modal pidiendo `accion + motivo`), `Reabrir`, `Cancelar`, `Generar etiqueta de retiro`.
  - Timeline vertical de `compras_eventos` filtrados por `entidad_tipo='pedido_compra'` con iconos por tipo, descripción humana, usuario, fecha.
  - Panel lateral con imputaciones que apuntan al pedido (de CC/OP relacionadas).
  - Si `ct_transaction_id` set → mostrar link "Ver factura ERP" con número.
- [ ] Botones respetan permisos del usuario (usa `usePermisos()`).
- [ ] Transiciones inválidas → los botones NO se renderizan (no solo disabled).

**Implementation notes:**
- REQ-PED-002, REQ-PED-004 + design §6.

---

### Task COMPRAS-6.6: Listado + form de órdenes de pago + banner sessionStorage
**Size:** L
**Depends on:** 6.2
**Parallelizable with:** 6.3, 6.4, 6.5, 6.7, 6.8, 6.9, 6.10, 6.11, 6.12, 6.13
**Artifacts:**
- `frontend/src/components/compras/OrdenesPagoList.jsx` (NEW)
- `frontend/src/components/compras/OrdenPagoFormModal.jsx` (NEW)
- `frontend/src/components/compras/DuplicadoERPBanner.jsx` (NEW)

**Acceptance criteria:**
- [ ] Listado con columnas: número, proveedor, empresa, monto/moneda, modo_imputacion (badge), estado, fecha_pago_real, acciones.
- [ ] Form modal con:
  - Selección de proveedor, empresa, moneda, monto_total.
  - Radio de modo: Específica / A cuenta / Mixta.
  - Si Específica/Mixta: selector de items (pedidos con saldo o facturas ERP) con monto imputado por item.
  - Validación live: suma de items vs monto_total según modo.
  - **Banner sessionStorage arriba del form** según design §7.4:
    - Key: `compras_op_doble_contab_banner_dismissed_${user_id}_${YYYYMMDD}`.
    - Texto: "Si este pago ya se registró directamente en el ERP, NO lo cargues aquí. Se contabilizaría dos veces."
    - Botón "Entendido" dismissa (set sessionStorage).
    - Reaparece al día siguiente por el YYYYMMDD en la key.
    - NO usa localStorage.
  - Button "Crear OP" envía POST.
- [ ] Si backend responde 409 POSIBLE_DUPLICADO_OP_ERP → abrir ModalTesla con lista de duplicados, `[Cancelar]` o `[Confirmar, es un pago distinto]` que reenvía con `confirmar_duplicado=true`.

**Implementation notes:**
- REQ-OP-001, REQ-OP-002, REQ-OP-005 + design §7.3, §7.4.

---

### Task COMPRAS-6.7: Detalle de OP + pagar + anular + distribuir FIFO
**Size:** L
**Depends on:** 6.6
**Parallelizable with:** 6.3, 6.4, 6.5, 6.8, 6.9, 6.10, 6.11, 6.12, 6.13
**Artifacts:**
- `frontend/src/components/compras/OrdenPagoDetalle.jsx` (NEW)
- `frontend/src/components/compras/PagarOPModal.jsx` (NEW)

**Acceptance criteria:**
- [ ] Detalle muestra OP + imputaciones + eventos.
- [ ] Si `estado='pendiente'`: botón `Pagar` abre modal con selección de caja (filtrada por empresa + moneda de la OP) + fecha_pago_real.
- [ ] Si backend responde 422 OP_CAJA_MONEDA_MISMATCH → mostrar error en modal: "La caja seleccionada es {moneda_caja}, pero la OP es {moneda_op}. Elegí una caja de la moneda correcta."
- [ ] Botón `Distribuir automáticamente` (solo en modo `a_cuenta`/`mixta` pendiente) invoca `/distribuir-automatico`.
- [ ] Si `estado='pagado'`: botón `Anular` (con confirmación de motivo).
- [ ] Permisos: pagar/anular requieren `ejecutar_pagos`.

**Implementation notes:**
- REQ-OP-003, REQ-OP-004, REQ-OP-006 + design §3.2.

---

### Task COMPRAS-6.8: CC Proveedor drill-down + saldo por moneda
**Size:** L
**Depends on:** 6.2
**Parallelizable with:** 6.3..6.7, 6.9, 6.10, 6.11, 6.12, 6.13
**Artifacts:**
- `frontend/src/components/compras/CCProveedorDetalle.jsx` (NEW)
- `frontend/src/components/compras/CCProveedorDetalle.module.css` (NEW)

**Acceptance criteria:**
- [ ] Selector de proveedor.
- [ ] **Cards principales**: "Saldo ARS: $X" + "Saldo USD: US$Y" bien grandes, como fuente de verdad (REQ-CC-002).
- [ ] Badge secundario: "Estimado consolidado: $Z ARS @ TC ... (fecha TC)" con disclaimer "Estimado al TC del día. Fuente de verdad: saldos por moneda."
- [ ] Toggle `[Cronológico] | [Agrupado por pedido]` (REQ-CC-003).
- [ ] Tabla cronológica: fecha, tipo (debe/haber/ajuste), origen, descripción, monto/moneda, saldo corriente.
- [ ] Vista agrupada por pedido: card por pedido con debe/haber/saldo de ese pedido.
- [ ] Link al pedido/OP de origen en cada fila.

**Implementation notes:**
- REQ-CC-002, REQ-CC-003 + design §9.4.

---

### Task COMPRAS-6.9: Panel admin — Reconciliación (listado + forzar + métricas deprecación)
**Size:** M
**Depends on:** 6.2
**Parallelizable with:** 6.3..6.8, 6.10, 6.11, 6.12, 6.13
**Artifacts:**
- `frontend/src/components/compras/ReconciliacionPanel.jsx` (NEW)

**Acceptance criteria:**
- [ ] Tab "Reconciliación" dentro de la página Compras.
- [ ] Top: métricas visibles (REQ-CC-005):
  - "Días consecutivos sin divergencia: 12 / 30"
  - "Cobertura de proveedores: 67% / 80%"
  - "Estado: criterio NO cumplido / cumplido"
- [ ] Tabla de `cc_reconciliacion_log` con filtros fecha + estado (ok/divergencia).
- [ ] Columnas: fecha_corrida, proveedor, moneda, saldo_libro_mayor, saldo_snapshot, diferencia, tolerancia_aplicada, estado, nota.
- [ ] Botón admin: "Forzar reconciliación ahora" (POST /reconciliacion/forzar, con confirmación).
- [ ] Si hay divergencias recientes → alert visible.

**Implementation notes:**
- REQ-CC-004, REQ-CC-005 + design §9.4.

---

### Task COMPRAS-6.10: Panel admin — Sale Document Catalog (READ-ONLY + no clasificados)
**Size:** M
**Depends on:** 6.2
**Parallelizable with:** 6.3..6.9, 6.11, 6.12, 6.13
**Artifacts:**
- `frontend/src/components/compras/SaleDocumentsPanel.jsx` (NEW)

**Acceptance criteria:**
- [ ] Tab "Sale Documents" (solo visible para admin).
- [ ] Tabla READ-ONLY de `tb_sale_document` con columnas: sd_id, sd_desc, flags (checkboxes disabled — son solo lectura), clasificacion (derivada del clasificador — badge con color por tipo).
- [ ] **NO hay columna `synced_at`** (ya no existe — tabla es seed estático).
- [ ] **NO hay botón "Forzar sync ahora"** (eliminado en refinement 2026-04-17 — no hay sync, el catálogo se extiende vía Alembic migration).
- [ ] Filtro: por clasificación (FACTURA, NC, ND, REMITO, AJUSTE, ANULACION, CONTRAPARTE, IGNORAR), por flag (`sd_ispurchase`, `sd_isbanking`, etc.).
- [ ] Sección "`sd_id`s no catalogados": consulta `GET /sale-documents/faltantes` (COMPRAS-3.4) que busca `sd_id` recientes en `tb_commercial_transactions` (últimos 30 días) que NO están en `tb_sale_document`.
- [ ] Si hay `sd_id`s no catalogados → **mensaje claro**: `"⚠ Aparecieron N tipo(s) de documento nuevo(s) en el ERP (sd_id: X, Y, Z). Contactar al admin para agregarlos al catálogo vía migración Alembic."` (NO invitar a "forzar sync" porque no existe).
- [ ] Si la lista de `faltantes` tiene filas → log WARNING server-side en el endpoint (ya implementado en COMPRAS-3.4, verificar).
- [ ] Tabla de `{sd_id, count, primera_aparicion}` para los faltantes.

**Implementation notes:**
- REQ-SDC-007 + design §9.5 + R1 (riesgo "sd_id nuevo en ERP sin notificar" — mitigación: panel admin + revisión mensual).
- Este panel es la **única línea de defensa** contra que GBP agregue un tipo de documento sin avisarnos. Revisión operativa mensual obligatoria.

---

### Task COMPRAS-6.11: Extensión de TabEnviosFlex para `tipo_envio='retiro_proveedor'`
**Size:** M
**Depends on:** 1.8 (migración), 4.2 (servicio)
**Parallelizable with:** 6.3..6.10, 6.12, 6.13
**Artifacts:**
- `frontend/src/pages/TabEnviosFlex.jsx` (MODIFIED — o el componente real equivalente)
- `frontend/src/components/envios/EtiquetaEnvioRow.jsx` (MODIFIED)

**Acceptance criteria:**
- [ ] El componente existente detecta `etiqueta.tipo_envio`.
- [ ] Si `'retiro_proveedor'`:
  - Badge con texto "Retiro proveedor" (color distinto, ej. azul).
  - Muestra nombre del proveedor + dirección (origen del retiro) en vez de datos del cliente.
  - Link "Ver pedido" → `/administracion/compras/pedidos/{pedido_compra_id}`.
- [ ] Si `'cliente'`: sin cambios en el rendering.
- [ ] Tab/selector para filtrar "Todos / Cliente / Retiro proveedor".
- [ ] Queries existentes (`GET /etiquetas-envio/?cliente_id=X`) siguen funcionando sin romper.

**Implementation notes:**
- REQ-LOG-003. Requiere identificar el componente real — probablemente en `pages/` o `components/turbo/`.

---

### Task COMPRAS-6.12: Link "Ver OP" desde Cajas
**Size:** S
**Depends on:** 5.12
**Parallelizable with:** 6.3..6.11, 6.13
**Artifacts:**
- `frontend/src/components/caja/CajaDocumentoDetalle.jsx` (MODIFIED — identificar componente real)

**Acceptance criteria:**
- [ ] Componente de detalle de CajaMovimiento detecta `caja_documento.entidad_tipo`.
- [ ] Si `='orden_pago'` → muestra link "Ver OP #OP-01-2026-00042" (usa `entidad_id` en el path).
- [ ] Link abre `/administracion/compras/ordenes-pago/{entidad_id}`.
- [ ] Si `='orden_pago_anulada'` → similar pero con texto "Ver OP anulada".
- [ ] Otros `entidad_tipo` existentes: sin cambios.

**Implementation notes:**
- REQ-CAJ-004.

---

### Task COMPRAS-6.13: Navbar — link "Compras" bajo Administración con gating por permiso
**Size:** S
**Depends on:** 6.2
**Parallelizable with:** 6.3..6.12
**Artifacts:**
- `frontend/src/components/Navbar.jsx` (MODIFIED)

**Acceptance criteria:**
- [ ] Bajo el grupo "Administración" aparece link "Compras" → `/administracion/compras`.
- [ ] Visible SOLO si `tienePermiso('administracion.ver_ordenes_compra')`.
- [ ] Se integra al pattern de navegación existente (probar dark/light mode).

**Implementation notes:**
- Usa `usePermisos()`.

---

### Task COMPRAS-6.14: Componente `ImputacionesPanel.jsx` (vista completa + reimputar + desimputar)
**Size:** M
**Depends on:** 6.2
**Parallelizable with:** 6.3..6.13
**Artifacts:**
- `frontend/src/components/compras/ImputacionesPanel.jsx` (NEW)
- `frontend/src/components/compras/ReimputarModal.jsx` (NEW)

**Acceptance criteria:**
- [ ] Tabla de imputaciones con filtros (proveedor, origen_tipo, destino_tipo, fecha).
- [ ] Columnas: id, origen, destino, monto/moneda, es_reversal (badge), reimputada_desde_id, creado_por, fecha.
- [ ] Acciones por fila: `Desimputar` (modal de confirmación + motivo), `Reimputar` (modal seleccionando nuevo destino).
- [ ] Reimputar modal muestra combos válidos permitidos (del backend) — si el usuario elige combo inválido, el backend responde 400.
- [ ] Si intenta reimputar una ya reimputada (`reimputada_desde_id IS NOT NULL` en la original) → 400 del backend, mostrar toast.

**Implementation notes:**
- REQ-IMP-005.

---

## Fase 7 — Tests (unitarios + integración + concurrencia)

> Tests específicos que **no** fueron cubiertos inline en F1-F6. Acá van los de mayor complejidad y regresión.

### Task COMPRAS-7.1: Test regresión — 43 sd_id del clasificador (parametrizado)
**Size:** M
**Depends on:** 2.1, 3.1
**Parallelizable with:** 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9
**Artifacts:**
- `backend/tests/unit/test_sale_document_classifier.py` (NEW)
- `backend/tests/fixtures/sd_ids_known.py` (NEW)

**Acceptance criteria:**
- [ ] Fixture con los 43 sd_id conocidos + flags esperados (basado en state.yaml `key_decisions.matching_erp.sd_ids_conocidos_regression_test` y obs #106).
- [ ] Test parametrizado con `@pytest.mark.parametrize` cubriendo TODOS los 43: clasificación esperada + `afecta_cc_proveedor` + `signo_contable`.
- [ ] Clasificaciones esperadas (baseline REQ-SDC-005):
  - FACTURA: 101, 104, 130, 131 (nota: 104 tiene ambigüedad con ND — ver SDC-02 cierre).
  - NC: 103, 133.
  - ND: 132 (104 resuelto como FACTURA en design).
  - REMITO: 102.
  - ORDEN_PAGO: 106.
  - AJUSTE_SALDO: 121, 123, 125 (D15: reversión OP rechazada → AJUSTE_SALDO), 128, 129.
  - IGNORAR: 105 (presupuesto), 124 (stock inicial).
  - ANULACION: 151, 152, 153, 154, 156, 180.
  - CONTRAPARTE: 161, 162, 163, 164, 166, 190.
- [ ] Test adicional `test_all_known_sd_ids_are_classified_not_ignore` itera `tb_sale_document` local (si poblado) y falla si un sd_id clasifica a `IGNORAR` sin estar en la whitelist explícita [105, 124].
- [ ] `pytest backend/tests/unit/test_sale_document_classifier.py -v` pasa.

**Implementation notes:**
- REQ-SDC-005 + D15 + obs #106.

---

### Task COMPRAS-7.2: Test concurrencia — `numeracion_service` bajo 10 hilos
**Size:** M
**Depends on:** 2.2
**Parallelizable with:** 7.1, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9
**Artifacts:**
- `backend/tests/integration/test_numeracion_concurrencia.py` (NEW)

**Acceptance criteria:**
- [ ] Fixture `db_session_factory` que retorna una factory de sesiones separadas (necesario para concurrencia real).
- [ ] Test `test_dos_requests_simultaneos_no_generan_duplicados` con 10 threads simultáneos invocando `generar_siguiente_numero(s, 'pedido', 1, 2026)` + commit.
- [ ] Asserts: 10 números únicos, conjunto exacto = `{P-01-2026-00001, ..., P-01-2026-00010}`, `numeracion_contadores.ultimo_numero` = 10 al final.
- [ ] Test secundario `test_concurrencia_tipos_distintos` con 5 threads de 'pedido' + 5 threads de 'orden_pago' → verifica que los contadores son independientes.
- [ ] `pytest backend/tests/integration/test_numeracion_concurrencia.py -v` pasa (puede tardar 2-3s).

**Implementation notes:**
- REQ-NUM-004 + design §1.6.
- Si el test falla en CI por timing, investigar — es señal de bug en el lock, no de flakiness aceptable.

---

### Task COMPRAS-7.3: Tests de matching ERP con fixture JUKEBOX
**Size:** M
**Depends on:** 3.3, 3.5
**Parallelizable with:** 7.1, 7.2, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9
**Artifacts:**
- `backend/tests/integration/test_erp_matching.py` (NEW)

**Acceptance criteria:**
- [ ] Reusa fixture `jukebox_facturas` de COMPRAS-3.3.
- [ ] Test `test_match_forward_factura_sola_vigente` — pedido con numero_factura → matchea ct 101 vigente, setea ct_transaction_id, inserta evento.
- [ ] Test `test_match_forward_factura_anulada_no_matchea` — pedido con numero_factura de factura anulada → no setea ct_transaction_id.
- [ ] Test `test_match_forward_factura_contraparte_matchea_base` — ct 101 + ct 161 → matchea solo la 101.
- [ ] Test `test_match_backward_cts_sincronizadas` — simula sync de 3 cts nuevas, ejecuta `match_backward`, verifica que pedidos con `numero_factura` matching quedan asociados.
- [ ] Test `test_match_backward_aborta_si_catalogo_vacio` — `tb_sale_document` vacía → raise RuntimeError.

**Implementation notes:**
- REQ-ERP-007 + design §4.1 + §5.

---

### Task COMPRAS-7.4: Tests de whitelist imputaciones — 6 combos válidos + N inválidos
**Size:** S
**Depends on:** 2.5, 4.3
**Parallelizable with:** 7.1, 7.2, 7.3, 7.5, 7.6, 7.7, 7.8, 7.9
**Artifacts:**
- `backend/tests/unit/test_imputaciones_whitelist.py` (NEW — extender si ya existe de COMPRAS-2.5)
- `backend/tests/integration/test_imputaciones_crear.py` (NEW)

**Acceptance criteria:**
- [ ] Unit tests cubriendo los 6 combos válidos (no raise).
- [ ] Unit tests cubriendo al menos 8 combos inválidos raise HTTPException(400) con mensaje exacto `"Combinación origen/destino no soportada en v1"`.
- [ ] Integration test `test_crear_imputacion_happy` verifica que la fila se crea + 1 cc_proveedor_movimiento haber.
- [ ] Integration test `test_crear_imputacion_combo_invalido_rollback` → nada en DB.
- [ ] Integration test `test_crear_imputacion_cross_moneda_falla` (D3) — origen ARS + destino USD → 400.
- [ ] Integration test `test_crear_imputacion_proveedor_inconsistente` → 400.

**Implementation notes:**
- REQ-IMP-002, REQ-IMP-003, REQ-IMP-006 + D3.

---

### Task COMPRAS-7.5: Tests de state machine de pedidos — todas las transiciones
**Size:** M
**Depends on:** 4.1
**Parallelizable with:** 7.1..7.4, 7.6, 7.7, 7.8, 7.9
**Artifacts:**
- `backend/tests/unit/test_pedidos_state_machine.py` (NEW)

**Acceptance criteria:**
- [ ] Test matrix: cubre las 10 transiciones válidas del design §6.
- [ ] Test matrix: cubre TODAS las transiciones inválidas (al menos 20) con `HTTPException(400)` y mensaje exacto `"Transición no permitida: {origen} -> {destino}"`.
- [ ] Tests específicos:
  - `test_borrador_a_aprobado_directo_falla` (salto ilegal).
  - `test_pagado_no_sale_de_ese_estado` (terminal).
  - `test_cancelado_no_sale` (terminal).
  - `test_aprobar_sin_permiso_critico_falla` → 403.
  - `test_rechazar_sin_accion_falla` → 400.
  - `test_cancelar_aprobado_crea_ajuste_reverso_en_cc` (integración mínima).

**Implementation notes:**
- REQ-PED-001, REQ-PED-002, REQ-PED-003, REQ-PED-005 + design §6.

---

### Task COMPRAS-7.6: Tests de integración `ordenes_pago.ejecutar_pago` atómico
**Size:** L
**Depends on:** 4.6
**Parallelizable with:** 7.1..7.5, 7.7, 7.8, 7.9
**Artifacts:**
- `backend/tests/integration/test_ordenes_pago_pagar_atomico.py` (NEW)

**Acceptance criteria:**
- [ ] Fixture crea: 1 caja ARS activa con saldo, 1 pedido aprobado, 1 OP pendiente imputando al pedido.
- [ ] Test `test_pago_ars_happy_5_artefactos` (REQ-CAJ-001): verifica 1 caja_movimiento + 1 caja_documento + 1 caja_documento_movimiento + OP.caja_movimiento_id set + 1 cc_proveedor_movimiento haber + pedido pasa a `pagado`.
- [ ] Test `test_pago_cross_moneda_bloqueado_422` (D7): OP USD + caja ARS → 422 `OP_CAJA_MONEDA_MISMATCH` con payload exacto.
- [ ] Test `test_pago_falla_paso_caja_rollback_total`: mock `caja_service.registrar_movimiento` para que raise, verificar que NADA queda en DB (0 CajaDocumento, 0 cc_proveedor_movimiento, OP sigue pendiente).
- [ ] Test `test_op_mixta_crea_imputacion_saldo_remanente` (REQ-OP-002): OP monto=15000, items=13000 → crea imputación saldo=2000 en el pago.
- [ ] Test `test_pago_sin_permiso_ejecutar_pagos_falla_403`.

**Implementation notes:**
- REQ-OP-004 + REQ-CAJ-001 + D7 + D8.

---

### Task COMPRAS-7.7: Tests anti-doble-contabilización (409 POSIBLE_DUPLICADO_OP_ERP)
**Size:** M
**Depends on:** 2.6, 4.7
**Parallelizable with:** 7.1..7.6, 7.8, 7.9
**Artifacts:**
- `backend/tests/integration/test_op_anti_doble_contabilizacion.py` (NEW)

**Acceptance criteria:**
- [ ] Fixture inserta en `tb_commercial_transactions` una ct con `sd_id=106, supp_id=X, ct_docnumber='FA-00012345', ct_date=today`.
- [ ] Test `test_crear_op_con_factura_duplicada_sin_flag_devuelve_409`: response status=409, body incluye `codigo='POSIBLE_DUPLICADO_OP_ERP'` y `duplicados_detectados` con estructura esperada.
- [ ] Test `test_crear_op_con_factura_duplicada_con_flag_confirma_y_registra_evento`: con `confirmar_duplicado=true` → 201 + inserta evento `tipo='op_creada_con_duplicado_confirmado'` con `payload.ct_transaction_duplicada`.
- [ ] Test `test_ct_iscancelled_no_dispara_409`: ct con `ct_iscancelled=true` → no detecta duplicado.
- [ ] Test `test_ct_vieja_no_dispara_409`: ct con `ct_date = today - 30 days` → no detecta (ventana 7 días).
- [ ] Test `test_sin_items_factura_erp_no_dispara_409`: OP con solo items a `pedido_compra` → no dispara detección.

**Implementation notes:**
- REQ-OP-005 + design §7.1.

---

### Task COMPRAS-7.8: Tests de reimputación append-only + cadena prohibida
**Size:** M
**Depends on:** 4.5
**Parallelizable with:** 7.1..7.7, 7.9
**Artifacts:**
- `backend/tests/integration/test_imputaciones_reimputar.py` (NEW)

**Acceptance criteria:**
- [ ] Test `test_reimputar_happy_crea_dos_filas`: original OP→pedido, reimputar a OP→factura_erp → 2 filas nuevas: reversal + nueva.
- [ ] Verifica: original intacta (no UPDATE), saldo proveedor invariante (debe - haber cancela en CC).
- [ ] Test `test_reimputar_una_ya_reimputada_falla_400` (D13): intenta reimputar una imputación cuyo `reimputada_desde_id IS NOT NULL` en la original → 400.
- [ ] Test `test_desimputar_happy_crea_reversal`: crea fila `es_reversal=True`, original intacta.
- [ ] Test `test_desimputar_un_reversal_falla_400`: intenta desimputar una fila con `es_reversal=True` → 400.
- [ ] Test `test_reimputar_combo_invalido_falla_400`: intenta reimputar a combo no en COMBOS_VALIDOS_V1 → 400.

**Implementation notes:**
- REQ-IMP-005 + D9 + D13.

---

### Task COMPRAS-7.9: Tests reconciliación — tolerancia por moneda + alertas/notificaciones
**Size:** M
**Depends on:** 3.6, 2.4
**Parallelizable with:** 7.1..7.8
**Artifacts:**
- `backend/tests/integration/test_reconciliacion_cc.py` (NEW)

**Acceptance criteria:**
- [ ] Test `test_reconciliacion_sin_divergencias_no_alerta`: saldos iguales → 0 divergencias → 0 alertas, 0 notificaciones.
- [ ] Test `test_reconciliacion_divergencia_ars_dispara_1_alerta_y_N_notifs`: 2 proveedores con divergencia ARS → 1 alerta + 2 notificaciones + log.alerta_id/notificacion_id poblados.
- [ ] Test `test_reconciliacion_tolerancia_diferente_por_moneda` (**Cierre 2 del usuario**): proveedor con diff ARS=80 (bajo tolerancia 100) y diff USD=2 (arriba de tolerancia 1) → solo USD marca divergencia, no ARS.
- [ ] Test `test_reconciliacion_lee_tolerancia_de_configuracion`: si se cambia el valor en `configuracion.compras.cc_reconciliacion_tolerancia_ars` a 500, entonces diff=200 ARS NO dispara divergencia.
- [ ] Test `test_reconciliacion_sync_atrasado_warn_pero_continua` (RD6): `MAX(ct_date) < today-1` → log WARN + procesa igual.

**Implementation notes:**
- REQ-CC-004 + Cierre 2 + RD6.

---

## Fase 8 — Deploy (seeds críticos, permisos, smoke tests, documentación)

> **Todos los tasks marcados PRE-DEPLOY CRITICAL son BLOQUEANTES**. Sin ellos, el módulo NO se habilita en producción.

### Task COMPRAS-8.1: **⚠ PRE-DEPLOY CRITICAL** — Seed caja USD por empresa
**Size:** S
**Depends on:** toda F1-F7 operativa
**Parallelizable with:** 8.2, 8.3
**Artifacts:**
- `backend/app/scripts/seed_cajas_usd_por_empresa.py` (NEW)
- `backend/alembic/versions/compras_015_seed_cajas_usd.py` (NEW — o script standalone, evaluar)

**Acceptance criteria:**
- [ ] **Pre-check**: `SELECT empresa_id, COUNT(*) FROM cajas WHERE moneda='USD' AND activa=true GROUP BY empresa_id`.
- [ ] Para cada empresa activa en `empresas` que NO tenga caja USD → crear automáticamente `Caja` con:
  - `nombre = f"Caja USD {empresa.nombre}"`
  - `moneda = 'USD'`
  - `empresa_id = empresa.id`
  - `saldo_inicial = Decimal("0.00")`
  - `saldo_actual = Decimal("0.00")`
  - `activa = true`
  - `descripcion = 'Caja USD creada automáticamente por seed pre-deploy del módulo de compras'`
- [ ] Log resumen: `"Empresas evaluadas: N, cajas USD creadas: M, empresas con caja USD preexistente: K"`.
- [ ] Idempotente: re-ejecutar no crea duplicados.
- [ ] Smoke test post-seed: `SELECT empresa_id FROM empresas WHERE activa=true AND id NOT IN (SELECT empresa_id FROM cajas WHERE moneda='USD' AND activa=true)` → 0 filas.

**Implementation notes:**
- **Cierre 4 del usuario** + RD7.
- CRÍTICO: sin esto, los usuarios que intenten pagar una OP USD sin caja USD reciben 422 OP_CAJA_MONEDA_MISMATCH y no pueden operar.
- Se puede implementar como migración Alembic (compras_015) o como script standalone — preferir migración para que se ejecute con `alembic upgrade head`.

---

### Task COMPRAS-8.2: **⚠ PRE-DEPLOY CRITICAL** — Verificación seed permisos + ZERO usuarios con crítico
**Size:** S
**Depends on:** 1.14
**Parallelizable with:** 8.1, 8.3
**Artifacts:**
- `backend/app/scripts/verificar_permisos_compras.py` (NEW)

**Acceptance criteria:**
- [ ] Script verifica:
  - `SELECT codigo FROM permiso WHERE codigo IN ('administracion.aprobar_ordenes_compra', 'administracion.ejecutar_pagos')` → retorna 2 filas con `es_critico=true`.
  - `SELECT COUNT(*) FROM rol_permiso rp JOIN permiso p ON p.id=rp.permiso_id WHERE p.codigo IN ('administracion.aprobar_ordenes_compra','administracion.ejecutar_pagos')` → 0 (ningún rol los tiene por default, R8).
  - `SELECT COUNT(*) FROM usuario_permiso up JOIN permiso p ON p.id=up.permiso_id WHERE p.codigo IN (...)` → 0 (ningún usuario los tiene asignado individualmente pre-deploy).
- [ ] Si falla cualquier check → exit != 0 + log detallado.
- [ ] Output final: "OK pre-deploy: permisos críticos creados, sin asignaciones automáticas."
- [ ] Post-deploy: admin asigna manualmente desde `/admin/usuarios` según documento de onboarding.

**Implementation notes:**
- R8 del proposal + REQ-PED-005 + REQ-OP-003.

---

### Task COMPRAS-8.3: Configuración de cron jobs en servidor
**Size:** S
**Depends on:** 3.6
**Parallelizable with:** 8.1, 8.2
**Artifacts:**
- `backend/deploy/crontab_compras.txt` (NEW)
- `DEPLOYMENT.md` o equivalente del proyecto (MODIFIED)

**Acceptance criteria:**
- [ ] Documento con las entradas de cron:
  - `0 3 * * * cd /path/to/backend && source venv/bin/activate && python -m app.scripts.reconciliar_cc_proveedor >> /var/log/compras/reconciliacion.log 2>&1`
  - **NO** se agrega cron para `sync_sale_documents` (eliminado en refinement 2026-04-17 — tb_sale_document es seed estático Alembic).
- [ ] Verificar que el cron `sync_commercial_transactions_guid.py` con el hook ya aplicado sigue activo (cada 10 min).
- [ ] Directorio `/var/log/compras/` creado con permisos adecuados.
- [ ] Logrotate config para el log nuevo (retain 30 días).

**Implementation notes:**
- REQ-CC-004 + D5 (cron 03:00).
- El cron de sync de sale_documents fue eliminado en el refinement 2026-04-17 (Engram obs #121): la tabla es seed estático, se popula en COMPRAS-1.2b y se extiende vía nueva Alembic migration cuando GBP agrega tipos nuevos.

---

### Task COMPRAS-8.4: Smoke tests end-to-end en staging con proveedor piloto JUKEBOX
**Size:** M
**Depends on:** 8.1, 8.2, 8.3, F7 verde
**Parallelizable with:** 8.5
**Artifacts:**
- `backend/tests/e2e/smoke_modulo_compras.md` (NEW — checklist manual)

**Acceptance criteria:**
- [ ] Checklist ejecutado en staging contra DB réplica + ERP sandbox:
  - [ ] Crear pedido P-01-2026-00001 para JUKEBOX → estado borrador.
  - [ ] Enviar a aprobación → estado `pendiente_aprobacion`.
  - [ ] Aprobar con usuario crítico → estado `aprobado` + 1 movimiento debe en CC.
  - [ ] Crear OP OP-01-2026-00001 (modo específica) imputando al pedido.
  - [ ] Pagar OP desde caja ARS → verificar 5 artefactos (REQ-CAJ-001) + pedido pasa a `pagado`.
  - [ ] Consultar CC proveedor → saldo ARS = 0 (debe - haber cancela).
  - [ ] Verificar catálogo estático tb_sale_document → 43 sd_id presentes (viene del seed Alembic COMPRAS-1.2b; no se "fuerza sync" porque no existe).
  - [ ] Forzar reconciliación → 0 divergencias (o documentadas).
  - [ ] Verificar en Cajas: el egreso aparece con link "Ver OP" → OP-01-2026-00001.
  - [ ] Crear pedido con `requiere_envio=true` → generar etiqueta de retiro → aparece en TabEnviosFlex con badge "Retiro proveedor".
  - [ ] Crear OP con factura ERP duplicada → 409 POSIBLE_DUPLICADO_OP_ERP + payload esperado.
  - [ ] Anular OP pagada → caja recibe ingreso + CC recibe debe + pedido vuelve a aprobado.
- [ ] Todos los checks ✅ → merge a main + deploy a producción.

**Implementation notes:**
- Definition of Done v1 del proposal.
- JUKEBOX es el proveedor piloto (obs #103).

---

### Task COMPRAS-8.5: README del módulo (guía de usuario + onboarding permisos)
**Size:** M
**Depends on:** 8.1, 8.2, F6 completa
**Parallelizable with:** 8.4
**Artifacts:**
- `backend/docs/README-compras.md` (NEW)
- `backend/docs/onboarding-permisos-compras.md` (NEW)

**Acceptance criteria:**
- [ ] README-compras.md incluye:
  - Diagramas de flujo (pedido → OP → pago → CC, incluyendo reimputación y anulación).
  - Cómo armar una OP específica / a cuenta / mixta.
  - Cómo usar "Distribuir automáticamente" FIFO.
  - Cómo interpretar saldos multi-moneda en CC.
  - Regla de oro anti-doble-contabilización: "UN solo canal por operación" (REQ-OP-005).
  - Qué hacer ante alertas de divergencia en reconciliación.
  - Nota sobre gaps en numeración (D21) — son aceptables.
- [ ] onboarding-permisos-compras.md explica:
  - Los 2 permisos nuevos (`aprobar_ordenes_compra`, `ejecutar_pagos`), criticidad, a quién asignarlos.
  - Criterio organizacional: NO dar ambos permisos al mismo usuario si se quiere evitar auto-aprobación (aunque v1 no lo bloquea técnicamente — REQ-PED-005 scenario).
- [ ] Plan de deprecación de snapshot CC (change futuro) documentado con los criterios de R2.
- [ ] Guía de monitoring: `pg_stat_activity` + `pg_locks` sobre `numeracion_contadores` (**Cierre 1 del usuario**) para detectar contention bajo volumen alto.

**Implementation notes:**
- Definition of Done v1 del proposal + R2 + R8 + Cierre 1.

---

### Task COMPRAS-8.6: Checklist post-deploy + monitoring inicial (48h)
**Size:** S
**Depends on:** 8.4
**Parallelizable with:** 8.5
**Artifacts:**
- `backend/docs/post-deploy-checklist-compras.md` (NEW)

**Acceptance criteria:**
- [ ] Checklist para monitorear las primeras 48h post-deploy:
  - [ ] 6h post-deploy: `sync_commercial_transactions_guid.py` sigue verde (hook no rompió el cron).
  - [ ] Post-migration: `SELECT COUNT(*) FROM tb_sale_document` → **43 filas** (seed estático de COMPRAS-1.2b corrió OK en la subida de versión; no depende de cron).
  - [ ] 24h post-deploy: `reconciliar_cc_proveedor.py` corrió 1x a las 03:00 → log OK.
  - [ ] Primer pedido de producción creado sin errores (numero = `P-XX-2026-00001`).
  - [ ] Primera OP creada + pagada sin errores → 5 artefactos OK.
  - [ ] `pg_stat_activity` / `pg_locks` sobre `numeracion_contadores`: sin waiting queries sostenidos (>5s).
  - [ ] Alertas y notificaciones de admin funcionando (spot-check con un evento manual).
- [ ] Rollback plan documentado: si falla algo crítico en las primeras 24h, cómo hacer downgrade de migraciones + disable de cron.

**Implementation notes:**
- **Cierre 1 del usuario** (monitoring pg_locks en producción bajo volumen real).

---

## Apéndice A — Índice de tasks por ID (para tracking rápido)

### Fase 0 — Pre-flight (3 tasks activas + 1 cancelada)
- [ ] ~~COMPRAS-0.1~~ — 🚫 CANCELADA (tb_sale_document es seed estático, sin sync ERP)
- [ ] COMPRAS-0.2 — Confirmar `EMPRESA_A_COMP_BRA_MAP` (S) **BLOQUEANTE**
- [ ] COMPRAS-0.3 — Confirmar sync ERP en verde (S) **BLOQUEANTE**
- [ ] COMPRAS-0.4 — Inventariar `etiquetas_envio.cliente_id` nullable (S)

### Fase 1 — Foundations (19 tasks)
- [ ] COMPRAS-1.1 — Migración `compras_001_numeracion_contadores` (S)
- [ ] COMPRAS-1.2 — Migración `compras_002_tb_sale_document` (estructura, sin synced_at) (S)
- [ ] COMPRAS-1.2b — **Seed estático tb_sale_document** (~43 registros Alembic, NEW en refinement) (M)
- [ ] COMPRAS-1.3 — `compras_empresa_erp_map.py` + constants (S)
- [ ] COMPRAS-1.4 — Migración `compras_003_pedidos_compra` (M)
- [ ] COMPRAS-1.5 — Migración `compras_004_ordenes_pago` (M)
- [ ] COMPRAS-1.6 — Migración `compras_005_compras_eventos` (S)
- [ ] COMPRAS-1.7 — Migración `compras_006_etiquetas_envio_paso_a` (S)
- [ ] COMPRAS-1.8 — Migración `compras_007_etiquetas_envio_paso_b` (M)
- [ ] COMPRAS-1.9 — Migración `compras_008_imputaciones` (M)
- [ ] COMPRAS-1.10 — Migración `compras_009_cc_proveedor_movimientos` (M)
- [ ] COMPRAS-1.11 — Migración `compras_010_cc_reconciliacion_log` (S)
- [ ] COMPRAS-1.12 — Vista `v_facturas_compra_vigentes` (M)
- [x] COMPRAS-1.13 — Seed `caja_tipo_documentos` (S)

- [x] COMPRAS-1.14 — Seed permisos críticos (S)

- [x] COMPRAS-1.15 — Seed tolerancias por moneda (S)
- [ ] COMPRAS-1.16 — Schemas Pydantic (M)
- [ ] COMPRAS-1.17 — Helper `require_permiso` (S — posible N/A)
- [ ] COMPRAS-1.18 — Docs schema diagramado (S)

### Fase 2 — Servicios base (8 tasks)
- [ ] COMPRAS-2.1 — `sale_document_classifier.py` (M)
- [ ] COMPRAS-2.2 — `numeracion_service.py` (M)
- [ ] COMPRAS-2.3 — `cc_proveedor_service.py` base (M)
- [ ] COMPRAS-2.4 — Validador tolerancia por moneda (S)
- [ ] COMPRAS-2.5 — `imputaciones_service.py` esqueleto + whitelist (M)
- [ ] COMPRAS-2.6 — `ordenes_pago_service.py` esqueleto + detectar_duplicado (M)
- [ ] COMPRAS-2.7 — `erp_matching_service.py` esqueleto (S)
- [ ] COMPRAS-2.8 — Adapter cajas + verificación signatures (S)

### Fase 3 — Matching ERP (4 tasks activas + 2 eliminadas)
- [ ] ~~COMPRAS-3.1~~ — 🚫 ELIMINADA (sync script innecesario — seed estático en 1.2b)
- [ ] ~~COMPRAS-3.2~~ — 🚫 ELIMINADA (endpoint forzar sync innecesario — no hay sync)
- [ ] COMPRAS-3.3 — Tests vista JUKEBOX (M)
- [ ] COMPRAS-3.4 — Endpoint `/sale-documents/faltantes` + router (S)
- [ ] COMPRAS-3.5 — Hook en `sync_commercial_transactions_guid.py` (M)
- [ ] COMPRAS-3.6 — Cron `reconciliar_cc_proveedor.py` (L)

### Fase 4 — Servicios de flujo (9 tasks)
- [ ] COMPRAS-4.1 — `pedidos_service.py` + state machine (L)
- [ ] COMPRAS-4.2 — `etiqueta_retiro_service.py` (M)
- [ ] COMPRAS-4.3 — `imputaciones.crear` + `cc.aplicar_imputacion` (L)
- [ ] COMPRAS-4.4 — `imputaciones.distribuir_fifo` (M)
- [ ] COMPRAS-4.5 — `imputaciones.desimputar` + `reimputar` (M)
- [ ] COMPRAS-4.6 — `ordenes_pago.ejecutar_pago` atómico (XL)
- [ ] COMPRAS-4.7 — `ordenes_pago.crear` + detección duplicado (M)
- [ ] COMPRAS-4.8 — `ordenes_pago.anular` (L)
- [ ] COMPRAS-4.9 — Transición automática pagado_parcial/pagado (M)

### Fase 5 — Endpoints REST (12 tasks)
- [ ] COMPRAS-5.1 — Router pedidos — listado/detalle/CRUD borrador (M)
- [ ] COMPRAS-5.2 — Router pedidos — transiciones (M)
- [ ] COMPRAS-5.3 — Router pedidos — etiqueta + eventos (S)
- [ ] COMPRAS-5.4 — Router OP — listado/detalle/create (M)
- [ ] COMPRAS-5.5 — Router OP — pagar/anular/distribuir (M)
- [ ] COMPRAS-5.6 — Router imputaciones (M)
- [ ] COMPRAS-5.7 — Router cc_proveedor + reconciliación (M)
- [ ] COMPRAS-5.8 — Router sale-documents completo + registrar en main (S)
- [ ] COMPRAS-5.9 — Smoke tests de todos los routers (M) **GATE F5**
- [ ] COMPRAS-5.10 — Doc de API markdown (S)
- [ ] COMPRAS-5.11 — Exception handler payload estandarizado (S)
- [ ] COMPRAS-5.12 — Endpoint filtro CajaDocumento por entidad_tipo (S — posible N/A)

### Fase 6 — Frontend (14 tasks)
- [ ] COMPRAS-6.1 — Hook `useComprasApi.js` (S)
- [ ] COMPRAS-6.2 — Página `AdministracionCompras.jsx` con tabs (M)
- [ ] COMPRAS-6.3 — Listado de pedidos (M)
- [ ] COMPRAS-6.4 — Modal form de pedido (L)
- [ ] COMPRAS-6.5 — Detalle de pedido + timeline + transiciones (L)
- [ ] COMPRAS-6.6 — Listado + form OP + banner sessionStorage (L)
- [ ] COMPRAS-6.7 — Detalle OP + pagar + anular + distribuir (L)
- [ ] COMPRAS-6.8 — CC Proveedor drill-down multi-moneda (L)
- [ ] COMPRAS-6.9 — Panel Reconciliación + métricas (M)
- [ ] COMPRAS-6.10 — Panel Sale Documents READ-ONLY + no clasificados (sin botón sync) (M)
- [ ] COMPRAS-6.11 — Extensión TabEnviosFlex para retiro proveedor (M)
- [ ] COMPRAS-6.12 — Link "Ver OP" desde Cajas (S)
- [ ] COMPRAS-6.13 — Navbar link "Compras" (S)
- [ ] COMPRAS-6.14 — Panel imputaciones + reimputar/desimputar (M)

### Fase 7 — REDEFINIDA EN EJECUCIÓN (2026-04-20): Tests de integración + fixes diferidos
> Nota: la numeración original F7.1-F7.9 asumía que F2-F5 dejaban tests unitarios pendientes.
> En la práctica F2-F5 incluyeron sus tests (baseline final 352 passed). F7 se reorientó a:
>   (a) resolver 2 bugs conocidos diferidos (clasificador CONTRAPARTE, exception handler),
>   (b) cerrar los 3 gaps UX de F6 (PanelImputaciones, Ver OP desde Caja, ProveedorAutocomplete),
>   (c) agregar tests de integración contra DB real (skippeables por env).
> Ver state.yaml::fase_7_tests_integracion_y_fixes_diferidos para el detalle.

- [x] COMPRAS-7.1 — FIX clasificador CONTRAPARTE con session (Engram #125) + 7 tests (M)
- [x] COMPRAS-7.2 — FIX exception_handler preserva dicts estructurados + tests 409/422 shape estructurado (M)
- [x] COMPRAS-7.3 — 4 tests JUKEBOX con DB real readonly (skippeable por env) (M)
- [x] COMPRAS-7.4 — Test concurrencia numeración 10 hilos Postgres real (skippeable por env) (M)
- [x] COMPRAS-7.5 — PanelImputaciones standalone + integración sub-tab (M)
- [x] COMPRAS-7.6 — Link "Ver OP" desde AdministracionCaja + deep-link query param (M)
- [x] COMPRAS-7.7 — ProveedorComprasAutocomplete en forms de pedido y OP (S)
- [ ] COMPRAS-7.8 — Tests E2E Playwright — **DIFERIDO a F8** (playwright no configurado) (L)
- [x] COMPRAS-7.9 — Performance baseline document (medición real queda para F8) (S)

### Fase 8 — Deploy (6 tasks)
- [x] COMPRAS-8.1 — **PRE-DEPLOY CRITICAL**: Seed caja USD por empresa (S) — script `verify_compras_pre_deploy.py` auto-remedia faltantes
- [x] COMPRAS-8.2 — **PRE-DEPLOY CRITICAL**: Verificación permisos sin asignaciones (S) — script `verificar_permisos_compras.py`
- [x] COMPRAS-8.3 — Configurar crons en servidor (S) — documentado en `openspec/changes/modulo-compras/deploy-setup.md`
- [x] COMPRAS-8.4 — Smoke tests E2E con JUKEBOX (M) — checklist en `docs/modulos/compras-post-deploy-checklist.md` Fase B (ejecución manual del usuario en staging)
- [x] COMPRAS-8.5 — README + onboarding + monitoring guide (M) — `docs/modulos/compras-guia-usuario.md` + `compras-dev-guide.md`
- [x] COMPRAS-8.6 — Checklist post-deploy 48h (S) — `docs/modulos/compras-post-deploy-checklist.md`

---

## Apéndice B — Mapping de cierres post-design del usuario a tasks

| Cierre del usuario | Tasks que lo implementan |
|---|---|
| **1. Volumen compras <100/día → lock pesimista se mantiene + monitoring pg_locks** | COMPRAS-2.2 (docstring nota), COMPRAS-8.5 (guía de monitoring), COMPRAS-8.6 (checklist 48h con pg_stat) |
| **2. Tolerancia reconciliación POR MONEDA** | COMPRAS-1.15 (seed 2 claves), COMPRAS-2.4 (validador), COMPRAS-3.6 (reconcilia lee por moneda), COMPRAS-7.9 (test por moneda) |
| **3. Mapeo empresa ↔ (comp_id, bra_id) configurable** | COMPRAS-0.2 (confirmación), COMPRAS-1.3 (archivo de mapeo), COMPRAS-3.5 (hook usa `resolver_comp_bra`) |
| **4. Seed caja USD CRÍTICO pre-deploy** | COMPRAS-8.1 (PRE-DEPLOY CRITICAL) |
| **5. Task 0 pre-flight checks BLOQUEANTE** | Fase 0 activas: COMPRAS-0.2, 0.3, 0.4 (0.1 CANCELADA por refinement 2026-04-17). ABORTA apply si cualquiera falla. |

---

## Apéndice C — Dependencias entre fases (grafo resumen)

```
Fase 0 (BLOQUEANTE: confirmaciones externas)
   │
   ▼
Fase 1 (migraciones + modelos + seeds + schemas)
   │  └─ todas paralelizables excepto 1.7→1.8 y 1.4/1.5→1.6
   ▼
Fase 2 (servicios base — clasificador, numeración, cc, esqueletos)
   │  └─ 2.1, 2.2, 2.3, 2.4 paralelizables entre sí
   │     2.5, 2.6, 2.7, 2.8 paralelizables entre sí
   ▼
Fase 3 (sync + matching + cron reconciliación)
   │  ├─ 3.1→3.2→3.4 secuencial
   │  ├─ 3.3 paralelo
   │  ├─ 3.5 depende de 2.7 + 1.12
   │  └─ 3.6 depende de 2.3, 2.4, 1.11
   ▼
Fase 4 (servicios de flujo completos)
   │  ├─ 4.1, 4.2, 4.3 paralelizables
   │  ├─ 4.4, 4.5 dependen de 4.3
   │  ├─ 4.6 (XL) depende de 2.6, 2.8, 4.3  ← task más crítico
   │  ├─ 4.7 paralelo con 4.6
   │  ├─ 4.8 depende de 4.5 + 4.6
   │  └─ 4.9 depende de 4.1, 4.3
   ▼
Fase 5 (endpoints REST)
   │  └─ 5.1..5.8 en paralelo tras F4, gate en 5.9
   ▼
Fase 6 (frontend)
   │  └─ 6.1 + 6.2 primero; 6.3..6.14 mayormente paralelizables
   ▼
Fase 7 (tests avanzados)
   │  └─ todos paralelizables entre sí
   ▼
Fase 8 (deploy)
   └─ 8.1, 8.2, 8.3 paralelizables; 8.4 depende de los anteriores; 8.5, 8.6 al final
```

---

## Apéndice D — Tasks críticos / único-cuerpo (no partir)

- **COMPRAS-4.6 (XL — `ordenes_pago.ejecutar_pago` atómico)**: único cuerpo transaccional que toca 5 tablas. Si se parte, se rompe la atomicidad. Tests E2E exhaustivos.
- **COMPRAS-3.5 (hook en sync guid)**: único punto de modificación del cron crítico existente. Cualquier bug acá rompe el sync de tb_commercial_transactions — con try/except defensivo pero aún así alto riesgo.
- **COMPRAS-1.7/1.8 (migración `etiquetas_envio`)**: secuencial OBLIGATORIA (paso A antes que paso B). No paralelizar bajo NINGÚN concepto.
- **Fase 0 completa**: BLOQUEA toda la cadena. No arrancar F1 sin los 3 activos confirmados (0.2, 0.3, 0.4 — 0.1 está CANCELADA).
- **COMPRAS-8.1 / 8.2 (pre-deploy critical)**: sin esto, el módulo NO se habilita.

---

## Next

`sdd-apply COMPRAS-0.2..0.4` (fase 0 activas primero; 0.1 está CANCELADA). Después avanzar en batches por fase. F1 incluye el seed estático COMPRAS-1.2b con los 43 registros (fuente: Engram obs #106).

## Referencias cruzadas

- Proposal: `openspec/changes/modulo-compras/proposal.md`
- Design: `openspec/changes/modulo-compras/design.md` (1350 líneas, 22 decisiones D1..D22, 10 riesgos emergentes RD1..RD10)
- Specs: `openspec/changes/modulo-compras/specs/*.md` (9 archivos, 53 requirements)
- State: `openspec/changes/modulo-compras/state.yaml`
- Cierres post-design: incorporados en tasks de F0, F1.15, F2.4, F3.6, F7.9, F8.1, F8.5, F8.6.

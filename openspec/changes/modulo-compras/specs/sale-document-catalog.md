# Spec Delta — Sale Document Catalog (ERP)

**Change:** modulo-compras
**Capability:** sale-document-catalog
**Status:** draft

> ⚠ **Refinement 2026-04-17** (Engram obs #121): `tb_sale_document` pasa a ser **seed estático Alembic** (sin sync automático). El catálogo se popula con los ~43 registros conocidos (obs #106) vía migración (`compras_NNNN_seed_tb_sale_document.py`, COMPRAS-1.2b). Tipos nuevos en el futuro → **nueva Alembic migration** (no hay cron, no hay script, no hay endpoint admin ABM). Se reescribieron REQ-SDC-002, REQ-SDC-003, REQ-SDC-006, REQ-SDC-007 y se cerraron OPEN_QUESTION-SDC-01/03.

## Purpose

Proveer el catálogo de tipos de documento (`tb_sale_document`) como tabla maestra local **seed-only** (Alembic migration con los ~43 registros conocidos) y proveer un **clasificador semántico** (`sale_document_classifier.py`) con 5 predicados que reemplaza las listas hardcodeadas de `sd_id` (abandonadas tras el hallazgo del catálogo completo, obs #106). Este spec es la base del matching ERP y de todos los cálculos de impacto en CC proveedor.

## ADDED Requirements

### Requirement: REQ-SDC-001 — Modelo local `tb_sale_document` con flags semánticos

**Priority:** must
**Type:** functional

El sistema MUST implementar el modelo local `tb_sale_document` con las siguientes columnas (matcheando el esquema del ERP origen):

- `sd_id` (INT PK — NO autogenerado, viene del ERP)
- `sd_desc` (VARCHAR NOT NULL — descripción legible, ej. "Factura A Compra")
- `sd_isCredit` (BOOLEAN)
- `sd_isQuotation` (BOOLEAN)
- `sd_isReceipt` (BOOLEAN)
- `sd_isTaxable` (BOOLEAN)
- `sd_isInBalance` (BOOLEAN)
- `sd_isSales` (BOOLEAN)
- `sd_isPurchase` (BOOLEAN)
- `sd_isBanking` (BOOLEAN)
- `sd_isPackingList` (BOOLEAN)
- `sd_isCreditNote` (BOOLEAN)
- `sd_isDebitNote` (BOOLEAN)
- `sd_isAnnulment` (BOOLEAN)
- `sd_plusOrminus` (INT — `+1` o `-1`, leído directo del ERP)
- `hacc_group` (INT NULL — agrupación contable)

> **NOTA (refinement 2026-04-17)**: columna `synced_at` **eliminada**. La tabla es seed estático Alembic, no hay sync que timestampear.

#### Scenario: Tabla populada tras migración seed

- GIVEN un deploy fresco
- WHEN se ejecuta `alembic upgrade head` (incluye la migración `compras_NNNN_seed_tb_sale_document.py` — COMPRAS-1.2b)
- THEN `tb_sale_document` MUST contener los 43 registros conocidos del catálogo (sd_id 1-80 ventas + sd_id 101-500 compras/bancos según obs #106)
- AND cada fila MUST tener todos los flags copiados **exactos del ERP** (NO inventados)

### Requirement: REQ-SDC-002 — ~~Mapeo de nombres local ↔ ERP~~ OBSOLETO

**Status:** 🚫 OBSOLETO (refinement 2026-04-17, Engram obs #121)

Ya no hay sync desde el ERP, por lo tanto **no hay mapeo** de nombre de tabla ERP → local que sostener. `tb_sale_document` es tabla local poblada vía Alembic migration con datos de `obs #106`. Se deja el requirement como placeholder para trazabilidad. OPEN_QUESTION-SDC-01 (nombre tabla ERP) queda cerrada como **no aplica**.

### Requirement: REQ-SDC-003 — Seed estático Alembic de `tb_sale_document`

**Priority:** must
**Type:** functional

El sistema MUST poblar `tb_sale_document` vía **una única migración Alembic seed** (`backend/alembic/versions/compras_NNNN_seed_tb_sale_document.py`, task COMPRAS-1.2b) con los ~43 registros conocidos del catálogo del ERP (fuente: Engram obs #106, dos tablas pasadas por el usuario: sd_id 1-80 de ventas + sd_id 101-500 de compras/bancos).

Reglas:

1. La migración MUST usar `op.bulk_insert()` o `INSERT` raw con los valores **copiados exactos del ERP** — NO inventar flags. Los valores correctos están en obs #106.
2. La migración MUST incluir `downgrade()` que borre las filas del seed (`DELETE FROM tb_sale_document WHERE sd_id IN (...)`) o `TRUNCATE` si no hay seeds posteriores.
3. La migración MUST ser idempotente (re-correrla no duplica ni rompe).
4. NO hay cron, NO hay script de sync, NO hay endpoint admin "forzar sync". Esta es una decisión explícita (Engram obs #121): la tabla del ERP cambia 1-2 veces por año → no justifica sync automático.
5. Tipos nuevos en el futuro → **nueva Alembic migration** (INSERT de la fila nueva), decisión operativa tras revisión humana del ERP.

#### Scenario: Migración seed idempotente

- GIVEN `tb_sale_document` ya tiene 43 filas tras `alembic upgrade head`
- WHEN se corre `alembic downgrade -1` y luego `alembic upgrade head` de nuevo
- THEN `tb_sale_document` vuelve a tener las 43 filas, idénticas
- AND el clasificador puede clasificar los 43 sd_id sin retornar `UNKNOWN`

#### Scenario: Sd_id nuevo aparece en ERP (flujo operativo)

- GIVEN el ERP de GBP agrega un nuevo `sd_id=167 "ND Compra Especial"`
- AND aparece en `tb_commercial_transactions` sin estar en `tb_sale_document` local
- WHEN un admin revisa el panel `/administracion/compras/sale-documents`
- THEN MUST ver en la sección "sd_id no catalogados" una fila `{sd_id: 167, count: N, primera_aparicion: <date>}`
- AND el mensaje dice `"Aparecieron 1 tipo(s) de documento nuevo(s) en el ERP. Contactar al admin para agregar vía migración Alembic."`
- AND la operativa correcta es: dev crea una nueva Alembic migration `compras_MMMM_add_sd_167.py` con un INSERT single-row → deploy → el sd_id entra al catálogo.
- AND NO hay botón "forzar sync" (no existe).

### Requirement: REQ-SDC-004 — Clasificador semántico con 5 predicados

**Priority:** must
**Type:** functional

El sistema MUST implementar `backend/app/services/sale_document_classifier.py` con EXACTAMENTE cinco funciones públicas:

```python
class ClasificacionDocCompra(str, Enum):
    FACTURA = "FACTURA"
    NC = "NC"
    ND = "ND"
    REMITO = "REMITO"
    ORDEN_PAGO = "ORDEN_PAGO"
    ANULACION = "ANULACION"
    CONTRAPARTE = "CONTRAPARTE"
    AJUSTE_SALDO = "AJUSTE_SALDO"
    PRESUPUESTO = "PRESUPUESTO"
    IGNORAR = "IGNORAR"

def clasificar_documento_compra(sd: SaleDocument) -> ClasificacionDocCompra: ...
def afecta_cc_proveedor(sd: SaleDocument) -> bool: ...
def signo_contable(sd: SaleDocument) -> int: ...   # +1 o -1
def es_anulacion(sd: SaleDocument) -> bool: ...
def es_contraparte(sd: SaleDocument, sd_base: SaleDocument) -> bool: ...
```

Reglas de implementación:

- **NO SHALL haber números mágicos**: NO se permite `if sd.sd_id == 101` ni `if sd.sd_id in [101, 103]`. La clasificación SHALL leer EXCLUSIVAMENTE de los flags (`sd_isPurchase`, `sd_isCreditNote`, `sd_isAnnulment`, `sd_plusOrminus`, `hacc_group`, etc.).
- `signo_contable(sd)` SHALL retornar `sd.sd_plusOrminus` directamente (el ERP ya lo define; no decidimos nosotros).
- `es_contraparte(sd, sd_base)` heurística documentada: `sd.hacc_group == sd_base.hacc_group AND sd.sd_plusOrminus == -sd_base.sd_plusOrminus AND sd.sd_id != sd_base.sd_id`.
- `afecta_cc_proveedor(sd)` MUST retornar `false` para `REMITO`, `PRESUPUESTO`, `ANULACION`, `CONTRAPARTE`, `IGNORAR`; `true` para el resto.

#### Scenario: Factura clasifica correctamente

- GIVEN un sd con `sd_isPurchase=true, sd_isTaxable=true, sd_isInBalance=true, sd_isAnnulment=false, sd_isCreditNote=false, sd_isDebitNote=false, sd_isPackingList=false, sd_isReceipt=false, sd_isQuotation=false`
- WHEN se invoca `clasificar_documento_compra(sd)`
- THEN MUST retornar `ClasificacionDocCompra.FACTURA`
- AND `afecta_cc_proveedor(sd)` MUST retornar `true`

#### Scenario: Anulación detectada

- GIVEN un sd con `sd_isPurchase=true, sd_isAnnulment=true`
- WHEN se invoca `clasificar_documento_compra(sd)`
- THEN MUST retornar `ClasificacionDocCompra.ANULACION`
- AND `es_anulacion(sd)` MUST retornar `true`
- AND `afecta_cc_proveedor(sd)` MUST retornar `false`

#### Scenario: Signo contable lee ERP

- GIVEN un sd con `sd_plusOrminus=-1` (ej. NC compra)
- WHEN se invoca `signo_contable(sd)`
- THEN MUST retornar `-1`
- AND NO SHALL haber lógica custom que derive el signo de otros campos

### Requirement: REQ-SDC-005 — Tests de regresión sobre 43 sd_id conocidos

**Priority:** must
**Type:** non-functional

El sistema MUST incluir tests unitarios en `backend/tests/unit/test_sale_document_classifier.py` que cubran cada uno de los **43 sd_id conocidos del catálogo** (referenciados en `state.yaml → key_decisions.matching_erp.sd_ids_conocidos_regression_test`).

Para cada sd_id, el test MUST validar:
- Clasificación esperada (ej. sd_id=101 → FACTURA, sd_id=151 → ANULACION, sd_id=106 → ORDEN_PAGO).
- `afecta_cc_proveedor()` esperado.
- `signo_contable()` esperado.

El test SHALL usar `pytest.mark.parametrize` con una tabla de expected values. Si aparece un sd_id nuevo en el catálogo real que no está cubierto, el test suite DEBERÍA tener un test adicional `test_all_known_sd_ids_are_classified` que itere `tb_sale_document` local y falle si algún sd_id clasifica a `IGNORAR` sin justificación explícita.

Clasificaciones esperadas (baseline según obs #106):
- **FACTURA**: 101, 104, 130, 131
- **NC**: 103, 133
- **ND**: 104, 132 (ojo: 104 puede ser FACTURA o ND según otros flags; resolver en diseño)
- **REMITO**: 102
- **ORDEN_PAGO**: 106
- **AJUSTE_SALDO**: 121, 123, 128, 129
- **IGNORAR**: 105 (presupuesto), 124 (stock inicial)
- **ANULACION**: 151, 152, 153, 154, 156, 180
- **CONTRAPARTE**: 161, 162, 163, 164, 166, 190
- **REVERSION_OP_RECHAZADA**: 125 (clasificar como `AJUSTE_SALDO` o crear categoría aparte; decidir en diseño)

#### Scenario: Test parametrizado de los 43 sd_id

- GIVEN el catálogo local populado con los 43 sd_id conocidos
- WHEN se ejecuta `pytest backend/tests/unit/test_sale_document_classifier.py`
- THEN todos los tests parametrizados MUST pasar
- AND el total de tests MUST ser >= 43 (uno por sd_id)

### Requirement: REQ-SDC-006 — Ordenamiento: seed ANTES que matching (pre-flight)

**Priority:** must
**Type:** integration

El seed Alembic de `tb_sale_document` (COMPRAS-1.2b) MUST correr **antes** de habilitar el hook de matching en `sync_commercial_transactions_guid.py`. Dos mecanismos complementarios:

1. **Orden de deploy**: `alembic upgrade head` (incluye la migración seed) corre en el paso de deploy ANTES de habilitar el hook / cron de `sync_commercial_transactions_guid.py`.
2. **Validación defensiva en runtime**: el hook de matching en el cron guid MUST verificar al arrancar que `SELECT COUNT(*) FROM tb_sale_document > 0`; si está vacío, aborta con alerta admin (ver `erp-matching` REQ-ERP-006). Esto protege contra un rollback manual accidental.

Esto asegura que el clasificador nunca opera sin catálogo, evitando falsos negativos silenciosos.

#### Scenario: Primer deploy respeta ordenamiento

- GIVEN un ambiente fresco sin migraciones aplicadas
- WHEN se hace deploy y se habilita el cron guid SIN haber corrido `alembic upgrade head`
- THEN el primer run del hook SHALL abortar con alerta admin (ver REQ-ERP-006)
- AND NO SHALL procesar ninguna ct hasta que `alembic upgrade head` corra y la migración seed de COMPRAS-1.2b inserte las 43 filas.

#### Scenario: Rollback accidental del seed

- GIVEN alguien corrió `alembic downgrade` borrando el seed por error
- WHEN el cron guid corre
- THEN el hook detecta `tb_sale_document` vacío, genera notificación admin y NO procesa (ver REQ-ERP-006)
- AND el admin restaura con `alembic upgrade head`

### Requirement: REQ-SDC-007 — Panel admin READ-ONLY + listado de sd_id no catalogados

**Priority:** should
**Type:** functional

El sistema SHOULD exponer en `/administracion/compras/sale-documents` un panel **READ-ONLY** que:

1. Lista las filas actuales de `tb_sale_document` con sus flags (checkboxes disabled, NO editables desde UI).
2. Muestra la clasificación derivada de cada fila (columna derivada vía clasificador).
3. **NO hay botón "Forzar sync ahora"** (eliminado en refinement 2026-04-17 — no hay sync).
4. Sección "sd_id no catalogados": consulta `GET /sale-documents/faltantes` (sd_id que aparecen en `tb_commercial_transactions` en los últimos 30 días y NO están en `tb_sale_document` local).
5. Si existen sd_id no catalogados → mensaje explícito: `"⚠ Aparecieron N tipo(s) de documento nuevo(s) en el ERP (sd_id: X, Y). Contactar al admin para agregarlos al catálogo vía migración Alembic."`
6. El endpoint `GET /sale-documents/faltantes` MUST loggear WARNING server-side si detecta filas (para observability).

#### Scenario: sd_id faltante aparece en el panel

- GIVEN `tb_commercial_transactions` tiene cts recientes con `sd_id=999` que NO está en `tb_sale_document`
- WHEN un admin abre el panel `/administracion/compras/sale-documents`
- THEN MUST ver un alert con sección "sd_id no catalogados" listando `{sd_id: 999, count: 3, primera_aparicion: 2026-04-15}`
- AND el mensaje sugiere **agregar vía migración Alembic** (NO "forzar sync")
- AND el endpoint loggeó WARNING `"[WARNING] sd_id no catalogados detectados: [999] — requiere nueva Alembic migration"` server-side

## OPEN QUESTIONS

- ~~OPEN_QUESTION-SDC-01~~: **CERRADA (NO APLICA)** — refinement 2026-04-17. Ya no hay sync desde el ERP, por lo tanto no se necesita conocer el nombre exacto de la tabla ERP origen. El catálogo es seed estático Alembic.
- OPEN_QUESTION-SDC-02: ¿Cómo identificar `REVERSION_OP_RECHAZADA` (sd_id=125) por flags? No parece haber un flag explícito. Opciones: (a) categorizar como `AJUSTE_SALDO`, (b) agregar un predicado heurístico `es_reversion_op(sd)` basado en descripción o `hacc_group` específico. Decidir en diseño.
- ~~OPEN_QUESTION-SDC-03~~: **CERRADA (NO APLICA)** — refinement 2026-04-17. Ya no hay sync desde el ERP (ni vía API REST ni vía DB directa). Catálogo poblado vía seed Alembic único.

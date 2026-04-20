# Spec Delta — ERP Matching (Pedidos ↔ Facturas)

**Change:** modulo-compras
**Capability:** erp-matching
**Status:** draft

## Purpose

Cruzar automáticamente pedidos del pricing-app con facturas reales sincronizadas desde el ERP (`tb_commercial_transactions`), usando la tupla `(comp_id, bra_id, supp_id, ct_docnumber)` como llave canónica. Implementado como hook inline al final del cron `sync_commercial_transactions_guid.py` (activo cada 10 min). Depende críticamente del catálogo `tb_sale_document` estando populado antes de correr.

## ADDED Requirements

### Requirement: REQ-ERP-001 — Llave de matching canónica

**Priority:** must
**Type:** functional

La llave de matching entre un pedido y una factura del ERP MUST ser la tupla:

```
(comp_id, bra_id, supp_id, ct_docnumber)
```

Donde:
- `comp_id` = empresa del pricing-app mapeada a la empresa del ERP.
- `bra_id` = branch (sucursal) — siempre presente en `tb_commercial_transactions`.
- `supp_id` = proveedor del pricing-app mapeado a `supp_id` del ERP.
- `ct_docnumber` = número de documento (factura, NC, etc.) tal como lo reporta el ERP.

El sistema MUST NOT usar `df_id` o `fc_id` como llave (hallazgo #104: `df_id` casi siempre NULL en compras; `fc_id` es condición fiscal del cliente, no tipo de documento).

#### Scenario: Matching por tupla completa

- GIVEN un pedido con `numero_factura='FA-00012345'`, `proveedor_id=7` (mapeado a `supp_id=42` del ERP), `empresa_id=1` (mapeada a `comp_id=1`, `bra_id=1`)
- WHEN el hook busca en `tb_commercial_transactions`
- THEN MUST filtrar `WHERE comp_id=1 AND bra_id=1 AND supp_id=42 AND ct_docnumber='FA-00012345'`

### Requirement: REQ-ERP-002 — DISTINCT ON priorizando sd_id principal

**Priority:** must
**Type:** functional

Una misma tupla `(comp_id, bra_id, supp_id, ct_docnumber)` puede tener múltiples `ct_transaction` con distintos `sd_id` (hallazgo #106: factura + anulación + contraparte son 3 asientos separados, ej. sd_id 101 + 151 + 161 para `ct_docnumber=00389000`). El matching MUST aplicar `DISTINCT ON` priorizando el documento "vigente" sobre anulaciones/contrapartes:

```sql
SELECT DISTINCT ON (comp_id, bra_id, supp_id, ct_docnumber) *
FROM v_facturas_compra_vigentes
WHERE (comp_id, bra_id, supp_id, ct_docnumber) = (:comp, :bra, :supp, :docnum)
ORDER BY comp_id, bra_id, supp_id, ct_docnumber,
  CASE
    WHEN sale_document.sd_isAnnulment THEN 99
    WHEN sale_document.hacc_group_is_contraparte THEN 98
    ELSE 1
  END ASC;
```

La prioridad efectiva SHALL basarse en los predicados del clasificador (`sale-document-catalog`): factura vigente > ND > NC > {anulación, contraparte} al final.

#### Scenario: Tupla con factura + anulación

- GIVEN `ct_docnumber='00389000'` del `supp_id=42` tiene 3 filas en `tb_commercial_transactions`: sd_id=101 (factura), sd_id=151 (anulación), sd_id=161 (contraparte)
- WHEN el hook matching busca
- THEN MUST retornar la fila con `sd_id=101` (vigente)
- AND NO SHALL retornar las filas 151 ni 161

### Requirement: REQ-ERP-003 — Vista SQL `v_facturas_compra_vigentes`

**Priority:** must
**Type:** functional

El sistema MUST crear una vista SQL `v_facturas_compra_vigentes` que filtra el ruido contable del ERP. La vista SHALL excluir:

1. Transacciones con `sale_document.sd_isAnnulment = true` (anulaciones).
2. Contrapartes (identificadas por el clasificador `es_contraparte(sd, sd_base)` en `sale_document_classifier.py`). Heurística documentada: mismo `hacc_group` y `sd_plusOrminus` invertido vs el documento base.
3. Transacciones cuyo `ct_docnumber + supp_id` tiene una anulación posterior con la misma tupla (la factura fue anulada aunque no esté marcada individualmente).
4. Transacciones con `ct_kindof='X'` (remitos según #104, sd_id 102, 106/301 para algunos casos — cruzar con `sale_document_classifier.clasificar_documento_compra(sd) NOT IN (REMITO, PRESUPUESTO)`).

La vista MUST exponer las columnas: `ct_transaction`, `comp_id`, `bra_id`, `supp_id`, `ct_docnumber`, `ct_total`, `curr_id_transaction`, `ct_date`, `sd_id`, `clasificacion` (derivada del clasificador).

#### Scenario: Factura anulada no aparece

- GIVEN ct 1001 con sd_id=101 (factura), docnumber=00389000, supp_id=42
- AND ct 1002 con sd_id=151 (anulación), docnumber=00389000, supp_id=42
- WHEN se consulta `SELECT * FROM v_facturas_compra_vigentes WHERE supp_id=42 AND ct_docnumber='00389000'`
- THEN el resultado MUST estar vacío (tiene anulación posterior con misma tupla)

#### Scenario: Factura vigente sola

- GIVEN ct 2001 con sd_id=101, docnumber=00400000, supp_id=42 (sin anulación ni contraparte)
- WHEN se consulta la vista
- THEN MUST retornar la fila con `clasificacion='FACTURA'`

### Requirement: REQ-ERP-004 — Matching bidireccional

**Priority:** must
**Type:** functional

El sistema MUST implementar matching en dos direcciones:

**(a) Pedido → Factura**: cuando un pedido es editado agregando/cambiando `numero_factura`, el sistema MUST buscar en `v_facturas_compra_vigentes` una ct con esa tupla y, si existe, asociarla (persistir `pedido.ct_transaction_id = <ct_id>` — columna nueva en `pedidos_compra`) y crear/ajustar imputaciones según corresponda.

**(b) Factura → Pedido**: al final del cron `sync_commercial_transactions_guid.py`, el hook MUST iterar las ct nuevas/actualizadas en esta corrida y buscar pedidos con `numero_factura == ct.ct_docnumber AND proveedor_id mapped supp_id AND ct_transaction_id IS NULL` para asociarlas.

Si hay match, el sistema MUST registrar un evento en `pedido_compra_eventos` con `tipo='matcheado_con_erp'`, `payload={ct_transaction, sd_id, ct_docnumber}`.

#### Scenario: Pedido recibe numero_factura y matchea al vuelo

- GIVEN un pedido `P1` aprobado, sin `numero_factura`
- AND existe en ERP ct=5000, docnumber='FA-00012345', supp_id correspondiente
- WHEN el PM edita `P1` agregando `numero_factura='FA-00012345'`
- THEN el sistema busca en `v_facturas_compra_vigentes` y encuentra ct=5000
- AND setea `P1.ct_transaction_id=5000`
- AND registra evento `tipo='matcheado_con_erp'`

#### Scenario: Factura llega después y el hook matchea

- GIVEN un pedido `P2` con `numero_factura='FA-00099999'` sin ct asociada
- WHEN el cron guid corre, sincroniza y encuentra ct=6000 con docnumber='FA-00099999', supp_id correspondiente
- THEN al final del cron el hook detecta el match
- AND asocia `P2.ct_transaction_id=6000`
- AND registra evento `tipo='matcheado_con_erp'`

### Requirement: REQ-ERP-005 — Hook inline al final de `sync_commercial_transactions_guid.py`

**Priority:** must
**Type:** integration

El matching factura → pedido MUST ejecutarse como último paso del script `backend/app/scripts/sync_commercial_transactions_guid.py` (cron activo cada 10 min), NO como un cron independiente. Esto evita races: el hook corre inmediatamente después de que las ct nuevas se persistieron.

El hook MUST:
1. Llamar a una función `run_matching_on_recent_cts(session, cts_synced_this_run)` que opera solo sobre las ct agregadas/actualizadas en la corrida actual.
2. Loggear un resumen: `"matching_run: {N} pedidos asociados, {M} ct procesadas, {K} errores"`.
3. Capturar excepciones sin hacer fallar el cron de sync (log error, continuar).

#### Scenario: Hook corre post-sync exitoso

- GIVEN el cron guid sincroniza 50 cts nuevas
- WHEN termina la fase de persistencia
- THEN el hook de matching SHALL ejecutarse con esas 50 cts
- AND SHALL loggear el resumen

#### Scenario: Excepción en hook no aborta el cron

- GIVEN durante el matching ocurre una excepción inesperada (ej. DB lock)
- WHEN el hook falla
- THEN el cron MUST loggear el error como `[ERROR] matching_hook falló: {exc}`
- AND el cron MUST terminar con `exit 0` (éxito del sync base)

### Requirement: REQ-ERP-006 — Validación: catálogo `tb_sale_document` populado antes de correr (Observación 4)

**Priority:** must
**Type:** integration

El hook de matching MUST validar **al arrancar** que la tabla `tb_sale_document` tenga al menos una fila. Si está vacía, el hook MUST abortar ruidosamente (NO silenciosamente):

1. Loggear `[ERROR] run_matching_on_recent_cts abortado: tb_sale_document está vacío. El clasificador no puede operar sin catálogo. Verificar que la migración de seed estático (compras_NNNN_seed_tb_sale_document, COMPRAS-1.2b) se haya ejecutado.`
2. Crear una notificación admin con mensaje equivalente.
3. NO SHALL procesar ninguna ct.
4. NO SHALL hacer fallar el cron de sync (retorna a `sync_commercial_transactions_guid.py` con un flag de "skipped" registrado).

El **ordenamiento operativo** MUST ser: `alembic upgrade head` (incluye la migración seed COMPRAS-1.2b) corre en deploy ANTES de habilitar el cron guid. Si alguien hace rollback manual del seed, el hook aborta de forma defensiva. (Ver `sale-document-catalog` REQ-SDC-006 — refinement 2026-04-17: ya no hay sync automático).

#### Scenario: Catálogo vacío aborta con alerta

- GIVEN `tb_sale_document` está vacía (ej. primer deploy antes del sync inicial)
- WHEN el cron guid corre y llega al hook
- THEN el hook MUST abortar con log `[ERROR] ... tb_sale_document está vacío ...`
- AND MUST crear una notificación admin visible en `/administracion/compras/notificaciones`
- AND NO SHALL procesar cts
- AND el cron guid SHALL terminar exitosamente con `exit 0`

#### Scenario: Catálogo con al menos 1 fila continúa

- GIVEN `tb_sale_document` tiene 43 filas
- WHEN el hook arranca
- THEN la validación `SELECT COUNT(*) FROM tb_sale_document > 0` retorna true
- AND el hook SHALL proceder al matching

### Requirement: REQ-ERP-007 — Tests de integración con fixtures JUKEBOX

**Priority:** must
**Type:** non-functional

El sistema MUST incluir tests de integración en `backend/tests/integration/test_erp_matching.py` cubriendo los 3 escenarios de hallazgos del proveedor piloto JUKEBOX:

1. **Factura sola vigente**: ct con sd_id=101, docnumber único, sin anulación ni contraparte → la vista la retorna, el matching funciona.
2. **Factura anulada**: ct con sd_id=101 + ct con sd_id=151 con misma tupla → la vista NO la retorna, el matching NO asocia.
3. **Factura con contraparte**: ct con sd_id=101 + ct con sd_id=161 (contraparte) → la vista retorna solo la factura original, el matching asocia correctamente.

Los fixtures MUST usar datos reales observados (o sintéticos equivalentes) de JUKEBOX documentados en la obs #104.

#### Scenario: Test de factura anulada

- GIVEN fixtures que insertan ct 1001 (sd_id=101) + ct 1002 (sd_id=151) mismo docnumber=00389000
- WHEN se ejecuta `pytest backend/tests/integration/test_erp_matching.py::test_factura_anulada_no_matchea`
- THEN el test SHALL verificar que la query sobre `v_facturas_compra_vigentes` retorna 0 filas para esa tupla
- AND el pedido con `numero_factura='00389000'` NO SHALL quedar asociado

## OPEN QUESTIONS

- OPEN_QUESTION-ERP-01: ¿La columna `pedidos_compra.ct_transaction_id` es INT o VARCHAR? Depende del tipo real de `ct_transaction` en `tb_commercial_transactions` (confirmar schema en diseño — likely INT PK).
- OPEN_QUESTION-ERP-02: ¿El mapeo `empresa_id pricing-app → comp_id ERP` está hardcoded (1↔1, 2↔2) o requiere una tabla de mapeo? v1 = hardcoded, v2 = tabla si crecen las empresas. Confirmar en diseño.
- OPEN_QUESTION-ERP-03: ¿La vista `v_facturas_compra_vigentes` se materializa (REFRESH MATERIALIZED VIEW) o es vista normal? Depende del volumen: si `tb_commercial_transactions` > 1M filas, considerar materialized con refresh post-sync. Medir en design.

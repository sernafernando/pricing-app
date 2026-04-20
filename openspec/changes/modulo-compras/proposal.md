# Proposal — Módulo de Compras (v1)

**Change ID:** `modulo-compras`
**Fase:** proposal
**Status:** draft (refinado)
**Owner:** Product Management + Backend Lead
**Fecha:** 2026-04-17 (refinement post-catálogo tb_sale_document)

---

## Why

Hoy los PMs (product managers de compras) cargan pedidos de compra en **papel, WhatsApp y Google Sheets**. El quilombo concreto:

1. **Cero trazabilidad**: no se sabe quién aprobó qué, cuándo, ni por qué. Un pedido rechazado se pierde en el chat.
2. **CC de proveedores fragmentada**: hoy tenemos una tabla snapshot (`cuentas_corrientes_proveedores`) que replica lo que devuelve el ERP externo. No refleja pedidos aprobados pendientes de facturar, no contempla pagos parciales, no cruza imputaciones. Los dueños no tienen un número confiable de "cuánto le debo a este proveedor".
3. **Caja desconectada de compras**: cuando se paga una factura de proveedor, el egreso se carga a mano en Cajas. Nadie cruza que ese egreso corresponde a una OP específica. Doble carga, errores de tipeo, conciliación manual.
4. **Logística manual para retiros**: cuando retiramos mercadería del proveedor (no siempre, depende del acuerdo), se genera una etiqueta en TabEnviosFlex escribiendo los datos del proveedor a mano. Ya existe la data maestra (`proveedor_direccion`), pero no se reusa.
5. **Pagos a cuenta y reimputaciones**: imposibles de modelar con lo actual. Un adelanto al proveedor no se puede asignar después a una factura que todavía no llegó.

El negocio mueve plata real por este circuito. **El riesgo de error operativo y fraude interno escala con el volumen.**

---

## What

Módulo nuevo integrado al panel de **Administración** del pricing-app que cubre el circuito completo de compras:

- **Pedidos de compra** con estados y workflow de aprobación por permisos.
- **Órdenes de pago (OP)** multi-factura, con modo de imputación específica / a cuenta / mixta.
- **Tabla unificada de imputaciones** con origen/destino abiertos (VARCHAR, no ENUM) para extensión v2 sin migración destructiva.
- **Libro mayor propio de CC proveedor** (`cc_proveedor_movimientos`) con debe/haber por movimiento, multi-moneda (moneda original + TC por movimiento), saldo calculado agrupado por moneda en UI.
- **Matching automático con facturas del ERP** (`tb_commercial_transactions`) leyendo el stream ya sincronizado por el cron existente, para cruzar pedido → factura real.
- **Integración con Cajas** al pagar OP (egreso automático + `CajaDocumento` polimórfico con `entidad_tipo='orden_pago'`).
- **Integración con Logística (TabEnviosFlex)** para generar etiqueta manual de retiro en proveedor cuando `requiere_envio=true`, extendiendo `etiquetas_envio` con `tipo_envio`/`proveedor_id`/`proveedor_direccion_id`/`pedido_compra_id`.
- **Numeración correlativa por (tipo, empresa, año)** con formato `P-01-2026-00001` / `OP-01-2026-00001`, usando tabla `numeracion_contadores` + `SELECT FOR UPDATE`.
- **Permisos granulares** reusando los existentes (`administracion.ver_ordenes_compra` 155, `administracion.gestionar_ordenes_compra` 156) y agregando dos nuevos críticos: `aprobar_ordenes_compra` y `ejecutar_pagos`.

Front: página `AdministracionCompras.jsx` siguiendo el patrón canónico de `AdministracionCaja.jsx` (listado, form modal, drill-down CC por proveedor).

---

## Scope v1 (ENTRA)

### Backend
- **Modelos nuevos**:
  - `pedidos_compra` — estados `borrador | pendiente_aprobacion | aprobado | rechazado | cancelado | pagado_parcial | pagado`.
  - `pedido_compra_eventos` — auditoría inmutable (quién, qué, cuándo, payload JSON).
  - `ordenes_pago` — con `modo_imputacion ∈ {especifica, a_cuenta, mixta}`.
  - `imputaciones` — **tabla unificada**, `origen_tipo`/`destino_tipo` como `VARCHAR` abiertos. v1: origen `∈ {orden_pago, nota_credito_erp}`, destino `∈ {pedido_compra, factura_erp, saldo}`.
  - `cc_proveedor_movimientos` — libro mayor propio con `debe`, `haber`, `moneda`, `tipo_cambio` por movimiento.
  - `numeracion_contadores` — `(tipo, empresa_id, año, ultimo_numero)` con lock pesimista.
  - `tb_sale_document` — **catálogo de tipos de documento del ERP sincronizado** (tabla casi estática, ~43 registros conocidos, range sd_id 1-500). Columnas: `sd_id` (PK), `sd_desc`, `sd_isCredit`, `sd_isQuotation`, `sd_isReceipt`, `sd_isTaxable`, `sd_isInBalance`, `sd_isSales`, `sd_isPurchase`, `sd_isBanking`, `sd_isPackingList`, `sd_isCreditNote`, `sd_isDebitNote`, `sd_isAnnulment`, `sd_plusOrminus`, `hacc_group`. Es la base del clasificador semántico (ver servicios).
- **Modificaciones a tablas existentes** (backward-compatible, todo nullable):
  - `etiquetas_envio`: agregar `tipo_envio` (default `'cliente'`), `proveedor_id`, `proveedor_direccion_id`, `pedido_compra_id`.
- **Matching ERP (approach final: clasificación semántica, NO listas hardcodeadas)**:
  - Abandonamos `compras_erp_config.py` con listas `SD_COMPRAS_FACTURA=[101,103]`, `SD_COMPRAS_NC=[]`, etc. Hallazgo del catálogo completo (#106): el ERP ya provee flags semánticos (`sd_isPurchase`, `sd_isCreditNote`, `sd_isAnnulment`, `sd_isReceipt`, `sd_plusOrminus`, `hacc_group`) que permiten clasificar automáticamente cualquier `sd_id` nuevo sin intervención humana. El clasificador vive en `sale_document_classifier.py` (ver servicios).
  - Llave de matching: `(comp_id, bra_id, supp_id, ct_docnumber)` con `DISTINCT ON` priorizando el `sd_id` principal (factura vigente sobre anulación/contraparte).
  - Hook al final de `backend/app/scripts/sync_commercial_transactions_guid.py` (cron activo cada 10min).
- **Servicios nuevos**:
  - `backend/app/services/sale_document_classifier.py` — predicados semánticos del catálogo ERP. Sin números mágicos (ningún `if sd_id == 101`). Expone:
    - `clasificar_documento_compra(sd) → {FACTURA | NC | ND | REMITO | ORDEN_PAGO | ANULACION | CONTRAPARTE | AJUSTE_SALDO | PRESUPUESTO | IGNORAR}` basado en flags del ERP.
    - `afecta_cc_proveedor(sd) → bool` (excluye remitos, presupuestos, anulaciones, contrapartes).
    - `signo_contable(sd) → +1 | -1` leyendo `sd.sd_plusOrminus` del ERP (no lo decidimos nosotros).
    - `es_anulacion(sd) → bool` (sd_isAnnulment=true).
    - `es_contraparte(sd, sd_base) → bool` (heurística documentada: mismo `hacc_group` y `sd_plusOrminus` invertido vs documento base).
- **Scripts nuevos**:
  - ~~`backend/app/scripts/sync_sale_documents.py`~~ — **ELIMINADO** (refinement 2026-04-17, Engram obs #121). `tb_sale_document` pasa a ser **seed estático Alembic** (una migración con los ~43 registros conocidos, ver tasks.md COMPRAS-1.2b). La tabla del ERP cambia 1-2 veces por año → no justifica sync. Tipos nuevos → nueva Alembic migration.
- **Integraciones**:
  - Cajas: al marcar OP como pagada → `CajaMovimiento` egreso + `CajaDocumento` con `entidad_tipo='orden_pago'`, `entidad_id=orden_pago.id`.
  - Logística: si `pedido.requiere_envio=true` → generar `etiqueta_envio` con `tipo_envio='retiro_proveedor'` usando `proveedor.direcciones`.
- **Endpoints** bajo prefix `/api/administracion/compras/...` siguiendo patrón `routers/administracion_*.py`.
- **Permisos nuevos**:
  - `administracion.aprobar_ordenes_compra` (`es_critico=true`)
  - `administracion.ejecutar_pagos` (`es_critico=true`)

### Frontend
- Página `AdministracionCompras.jsx` bajo `/administracion/compras` con `ProtectedRoute`.
- Tabs/vistas:
  - Listado de pedidos con filtros (estado, proveedor, empresa, fecha).
  - Form modal de alta/edición (Tesla Design System, `ModalTesla`).
  - Detalle con timeline de eventos.
  - Vista de OPs y flujo de imputación (modo específico/a cuenta/mixto, botón "Distribuir automáticamente" FIFO).
  - Drill-down CC por proveedor con saldo agrupado por moneda.
- **Panel admin READ-ONLY de tabla maestra `tb_sale_document`** (refinement 2026-04-17): listado read-only del catálogo con flags + clasificación derivada, sección de `sd_id` no catalogados (aparecen en `tb_commercial_transactions` pero NO en el seed local) con mensaje que indica agregar vía nueva migración Alembic. **Sin botón "Forzar sync"** (no existe: catálogo es seed estático).

### Cron/Jobs
- Enganche inline al final de `sync_commercial_transactions_guid.py` para matching pedido ↔ factura ERP.

---

## Out of Scope (v2+)

Decisiones cerradas de lo que **NO entra** en este cambio y por qué:

1. **Facturas locales de proveedor**: v1 consumimos las facturas directo de `tb_commercial_transactions` (ERP externo). v2 cuando migremos la facturación al pricing-app se crea tabla `facturas_proveedor`.
2. **Notas de crédito locales**: mismo razonamiento. v1 las NCs se consumen desde el ERP cuando identifiquemos `sd_id` de NCs reales. La tabla `imputaciones` ya está lista para extender (`origen_tipo` abierto).
3. **Adjuntos en pedidos/OPs**: diferido. Cuando se necesiten, se reusa `CajaDocumento` con `entidad_tipo='pedido_compra'|'orden_pago'`.
4. **Eliminación de la tabla snapshot `cuentas_corrientes_proveedores`**: **convive** con el libro mayor nuevo en v1. La migración/deprecación se planifica en change aparte post-v1 cuando el mayor propio esté validado en producción.
5. **Aprobación por montos (tier-based)**: v1 es por permiso binario. Si se requiere "el aprobador A aprueba hasta $X, arriba de $X va al B" se hace en v2.
6. **OCR / carga automática de facturas PDF**: no. Las facturas vienen del ERP ya sincronizadas.
7. **Workflow multi-paso de aprobación** (varios aprobadores en cadena): v1 es un único paso. Reevaluar en v2.

---

## Major Risks

| # | Riesgo | Impacto | Mitigación v1 |
|---|--------|---------|---------------|
| R1 | **[medio] Dependencia de flags correctamente cargados en `tb_sale_document` del ERP**. Abandonamos listas hardcodeadas en favor de clasificación automática por flags semánticos (`sd_isPurchase`, `sd_isCreditNote`, `sd_isAnnulment`, `sd_plusOrminus`, `hacc_group`). Riesgo residual: si GBP (equipo ERP) configura mal los flags de un `sd_id` nuevo, nuestro clasificador lo procesa mal (o peor, lo ignora silenciosamente). | Clasificación incorrecta → CC proveedor contamina o pierde movimientos. Facturas nuevas quedan sin impactar libro mayor. | **(a)** Test de integración post-sync que valide que TODOS los `sd_id` usados en `tb_commercial_transactions` recientes (últimos 90 días) clasifican a algo distinto de `IGNORAR`. **(b)** Alert en admin si aparecen `sd_id` nuevos en `commercial_transactions` que no están en `tb_sale_document` (race: ERP reporta ct antes de sincronizar catálogo). **(c)** Tests unitarios del clasificador cubriendo cada `sd_id` real conocido como regression test (101, 102, 103, 104, 106, 130, 131, 151, 161, etc. — los 43 del catálogo). |
| R2 | **[alto] Convivencia con tabla snapshot `cuentas_corrientes_proveedores`**: dos fuentes de verdad durante v1. | Confusión de usuarios, números que no cuadran entre ambas vistas. | UI deja claro cuál es el "libro propio" vs el "snapshot ERP". Endpoint del snapshot queda read-only. Plan de deprecación documentado. **Criterio de deprecación**: la tabla snapshot `cuentas_corrientes_proveedores` se deprecará en change aparte cuando se cumplan TODOS estos criterios: **(a)** libro mayor propio lleve 30+ días en producción sin divergencias detectadas contra snapshot en reconciliación diaria; **(b)** al menos 80% de proveedores activos tengan movimientos cargados en el libro mayor nuevo; **(c)** usuarios clave aprueben la deprecación tras revisar reportes de ambas fuentes. El change de deprecación incluirá migración de datos históricos si aplica. |
| R3 | **[medio] Complejidad de la tabla `imputaciones` unificada**: `origen_tipo`/`destino_tipo` abiertos a VARCHAR. | Inconsistencias si se agregan tipos sin cuidado. | Validación a nivel servicio (whitelist de combos válidos) + índice compuesto + tests unitarios cubriendo cada combo de v1. **Combos válidos en v1 (whitelist en servicio)**: `(orden_pago, pedido_compra)` ✅, `(orden_pago, factura_erp)` ✅, `(orden_pago, saldo)` ✅, `(nota_credito_erp, pedido_compra)` ✅, `(nota_credito_erp, factura_erp)` ✅, `(nota_credito_erp, saldo)` ✅. Cualquier combo fuera de esta lista → HTTP 400 con mensaje `"Combinación origen/destino no soportada en v1"`. La whitelist vive en `app/services/imputaciones_service.py` como constante `COMBOS_VALIDOS_V1`. v2 extiende la lista sin tocar schema. |
| R4 | **[medio] Colisión con el `incremental` vs el `guid` sync**: el archivo `sync_commercial_transactions_incremental.py` existe pero **no** está en cron. El cron activo es `sync_commercial_transactions_guid.py`. | Si enganchamos al archivo equivocado, el matching nunca corre. | Confirmado en explore (#103): hook al final de `sync_commercial_transactions_guid.py`. Test de integración que valide que el matching ocurre. |
| R5 | **[medio] `etiquetas_envio` históricamente diseñada para cliente**: extender con columnas nullable requiere backfill mínimo + frontend que respete `tipo_envio`. | Frontend de TabEnviosFlex rompe si asume `cliente_id NOT NULL`. | Default `tipo_envio='cliente'` en migración. Auditar queries existentes de TabEnviosFlex. Backfill de filas existentes con `tipo_envio='cliente'`. |
| R6 | **[medio] Multi-moneda en libro mayor**: cada movimiento guarda moneda original + TC. Saldo se agrupa por moneda en UI. | Usuarios pueden querer "saldo consolidado en ARS al TC de hoy" y confundirlo con saldo real por moneda. | UI muestra claramente el saldo por moneda como fuente de verdad; la conversión a ARS es vista secundaria etiquetada "estimado al TC de hoy". |
| R7 | **[bajo] `SELECT FOR UPDATE` en `numeracion_contadores`**: lock pesimista. | Bajo carga concurrente (varios PMs aprobando a la vez) puede serializar. | Lock solo durante el INSERT de la entidad numerada, transacción corta. Monitoring de locks en `pg_stat`. Volumen esperado bajo (pedidos/OPs/día). |
| R8 | **[bajo] Permisos críticos nuevos (`aprobar_ordenes_compra`, `ejecutar_pagos`)**: hay que asignarlos a los usuarios adecuados. | Si no se configuran, nadie puede aprobar ni pagar → bloqueo operativo. | Seed de permisos en migración + documento de onboarding que explica a quién asignar. Migración **NO** los asigna por default a ningún rol. |
| R9 | **[medio] `sd_id=106` es "Orden de Pago" en el ERP — reconciliación bidireccional queda para v2**. Cuando se paga una OP en el pricing-app, termina reflejándose en el ERP como una transacción con `sd_id=106`. Esto crea ambigüedad: el libro mayor recibirá OPs creadas en pricing-app Y OPs registradas directo en ERP. | Sin reconciliación, el contador puede imputar 2 veces el mismo pago (una por la OP local, otra por la ct ERP). | **v1 (mitigación)**: LEEMOS estas transacciones del ERP para que impacten el libro mayor de CC (haber), y **documentamos explícitamente** que el libro mayor puede recibir TANTO OPs creadas en pricing-app COMO OPs registradas directo en ERP. La conciliación manual queda bajo responsabilidad del usuario hasta v2. **v2 (diferido)**: reconciliación bidireccional asociando nuestras OPs locales (`OP-01-2026-00042`) con las `ct_transaction` del ERP para detectar divergencias y evitar doble-contabilización. |
| R10 | **[alto] Detección correcta de anulaciones y contrapartes del ERP**. El ERP no borra transacciones: cuando se anula una factura, crea 2 asientos nuevos: (1) asiento anulación (`sd_id` par con `sd_isAnnulment=true`: 151, 152, 153, 154, 156, 180); (2) asiento contraparte (`sd_id` terminado en 1: 161, 162, 163, 164, 166, 190). **Ejemplo real observado en JUKEBOX**: `ct_docnumber=00389000` con `sd_id=101` + `sd_id=151` + `sd_id=161`, mismo total. NO son duplicados, son 3 asientos de la misma transacción anulada. | Si no filtramos correctamente, la CC proveedor muestra facturas duplicadas o muestra facturas pagadas como pendientes. CRÍTICO para integridad de datos financieros. | **(a)** Vista SQL `v_facturas_compra_vigentes` que filtra: excluye `sd_isAnnulment=true`, excluye contrapartes (por `hacc_group` correspondiente), excluye facturas que tienen anulación posterior con mismo `(supp_id, ct_docnumber)`. **(b)** Tests de integración con fixtures de los 3 escenarios: factura sola / factura anulada / factura normal + contraparte. **(c)** Documentar en `sale_document_classifier.py` cómo identificar contrapartes (heurística: comparar `hacc_group` y `sd_plusOrminus` invertido vs documento base). |

---

## Dependencies

- **Tablas ERP sincronizadas**: `tb_commercial_transactions` debe estar al día. Cron `sync_commercial_transactions_guid` en verde (check previo al apply).
- **Módulo Cajas**: `CajaMovimiento` + `CajaDocumento` polimórfico (`entidad_tipo`/`entidad_id`) ya operativos. Confirmado en explore.
- **Módulo Proveedores**: `proveedor` + `proveedor_direccion` con datos reales. Confirmado.
- **Módulo Empresas**: vínculo a Cajas por `empresa_id`. Confirmado.
- **TabEnviosFlex (etiquetas_envio)**: tabla existente, se extiende. Coordinación con equipo de logística para no romper queries existentes.
- **Tabla `tipo_cambio`**: histórico diario USD, patrón "fecha <= X ORDER BY DESC LIMIT 1" ya estándar. Reuso directo.
- **Sistema de permisos**: `permiso` (155, 156) ya existentes. Agregar 2 nuevos es migración simple.

---

## Definition of Done v1

El módulo se considera completo cuando:

### Funcionalidad end-to-end
- [ ] Un PM puede crear pedido → aprobador aprueba → se genera OP → se ejecuta pago → impactos correctos en Caja + CC proveedor, todo auditado en `pedido_compra_eventos`.
- [ ] El rechazo de pedido vuelve a borrador o cancela (dos caminos explícitos, ambos auditados).
- [ ] El matching ERP funciona bidireccional (pedido→factura y factura→pedido) para proveedor piloto JUKEBOX con `sd_id` clasificados correctamente.
- [ ] Una factura ERP anulada (`sd_isAnnulment=true`) NO aparece en el dropdown de facturas pendientes ni impacta CC.
- [ ] CC del proveedor piloto muestra saldo correcto POR MONEDA (USD y ARS separados).
- [ ] Imputación a cuenta funciona: OP de $10.000 sin items, botón "Distribuir automáticamente" FIFO aplica contra facturas pendientes y deja remanente como saldo.
- [ ] Re-imputación diferida funciona: imputación ya aplicada puede reasignarse a otro destino.
- [ ] Una OP con `requiere_envio=true` genera etiqueta en TabEnviosFlex con `tipo_envio='retiro_proveedor'` usando datos de `proveedor.direcciones`.

### Integraciones
- [ ] Al pagar OP → se crea `CajaMovimiento` egreso + `CajaDocumento` con `entidad_tipo='orden_pago'` + `entidad_id` correcto.
- [ ] Al aprobar pedido → se inserta movimiento debe en `cc_proveedor_movimientos`.
- [ ] Al cancelar pedido aprobado → se inserta movimiento de reverso (haber) tipo ajuste.
- [ ] Sync de `tb_sale_document` corre y popula la tabla con los 43+ registros conocidos.
- [ ] Clasificador de documentos pasa tests unitarios para cada `sd_id` observado (101, 102, 103, 104, 106, 121, 123, 124, 125, 128, 129, 130, 131, 132, 133, 151, 156, 161, 166).

### Permisos
- [ ] Permisos nuevos (`aprobar_ordenes_compra`, `ejecutar_pagos`) creados en migración.
- [ ] Ningún rol los recibe por default — se asignan manualmente vía admin.
- [ ] Seguridad: un usuario con `ver_ordenes_compra` pero sin `gestionar_ordenes_compra` NO puede crear pedidos.

### Testing
- [ ] Tests unitarios de state machine de pedidos (7 estados, todas las transiciones válidas e inválidas).
- [ ] Tests de integración del matching ERP con fixtures de JUKEBOX (factura sola, factura anulada, factura con contraparte).
- [ ] Tests del clasificador de sale documents con los 43 `sd_id` conocidos.
- [ ] Tests de whitelist de combos de imputaciones (válidos → OK, inválidos → 400).
- [ ] Tests de numeración bajo concurrencia (2 requests simultáneos no generan duplicados).

### Documentación
- [ ] README del módulo con diagramas de flujo de pedido/OP/imputación.
- [ ] Documento de onboarding para asignar permisos críticos.
- [ ] Plan de deprecación de snapshot CC (change futuro con criterios de R2).
- [ ] Guía para usuarios: cómo armar una OP, cómo imputar a cuenta, cómo distribuir automático.

---

## Next Steps

1. **sdd-spec** → delta specs por capability (pedidos, ops, imputaciones, cc-mayor, erp-matching, logistica-retiro, cajas-op, numeracion, sale-document-catalog).
2. **sdd-design** → decisiones técnicas (estructura de índices, validaciones de estado machine, contratos de integración).
3. **sdd-tasks** → breakdown por batches (modelos, migraciones, endpoints, frontend, cron hook, tests).
4. **sdd-apply** → implementación en batches.
5. **sdd-verify** → validación contra specs + QA con dato real (proveedor JUKEBOX como caso piloto).

# Vista `v_facturas_compra_vigentes` — lookup por fila sin escanear todo

## Objetivo

Que una consulta a `v_facturas_compra_vigentes` filtrada por `ct_transaction`
(o por cualquiera de los patrones reales de los callers) toque solo las filas
relevantes, con **resultados idénticos** a la vista actual.

## Problema

Medido en producción 2026-10-05: la vista es el mayor consumidor de CPU. El
lookup de una sola fila `WHERE v.ct_transaction = :ct`
(`erp_matching_service.py`, una vez por factura dentro del loop de
`app.scripts.sync_commercial_transactions_guid`) corre como query paralela
usando ~3 de los 4 cores, porque la vista (compras_014):

- materializa el CTE `contrapartes`: un self-join de TODAS las filas de compra
  de `tb_commercial_transactions`, y filtra con
  `ct_transaction NOT IN (SELECT ct_transaction FROM contrapartes)`;
- arma un CTE `anuladas` con `DISTINCT` sobre todas las anulaciones.

`base` se referencia tres veces, así que Postgres lo materializa y un filtro
sobre `ct_transaction` no puede bajar a esos CTEs. Una query de matching llegó
a tardar 7+ minutos.

## Por qué

Es el job de sync de transacciones comerciales: corre seguido, una vez por
factura, y se come el servidor entero.

## Alcance autorizado

- Nueva migración Alembic: índice `(supp_id, ct_docnumber)` en
  `tb_commercial_transactions` (CONCURRENTLY, maneja INVALID) +
  `CREATE OR REPLACE VIEW` con la misma lista de columnas.
- Tests Postgres nuevos (paridad + performance + migración).
- NADA de código de callers (el módulo compras tiene otro dev activo).

## Callers y sus patrones

| # | Caller | Patrón |
|---|--------|--------|
| A | `erp_matching_service._buscar_ct_vigente` | `WHERE comp_id AND bra_id AND supp_id AND ct_docnumber LIMIT 2` |
| B | `erp_matching_service` (loop post-sync) | `WHERE ct_transaction = :ct` |
| C | `pedidos_service._buscar_ct_vigente_para_proveedor` | `WHERE ct_transaction = :ct AND supp_id = :s LIMIT 1` |
| D | `GET .../proveedores/{id}/facturas-erp-vigentes` (`administracion_compras.py`) | `WHERE supp_id [AND curr_id_transaction = n] ORDER BY ct_date DESC NULLS LAST, ct_transaction DESC LIMIT 200` |
| E | `GET .../pedidos/{id}/facturas-candidatas` (`administracion_compras.py`) | `WHERE supp_id AND ct_transaction NOT IN (pedidos_compra...) ORDER BY ... LIMIT 100` |
| F | docs/checklist post-deploy | `SELECT count(*)` sin filtro |

`imputaciones_service.py` solo la nombra en un docstring (la parte (b) es un
TODO, no consulta la vista).

## Equivalencia semántica (por qué es la misma vista)

- `anuladas` LEFT JOIN + `a.supp_id IS NULL` → `NOT EXISTS` correlacionado
  sobre `(supp_id, ct_docnumber)` contra filas cuyo `sd_isannulment` es TRUE.
  `anuladas.supp_id` está filtrado `IS NOT NULL`, así que el `IS NULL` del
  LEFT JOIN solo es verdadero cuando no hubo match: es un anti-join exacto. El
  `DISTINCT` evitaba duplicar filas; `NOT EXISTS` nunca duplica. Igual que el
  original, la anulación NO se restringe a compras ni a `ct_kindof`.
- `NOT IN (SELECT ct_transaction FROM contrapartes)` → `NOT EXISTS` contra otra
  fila que cumple los MISMOS filtros de `base`. `NOT IN` y `NOT EXISTS` solo
  difieren si la subconsulta puede devolver NULL; `ct_transaction` es la PK
  (NOT NULL), así que son equivalentes. Las igualdades sobre
  `comp_id/bra_id/hacc_group/sd_plusorminus` con NULL dan NULL (no match) en
  ambos casos: una fila con `hacc_group` NULL nunca es contraparte.
- La contraparte se evalúa contra `base` SIN el filtro de anuladas (igual que
  el original). Como ambas comparten `(supp_id, ct_docnumber)` el resultado
  sería el mismo de todos modos.
- `tb_sale_document.sd_id` es PK, así que el JOIN no multiplica filas y la
  evaluación por fila de `NOT EXISTS` coincide con el `NOT IN` por
  `ct_transaction`.
- Mismas columnas, mismo orden, mismas expresiones → `CREATE OR REPLACE VIEW`
  alcanza (no hace falta DROP; ninguna otra vista/función depende de esta).

## TDD

- Modo: Strict TDD (configuración de sesión del usuario).
- Runner: `backend/venv/bin/python -m pytest` (venv de pricing-app-5),
  Postgres de tests `POSTGRES_TEST_URL` (default `pricing_test`).

## Tareas

- [x] T1 — Migración `20261005_vfactvig_lookup` (índice
  `ix_tb_commercial_transactions_supp_docnumber` + `CREATE OR REPLACE VIEW`) y
  `backend/tests/unit/test_v_facturas_compra_vigentes_postgres.py` (paridad,
  planes/tiempos por patrón, mecánica de la migración). Ruta: inline
  (1 migración + 1 test, problema ya entendido; el mapeo de callers fueron
  5 lecturas puntuales).
- [x] T2 — Checks: ruff format/check, pytest focalizado, suite backend completa
  una vez (ver Evidencia).

## Evidencia

### RED (migración nueva con la definición de compras_014, antes de reescribir)

`pytest -k "TestPlans and not report or TestMigration"` → 8 failed / 4 passed:
los 6 patrones de callers fallaron (B: `Gather` + `Parallel Seq Scan` sobre
`tb_commercial_transactions`; A/C/D/E: 215–290 ms, leyendo ~161k filas, todas
las compras). La corrida completa con la definición vieja ni terminó: el test
de lookups por `ct_transaction` (~12k lookups) llevaba 10 min y lo corté.

### GREEN — paridad (Postgres de tests, 612k filas sembradas)

- `old EXCEPT ALL new` = 0 y `new EXCEPT ALL old` = 0 sobre el dataset completo.
- Mismas columnas, nombres, tipos y orden (`pg_attribute`).
- El dataset ejerce cada exclusión en la vista vieja: >1.000 filas base
  anuladas, >10.000 contrapartes, >100 grupos de 3+ filas (triples).
- 42 casos a mano con veredicto explícito (anulación de compra y de VENTA,
  pares en ambos órdenes de sd_id, triple, hacc_group NULL, comp_id NULL,
  distinto comp/bra/proveedor, 'X'/'x'/NULL, remito, presupuesto, supp/doc
  NULL, sd_id NULL o fuera del catálogo, contraparte de una fila 'X') — vieja
  y nueva dan exactamente lo esperado.
- ~12.1k lookups `WHERE ct_transaction = X` sobre la vista nueva (todos los
  ct del bloque denso + muestra del volumen, presentes y ausentes) coinciden
  fila a fila con el resultado completo de la vieja.
- Dev DB (copia real, 415k filas, 1.946 vigentes), TEMP VIEW en transacción
  con rollback: `old EXCEPT ALL new` = 0, `new EXCEPT ALL old` = 0.

### Tiempos old → new por patrón de caller

Postgres de tests, 600k filas de volumen (150k compras), con el índice nuevo:

| Patrón | Old | New | Filas de ct leídas old → new |
|--------|-----|-----|------------------------------|
| B `ct_transaction = X` (en la vista) | 260 ms, Gather + Parallel Seq Scan | 0.06 ms | 773.266 → 3 |
| B `ct_transaction = X` (contraparte, fuera) | 249 ms, Gather + Parallel Seq Scan | 0.05 ms | 161.225 → 2 |
| C `ct_transaction AND supp_id LIMIT 1` | 215 ms | 0.06 ms | 161.415 → 3 |
| A `comp/bra/supp/docnumber LIMIT 2` | 234 ms | 0.06 ms | 161.226 → 3 |
| D `supp_id [+curr] ORDER BY ct_date LIMIT 200` | 244 ms | 0.73 ms | 161.415 → 429 |
| E `supp_id + NOT IN vinculadas ... LIMIT 100` | 249 ms | 1.06 ms | 161.415 → 549 |
| F `count(*)` sin filtro | 314 ms, paralela | 195 ms | (hash anti-join; no regresa) |

Dev DB (datos reales, SIN el índice nuevo, solo los índices existentes):
B 39 → 0.09 ms, B fuera 20 → 0.04 ms, C 43 → 0.09 ms, A 23 → 0.17 ms,
D 49 → 20 ms (con el índice nuevo D es sub-ms), F 45 → 30 ms.

E se midió con `NOT IN (VALUES ...)` en lugar de la subconsulta a
`pedidos_compra` (esa tabla no existe en la DB de tests); la parte que toca la
vista es la misma.

### Checks

- `ruff format` / `ruff check` sobre los archivos tocados: OK.
- pytest focalizado (compras, erp matching, pedidos, imputaciones, órdenes de
  pago, CC proveedor, clasificador, jukebox, vista SQLite, todos los
  `test_migration_*` + el nuevo): 879 passed, 4 skipped.
- Suite backend completa: ver commit/reporte.

## Notas

- Los tests SQLite (`test_v_facturas_compra_vigentes.py`,
  `test_erp_matching_service.py`, `test_pedidos_vincular_factura.py`,
  `test_compras_vincular_factura_endpoints.py`) siguen copiando la definición
  vieja: devuelven las mismas filas, así que no se tocaron (diff mínimo, el
  módulo compras tiene otro dev activo). La paridad contra Postgres es la
  fuente de verdad.
- No se tocó código de callers: todos los patrones quedan servidos.

## Próximo paso

PR (decisión del usuario: no se pushea).

# Rebuild de `tplink_ventas_metricas` (dual-key dedup fix)

**Fecha:** 2026-07-10
**Estado:** Pendiente de ejecución — bloqueado en merge de PR #887 (slice 2) y PR #888/slice 3
**Relacionado:** SDD change `tplink-metricas-dual-key-dedup` (design obs 859, PRs #884/#887/#888)

---

## Objetivo

`tplink_ventas_metricas` tenía dos bugs estructurales:

1. **Dual-key duplication**: el job incremental usaba `DISTINCT ON (tmlod.mlo_id)` y colapsaba
   órdenes multi-item a UN SOLO detalle (perdiendo montos), mientras que el backfill escribía
   una fila por detalle (perdiendo la garantía "una fila por orden"). Ambos jobs también
   divergían en la construcción de `mla_id`.
2. **Fechas mal acotadas**: filtros `BETWEEN` con bordes de fecha "pelados" (medianoche) que
   perdían ventas del mismo día después de las 00:00.

El fix (slices 1-3) reemplaza ambos jobs por wrappers finos sobre un único pipeline compartido
(`app/scripts/_tplink_metricas_core.py`) que:
- Trae TODOS los detalles por orden (sin `DISTINCT ON`) y los pliega en Python, SUMANDO
  `monto_total`, `costo`, `comisión`, `ganancia` por orden, aplicando el envío UNA sola vez.
- Usa bordes de fecha semi-abiertos (`>= from_ts AND < to_ts`) sobre `tmloh.mlo_cd`.
- Comparte la función `id_operacion=mlo_id` / `ml_order_id=str(ml_id)` / `mla_id=str(mlp_id)`
  entre backfill e incremental — estructuralmente imposible que diverjan.

Este runbook purga las filas duplicadas/obsoletas de la tabla y la reconstruye bajo el nuevo
contrato de una-fila-por-orden.

---

## Orden de ejecución

1. **Mergear PR #887** (slice 2 — wiring de ambos jobs sobre el core compartido + índice
   `mlo_cd`) y **PR #888** (slice 3 — este runbook + tests Postgres) a `main`.
2. **Deploy** del código a producción (según el proceso estándar del repo).
3. **`alembic upgrade head`** — aplica la migración
   `20260710_add_index_mlo_cd_orders_header.py`, que crea el índice sobre
   `tb_mercadolibre_orders_header.mlo_cd` usando `CREATE INDEX CONCURRENTLY` (no bloquea
   escrituras en la tabla, que recibe writes cada 5 min vía el cron incremental de ML).
4. **`TRUNCATE tplink_ventas_metricas`** — ver sección Seguridad más abajo.
5. **Backfill completo**:
   ```bash
   cd /var/www/html/pricing-app/backend
   source venv/bin/activate
   python -m app.scripts.agregar_metricas_tplink --from-date 2026-01-01 --to-date $(date +%Y-%m-%d)
   ```
   `--from-date 2026-01-01` es la fecha más temprana confirmada por el usuario para el rebuild
   (no hace falta ir más atrás).
6. **Confirmar que el cron incremental de 5 minutos retoma sobre el código nuevo** — no requiere
   cambios de configuración (mismo comando, mismo entrypoint), solo confirmar en los logs
   (`/var/log/pricing-app/` o el path configurado) que las corridas post-deploy usan el wrapper
   nuevo (sin `DISTINCT ON` en el SQL logueado, si el log incluye la query).

---

## Seguridad del TRUNCATE

- `tplink_ventas_metricas` es **dato 100% derivado**: se recalcula íntegramente a partir de
  `tb_mercadolibre_orders_header`/`_detail`/`_shipping`, `tb_item_cost_list(_history)` y
  `tipo_cambio`. No es fuente de verdad de nada.
- **No tiene FKs entrantes** — ninguna otra tabla referencia sus filas por `id`. Truncarla no
  puede romper integridad referencial en otra tabla.
- El backfill es **idempotente** (upsert por `id_operacion`), así que si el rebuild se corta a
  mitad de camino, re-correr el mismo comando completa lo que falte sin duplicar filas.
- **Recomendado**: ejecutar en horario de bajo tráfico. Mientras la tabla está vacía (entre el
  TRUNCATE y que el backfill complete), el dashboard TP-Link mostrará datos incompletos/vacíos
  para el rango truncado — el cron incremental de 5 min seguirá alimentando ventas nuevas en
  paralelo sin conflicto (dedupe por `id_operacion`).

---

## Verificación post-rebuild

Comparar, para una ventana de muestra (ej. una semana reciente), el **conteo de órdenes** de
TP-Link (store 2645) contra ML filtrado a la misma tienda:

```sql
-- TP-Link (post-rebuild)
SELECT COUNT(*) AS ordenes, SUM(monto_total) AS facturacion
FROM tplink_ventas_metricas
WHERE fecha_venta >= '2026-06-01' AND fecha_venta < '2026-06-08';

-- ML filtrado a store 2645 (misma ventana)
SELECT COUNT(DISTINCT id_operacion) AS ordenes, SUM(monto_total) AS facturacion
FROM ml_ventas_metricas
WHERE mlp_official_store_id = 2645
  AND fecha_venta >= '2026-06-01' AND fecha_venta < '2026-06-08';
```

**Esperado:**
- El **conteo de órdenes** (`COUNT`) debe **coincidir** entre ambas tablas — ese es el contrato
  fijo (una fila por orden) que este fix garantiza.
- La **facturación** (`SUM(monto_total)`) puede **divergir levemente y de forma esperada**: TP-Link
  ahora SUMA correctamente el monto de todos los detalles de una orden multi-item, mientras que
  ML sigue usando `DISTINCT ON` (colapsa a un solo detalle representativo). Para órdenes de un
  solo ítem (el caso común), ambos valores deben ser idénticos. Esta divergencia es intencional
  y NO es un bug — está documentada en el diseño (obs 859, decisión D1).

---

## Follow-up conocido, no bloqueante

`cambio_momento` (y por lo tanto `cotizacion_dolar`) no tiene fallback si ambas ramas del
`COALESCE` de costo (histórico `tb_item_cost_list_history` y actual `tb_item_cost_list`) no
matchean — en ese caso queda `None`. Es un gap preexistente a este fix (ver ledger de
judgment-day de slice 2, hallazgo RR2-004), no introducido por este cambio. Ticketear por
separado si se decide resolver.

# Ventas ML: la base del "% de varios" suma el envío que entra (y backfill único)

**Creado:** 2026-10-07 · **Estado:** implementado, pendiente de confirmación de la regla de bonificación (2 muestras)
**TDD:** estricto (config de sesión) · **Runners:** `cd backend && .venv/bin/python -m pytest` / `cd frontend && pnpm test`
**Estrategia de entrega:** `ask-on-risk` · **Rama base:** `origin/main` (`12e82949`, incluye #1415) · **Rama:** `feat/ventas-ml-varios-base-envio`
**Ruta por tarea:** todo inline en una sola sesión de escritor delegado (un único writer, sin SDD).

## Objetivo

La base del "% de varios" pasa de "operación sin IVA" a:

> operación sin IVA + (envío que pagó el comprador + bonificación Flex de ML) / 1,21

Y el historial se recalcula UNA sola vez (reglas de #1415 y de esta PR) subiendo
`CURRENT_FORMULA_VERSION`.

## Problema

`VariosDeduccion` (`deducciones.py`, `base = "venta_sin_iva"`, diseño D4 de ml-ventas-neto-iibb-varios)
aplica el % solo sobre los bienes sin IVA. Regla confirmada por el usuario: "lo que facturamos, después
pagamos IIBB". El envío que el comprador paga también se factura, entonces entra en la base.

## Reglas confirmadas por el usuario

- Base = bienes sin IVA + envío del comprador sin IVA + bonificación Flex sin IVA.
- Envío **BRUTO** facturado, aunque después ML lo cobre de vuelta (+990 / -990 en `shp_*`): el cargo
  `shp_*` sigue restándose como hoy; la base usa el envío bruto, nunca el neto después del cargo.
- El IVA del envío NO se resta como gasto: es informativo.
- Envío desglosado `{bruto, neto, iva}` con la misma forma que #1415 (`ImporteDesglosadoSummary`).
- Nada más de la cadena cambia.

## Evidencia (captura real, sin inventar)

`ml-captures/buyer_shipping_capture_20261007_142537.json` (fixture recortado, sin datos personales, en
`backend/tests/fixtures/ml_ventas_envio_comprador/`) y los paneles de ML que pegó el usuario.

### Fuente del envío que pagó el comprador: `payment.shipping_amount` (UNA sola fuente)

Decisión del usuario/coordinador: el desglose debe asumir lo mínimo, y `shipping_amount` es el campo que
ML rotula como envío. Es el mismo que ya lee la línea visible "Envío cobrado al comprador" de `iva.py`, y
la base lo lee con el mismo helper (`envio_comprador_de_pago`) y la misma agregación: cada pago
RELEVANTE de la orden aporta una vez (un pago rechazado nunca), así que 3 pagos no triplican el envío.

Descartadas (en este orden de la discusión):

- `order.paid_amount - order.total_amount`: coincide con `shipping_amount` en las 7 capturas, pero es una
  inferencia que también capturaría un recargo financiero (cuotas con interés) u otra diferencia.
  Hay un test con un recargo en `paid_amount` que lo fija.
- `raw_costs.receiver.cost`: NO es confiable. En el pack Flex `2000018846584294` dice 2216,30 pero el panel
  de ML muestra "Anulación del cargo por Envíos de ML (a cargo del comprador)"; su `shipping_amount` es 0.
- `total_paid_amount - transaction_amount` del pago: en 2000018846969514 da 5107,54 porque incluye el
  `tax_withholding_payer` de 117,54.

| Orden | `shipping_amount` (pagos relevantes) | Envío |
|---|---|---|
| fulfillment 2000018844749424 | 990 | 990 |
| cross_docking 2000018847750422 | 4699,09 | 4699,09 |
| fulfillment 2000018847574430 | 3990 | 3990 |
| self_service 2000018846969514 | 4990 | 4990 |
| cross_docking 2000018846999192 | 0 + 5373,70 (el rechazado no cuenta) | 5373,70 |
| pack Flex 2000018846584294 | 0 | 0 (anulado) |
| 2000018814119064 | 0 | 0 |

Las 7 bases quedan IGUAL que con la diferencia `paid - total`.

### Bonificación (corrección de la regla de #1415)

La regla de #1415 (sumar todo `receiver.discounts`) era incorrecta para el pack Flex: el panel de ML
muestra "Bonificación por envío" $599 = `senders[0].discounts[mandatory].promoted_amount`; el
`receiver.discounts[ratio] 3773,7` es el subsidio de ML al COMPRADOR y no es ingreso del vendedor.
El caso 1 (`receiver.discounts[loyal] 8990`, `senders[0].discounts = []`) sigue bien.

Regla candidata (NO confirmada, descansa en 2 muestras de panel; se le piden más muestras al usuario):

`bonificación = Σ senders[].discounts[].promoted_amount + Σ receiver.discounts[type == "loyal"].promoted_amount`, solo Flex.

Un tipo de `receiver.discounts` que no sea `loyal` ni uno conocido como no-ingreso (`ratio`) NO suma y
deja un warning con el shipment id.

## Decisiones

- **D1. Dos fuentes, dos conceptos, sin doble conteo.** El envío del comprador sale de los PAGOS de la
  orden (`shipping_amount`); la bonificación sale de `raw_costs` del SHIPMENT, repartida por `shipping_id`
  (#1415). Ninguna lee a la otra. Pack Flex 2000018846584294: comprador 0 + bonificación 599. La
  bonificación se calcula en UN solo lugar (`resolve_bonificacion_flex_by_order_ids`) que consumen la
  línea de la cadena, el componente de IVA y la base de varios.
- **D2. Sin lookup de shipment para el comprador:** un shipment guardado bajo otra orden del pack (caso
  2000018814119064) no importa para el envío del comprador; sí para la bonificación, que ya lo busca por
  `shipping_id` (`resolve_modes`).
- **D3. N pagos:** misma agregación que la línea: un componente por pago relevante con envío, la base suma
  sus bases; no hay multiplicación por cantidad de pagos.
- **D4. Fail-closed = opción (a): suma 0 y deja log.** Un `shipping_amount` no numérico (string, bool,
  NaN/inf) o NEGATIVO no inventa base: aporta 0 y avisa con el `payment_id`; nulo aporta 0 y se loguea en
  debug (es lo normal en un pago sin envío). Justificación: es la política de #1415 ("ante la duda, nada y
  un log"); bloquear (b) dejaría `total_gauss` y el markup del pack en NULL (todo-o-nada) por un efecto de
  `% varios x envío / 1,21` (centenas de pesos). El `varios` sigue bloqueando solo cuando falta la base de
  BIENES, como hoy. Costo asumido: ante un dato corrupto la base queda corta, con log. Consecuencia en la
  línea visible: un `shipping_amount` negativo ya no entra al desglose (antes sí), por lo que la
  reconciliación del neto lo muestra como no reconciliado en vez de absorberlo.
- **D5. Dónde se ve:** la línea visible `Envío cobrado al comprador` ya existía en `iva.py` (bruto/base/IVA);
  no se agrega una segunda. Lo nuevo en la API: `iva_decomposicion.envio_comprador` `{bruto, neto, iva}`
  (forma `ImporteDesglosadoSummary`, para el libro IVA) y `iva_decomposicion.base_varios`.
  `base_venta_sin_iva` (bienes) queda intacta.
- **D6. La base se arma en `descomponer_neto`** (`DescomposicionNeto.base_varios`) de las MISMAS
  fuentes que muestran las líneas, no de `componentes`. `calcular_total_gauss` recibe
  `base_varios_by_order` (renombrado desde `venta_sin_iva_by_order`: el nombre ya mentía).
- **D7. Backfill = subir `CURRENT_FORMULA_VERSION` 2 -> 3**, como ULTIMO commit separado. It ships in
  this PR (user decision, 2026-10-07). Holding it does not hold the recompute: `order_metrics.divergence`
  walks every stored order and re-enqueues the ones that differ under the new formula, so without the
  bump history would be recomputed anyway, slowly, while opening thousands of `stored_metrics_mismatch`
  rows that are a rule change rather than errors. The bonificación rule was confirmed against ML's
  explicit billing line (`flex/details` CREDIT_NOTE `BONUS`/`BFLX`: 8990 and 599, both matching the
  panel). Switching the desglose to that explicit source belongs to the `ml-billing-balance` SDD and will
  need a second bump. Ver sección Backfill.

## Backfill (verificado)

- **Reconcile** (`order_metrics.reconcile`, cada 10 min): lotes de `RECONCILE_BATCH_SIZE = 5000`,
  SQL set-based por `get_background_db` (un bloque corto por lote), dentro del deadline de 30 s del
  handler. Encola con `order_metrics_enqueue_system` (`ON CONFLICT DO NOTHING`: no toca lo ya sucio ni
  desestaciona parked) y dispara `pg_notify`. Encolar es barato; el límite real es el drain.
- **Drain** (`order_metrics.drain`): `WORKER_BATCH_SIZE = 200` por claim, `WORKER_LEASE_SECONDS = 120`,
  `WORKER_BATCH_TIMEOUT_SECONDS = 60`, `statement_timeout = 30s` por compute, UN `get_background_db`
  corto por compute y cada orden se guarda en su propia transacción corta. Un handler corre hasta
  30 s (`DEFAULT_HANDLER_DEADLINE_SECONDS`) y se despierta por NOTIFY y cada 5 s (safety poll). Nunca
  mantiene más de una conexión a la vez: no repite el incidente de pool agotado de 2026-06-24.
  El ritmo real NO está medido (depende de la máquina de prod); se lee con la query de avance.
- **Divergencia** (`order_metrics.divergence`): salta las órdenes con fila sucia. Después del primer
  reconcile casi todo el backlog está sucio, así que no compara lo viejo. Aun si algo viejo no sucio
  se compara (ventana entre reconcile y reconcile), abre como máximo `DIVERGENCE_MAX_RECORDED_PER_RUN = 100`
  `stored_metrics_mismatch` por corrida, y los reencola (autocura). No inunda. Test:
  `TestBumpDoesNotFloodDivergence`.
  Cómo leer/silenciar: las filas abiertas con `detected_at` dentro de la ventana del backfill son
  esperadas; cuando la query de avance dé 0 filas con versión vieja, se pueden cerrar con el
  `resolved` normal del panel (si reaparecen, se reabren por diseño: ahí SÍ hay algo real).
- **Query de avance** (operador):

```sql
SELECT formula_version, count(*) AS ordenes
FROM ml_order_metrics
GROUP BY formula_version
ORDER BY formula_version;
-- cola: SELECT count(*) FILTER (WHERE attempts >= 5) AS parked, count(*) AS en_cola FROM ml_order_metrics_dirty;
```

  Termina cuando no queda ninguna fila con `formula_version < 3`, la cola está vacía y
  `missing_metrics_count` de `GET /api/ml-ops/order-metrics/health` es 0.

## Tareas

- [x] T0 Documento + espejo en Engram (`odd/ventas-ml-varios-base-envio/tasks`)
- [x] T0b RED/GREEN: corrección de la regla de bonificación (senders + receiver `loyal`; unknown type no suma)
- [x] T1 RED/GREEN: `envio_comprador_de_pago` (fail-closed sobre `payment.shipping_amount`; RED: un recargo en `paid_amount` movía la base)
- [x] T2 RED/GREEN: línea y base comparten helper y agregación (varios pagos)
- [x] T3 RED/GREEN: `descomponer_neto` — `base_varios` (primer test: fixture 990/990, RED observado: AttributeError base_varios; luego 303,31 vs 319,67)
- [x] T4 RED/GREEN: `VariosDeduccion` usa `base_varios` (rename del kwarg, `compute.py` y tests)
- [x] T5 RED/GREEN: API `iva_decomposicion.envio_comprador` / `base_varios`
- [x] T6 RED/GREEN: casos capturados + pack Flex (599, comprador 0) + 3 pagos + sin doble conteo
- [x] T7 (ULTIMO commit, ships in this PR per user decision) RED/GREEN: `CURRENT_FORMULA_VERSION` = 3 + reconcile selecciona fila vieja + divergencia no inunda
- [x] T8 Frontend: novedad (no hay JSX nuevo: la línea visible de envío ya existía en la tabla de IVA); vitest `ventasMl` + novedades verde
- [x] T9 Runbook (backfill), lint, push, observaciones del GGA

## Chequeos

`pytest` sobre `tests/services/ml_ventas_desglose`, `tests/services/order_metrics`,
`tests/services/ml_group_metrics`, `tests/workers`, integración `ml_ventas_ops`; `pnpm test` sobre
`ventasMl`; `ruff check app/ tests/`, `ruff format app/ tests/ --check`, `pnpm run lint`, `pnpm run lint:css`.
No se corre la suite entera (la corre el CI).

## Evidencia

- T0b..T6: `pytest tests/services/ml_ventas_desglose tests/services/order_metrics tests/services/ml_group_metrics
  tests/workers tests/integration/test_ml_ventas_ops*.py` -> 1154 passed (antes del bump de versión).
- Commits: ver `git log origin/main..HEAD`. El bump (T7) es el ULTIMO commit y puede descartarse sin tocar el resto
  (la novedad dice que el historial se recalcula: si se descarta, ajustar ese bullet).
- T7: reconcile selecciona una fila v2 con el bump (RED observado: `assert 2 == 3`); lotes de 40 sobre 100 filas = 3 lotes;
  divergencia: con el backlog ya encolado compara 0 y abre 0; sin encolar, abre como máximo 100 por corrida
  (`TestBumpDoesNotFloodDivergence`). `ml_group_metrics` se recalcula como efecto de guardar la orden.
- Verificación final: pytest (desglose, order_metrics, ml_group_metrics, workers, integración ml_ventas_ops) verde;
  `ruff check/format` limpios; `pnpm run lint` 0 errores (2 warnings preexistentes), `lint:css` limpio.

## Próximo paso

Que el usuario confirme la regla de bonificación con más muestras de panel; recién ahí mergear con el commit de bump.

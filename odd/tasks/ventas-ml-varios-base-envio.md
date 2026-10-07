# Ventas ML: la base del "% de varios" suma el envío que entra (y backfill único)

**Creado:** 2026-10-07 · **Estado:** en curso
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

### Fuente del envío que pagó el comprador: `order.paid_amount - order.total_amount`

`raw_costs.receiver.cost` NO es confiable (corrección del coordinador): en el pack Flex
`2000018846584294` (pack `2000015400388457`) `receiver.cost` dice 2216,30, pero el panel de ML muestra
"Anulaciones -$2.216,30, Anulación del cargo por Envíos de ML (a cargo del comprador)": el comprador NO
lo pagó al final, y nuestros datos lo confirman (`paid_amount` 105998 = `total_amount` 105998; pago
`total_paid_amount` = `transaction_amount`). Se usa la plata que efectivamente entró:

| Orden | paid_amount - total_amount | Envío |
|---|---|---|
| fulfillment 2000018844749424 | 19340 - 18350 | 990 |
| cross_docking 2000018847750422 | 61598,09 - 56899 | 4699,09 |
| fulfillment 2000018847574430 | 48156 - 44166 | 3990 |
| self_service 2000018846969514 | 19590 - 14600 | 4990 |
| cross_docking 2000018846999192 | 42443,7 - 37070 | 5373,70 (3 pagos, con financiación) |
| pack Flex 2000018846584294 | 105998 - 105998 | 0 (anulado) |
| caso 1 2000018808335864 | 18857 - 18857 | 0 |

NO se usa `total_paid_amount - transaction_amount` del pago: en 2000018846969514 da 5107,54 porque
incluye el `tax_withholding_payer` de 117,54.

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

- **D1. Dos fuentes, dos conceptos, sin doble conteo.** El envío del comprador sale de columnas de la
  ORDEN (`paid_amount - total_amount`), por ORDEN, sin reparto: cada orden del pack trae lo suyo. La
  bonificación sale de `raw_costs` del SHIPMENT, repartida por `shipping_id` (#1415). Ninguna lee a la
  otra, así que no se pisan. Pack Flex 2000018846584294: comprador 0 + bonificación 599. La bonificación
  se calcula en UN solo lugar (`resolve_bonificacion_flex_by_order_ids`) que consumen la línea de la
  cadena, el componente de IVA y la base de varios.
- **D2. Sin shipment, sin lookup por pack.** Como la fuente es la orden, un shipment guardado bajo otra
  orden del pack (caso 2000018814119064) no importa para el envío del comprador; sí para la
  bonificación, que ya lo busca por `shipping_id` (`resolve_modes`).
- **D3. Varios 3 pagos / N pagos:** no multiplica, se lee de la orden, no del pago.
- **D4. Fail-closed = opción (a): suma 0 y deja log.** `paid_amount` o `total_amount` nulo, no
  numérico/no finito, o una diferencia NEGATIVA no inventan base: contribuyen 0 y avisan con el
  `order_id`. Si `receiver.cost` difiere de la diferencia se usa la diferencia y se loguea en debug
  (las anulaciones lo vuelven legítimo). Justificación: es la política de #1415 ("ante la duda, nada y
  un log"); bloquear (b) dejaría `total_gauss` y el markup del pack en NULL (el pack es todo-o-nada) por un
  efecto de `% varios x envío / 1,21` (centenas de pesos). El `varios` sigue bloqueando solo cuando falta la
  base de BIENES, como hoy. Costo asumido: ante un dato corrupto la base queda corta (margen
  levemente alto), con log. Cambiar a (b) es local a `descomponer_neto`.
- **D5. Dónde se ve:** componente informativo `Envío pagado por el comprador` en `iva.py`
  (mismo patrón que la bonificación: se muestra con su base/IVA al 21%, no entra en `neto_sin_iva`;
  0 = sin línea), más `iva_decomposicion.envio_comprador` y `iva_decomposicion.base_varios` en la API.
  `base_venta_sin_iva` (bienes) queda intacta.
- **D6. La base se arma en `descomponer_neto`** (`DescomposicionNeto.base_varios`) de las MISMAS
  fuentes que muestran las líneas, no de `componentes`. `calcular_total_gauss` recibe
  `base_varios_by_order` (renombrado desde `venta_sin_iva_by_order`: el nombre ya mentía).
- **D7. Backfill = subir `CURRENT_FORMULA_VERSION` 2 -> 3**, como ULTIMO commit separado y RETENIDO hasta que
  el usuario confirme la regla de bonificación con más muestras (el bump hace recalcular toda la
  historia con la regla vigente). Ver sección Backfill.
- **Riesgo anotado:** `paid_amount` también incluye cualquier recargo financiero del comprador (cuotas con
  interés) si existiera; no aparece en ninguna captura. Si apareciera se contaría como envío.

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
- [ ] T0b RED/GREEN: corrección de la regla de bonificación (senders + receiver `loyal`; unknown type no suma)
- [ ] T1 RED/GREEN: `envio_comprador_bruto` (fail-closed sobre `paid_amount - total_amount`)
- [ ] T2 RED/GREEN: `resolve_envio_comprador_by_order_ids` (por orden, sin reparto)
- [ ] T3 RED/GREEN: `descomponer_neto` — componente informativo + `base_varios` (primer test: fixture 990/990)
- [ ] T4 RED/GREEN: `VariosDeduccion` usa `base_varios` (rename del kwarg, `compute.py` y tests)
- [ ] T5 RED/GREEN: API `iva_decomposicion.envio_comprador` / `base_varios`
- [ ] T6 RED/GREEN: casos capturados + pack sin doble conteo + 3 pagos + shipment bajo otra orden
- [ ] T7 (ULTIMO commit, retenido hasta confirmación) RED/GREEN: `CURRENT_FORMULA_VERSION` = 3 + reconcile selecciona fila vieja + divergencia no inunda
- [ ] T8 Frontend: test de vitest del componente informativo + novedad
- [ ] T9 Runbook (backfill), lint, push, observaciones del GGA

## Chequeos

`pytest` sobre `tests/services/ml_ventas_desglose`, `tests/services/order_metrics`,
`tests/services/ml_group_metrics`, `tests/workers`, integración `ml_ventas_ops`; `pnpm test` sobre
`ventasMl`; `ruff check app/ tests/`, `ruff format app/ tests/ --check`, `pnpm run lint`, `pnpm run lint:css`.
No se corre la suite entera (la corre el CI).

## Evidencia

(se completa por tarea)

## Próximo paso

T0.

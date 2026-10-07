# Ventas ML: la bonificación por envío entra en el neto de ML, no en la cadena del Total Gauss

**Creado:** 2026-10-07 · **Estado:** en curso
**TDD:** estricto (config de sesión) · **Runners:** `cd backend && .venv/bin/python -m pytest` / `cd frontend && pnpm test`
**Estrategia de entrega:** `ask-on-risk` · **Rama base:** `origin/main` (`0d1ad051`, incluye #1415 y #1417) · **Rama:** `fix/ventas-ml-bonificacion-en-neto`
**Ruta por tarea:** un único writer en el worktree `bonif-en-neto`, todo inline (sin SDD).

## Objetivo

La "Bonificación por envío" de ML (Flex) es plata que ML paga por la operación. Debe formar parte del **neto
de ML** (lo que ML paga y cobra por la venta), no ser una deducción de la cadena del Total Gauss.

> Dueño: "Está bien la cuenta pero visualmente no está tan bien, porque la estás sumando directo al costo
> gauss y en realidad tendría que entrar en la parte del neto de ML, porque entra por la operación."

## Problema

#1415 / #1417 la meten como deducción NEGATIVA (`BonificacionEnvioDeduccion`, neto de IVA) y el IVA como
componente `informativo` en `iva.py`. La plata final del Total Gauss es correcta; la presentación no.

## Alcance

1. `neto` (stored + detalle + KPI + pack) incluye la bonificación BRUTA. `neto_sin_iva` incluye su base.
2. El IVA de la bonificación es un componente real (no `informativo`) del desglose de IVA.
3. La reconciliación del IVA sigue EXACTA: el tramo del pago se reconcilia contra `net_received_amount`
   (igual que hoy); la bonificación es un componente explícito, fuera del pago, que se suma aparte.
4. El **Total Gauss final es EXACTAMENTE el mismo** en todos los casos capturados.
5. La base del "% de varios" cuenta la bonificación UNA sola vez.
6. API y panel: la línea "Bonificación por envío" va dentro de la sección del neto, con bruto/neto/IVA.
7. `CURRENT_FORMULA_VERSION` 3 -> 4 como ÚLTIMO commit, con su test de reconcile.
8. Novedad en `frontend/src/novedades` en la MISMA PR.

Fuera de alcance: cambiar la regla de qué es bonificación (sigue siendo la de #1417), tocar el trigger de
`raw_costs`, el historial se recalcula por el bump (no hay backfill manual).

## Decisiones

- `neto_depositado` (tooltip del listado) sigue siendo lo que ML depositó (pago, sin SIRTAC): la
  bonificación NO está en el pago. Se expone aparte (`bonificacion_envio`) para que el tooltip cierre con el neto.
- `breakdown_service` no puede importar `bonificacion_flex` a nivel módulo (ciclo): import local.
- El tooltip del listado muestra la bonificación solo si el neto guardado la confirma: la fila está
  asentada (`ok`/`provisional`) y `neto == neto_depositado + retenciones_recuperables + bonificación en vivo`
  al centavo. Si no cierra (fila esperando recálculo, neto guardado con la fórmula 3, deriva de centavos) es
  `None`, nunca un residuo inventado; una venta asentada sin bonificación da 0.
- Borde conocido: si un hermano de un pack no tiene pagos relevantes, su parte de la bonificación no entra en
  ningún neto (regla "sin pago no hay neto"); la suma del pack queda corta hasta que ese pago exista. Es
  coherente con `compute_neto_by_order_ids` (el neto de esa orden es `None`) y no se parchea con un reparto ad hoc.
- La línea del panel es una `BreakdownLine` con `monto` NEGATIVO (un cargo negativo suma: el panel ya lo
  dibuja como `(+)`), `origen="bonificacion"`.

## Checklist

- [x] T1 RED: el fixture 2000018808335864 espera neto +8990, neto_sin_iva +7429,75 y el MISMO Total Gauss (falla hoy).
- [x] T2 GREEN backend: neto / breakdown / IVA / cadena (la bonificación sale de `DEDUCCIONES`).
- [x] T3 pin del Total Gauss antes == después para todos los casos capturados; base_varios una sola vez (con % de varios cargado).
- [x] T4 API: línea con importe en el breakdown, `bonificacion_envio` en breakdown y listado; la cadena ya no la trae.
- [x] T5 frontend: la línea en "De dónde sale el neto"; fuera de la tarjeta Total Gauss; tooltip del neto.
- [x] T6 novedad.
- [ ] T7 bump `CURRENT_FORMULA_VERSION` 3 -> 4 + test de reconcile (último commit).
- [ ] T8 lint (ruff, pnpm lint, lint:css), tests acotados, push, observaciones del GGA.

## Verificación

- `ENVIRONMENT=testing ... POSTGRES_TEST_URL=.../pricing_test_bonifneto .venv/bin/python -m pytest tests/services/ml_ventas_desglose tests/services/order_metrics tests/services/ml_group_metrics tests/services/ml_sales_query tests/workers` + integración `ml_ventas_ops*`.
- `pnpm test` acotado a `ventasMl`, `metricasMl`, novedades; `pnpm run lint`, `pnpm run lint:css`.
- `ruff check app/ tests/` y `ruff format app/ tests/ --check` (ruff 0.15.1).

## Evidencia (antes, en `origin/main`, fixtures capturados)

| Orden | neto | neto_sin_iva | Total Gauss |
|---|---|---|---|
| 2000018808335864 (Flex, 8990) | 13081.02 | 10677.99 | 11107.74 |
| 2000018846584294 (pack Flex, 599) | 88932.33 | 72751.42 | 71246.46 (provisorio) |
| 2000018844749424 | 12569.71 | 10252.01 | 9252.01 |
| 2000018847750422 | 38120.07 | 31070.46 | 30070.46 |
| 2000018847574430 | 29518.99 | 23931.41 | 22931.41 |
| 2000018846969514 | 15879.46 | 12985.59 | 11985.59 (provisorio) |
| 2000018846999192 | 19312.11 | 15661.56 | 14661.56 |
| 2000018814119064 | 18264.25 | 14913.11 | 13913.11 |

## Progreso

- T1-T4 (backend + API): RED observado (11 de 28 tests del archivo nuevo fallaban: neto/neto_sin_iva sin +bonificación, la deducción seguía en la cadena, `bonificacion_envio` inexistente en el breakdown); GREEN 28/28; mutación de la base de varios (bonificación x2) la rompe. Suites acotadas: 1340 passed. Commit: ver `git log`.

- T5-T6 (frontend + novedad): RED observado (5 tests: línea dentro de 'De dónde sale el neto', composición del neto, tooltip del listado); GREEN: 423 tests de ventasMl/VentasML/utils, 8 de novedades/metricasMl. `pnpm run lint` y `lint:css` sin errores (2 warnings preexistentes de react-hooks fuera de este cambio).

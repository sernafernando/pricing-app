# Ventas ML: bonificación por envío Flex en el desglose y el Total Gauss

**Creado:** 2026-10-07 · **Estado:** en curso
**TDD:** estricto (config de sesión) · **Runners:** `cd backend && .venv/bin/python -m pytest` / `cd frontend && pnpm test`
**Estrategia de entrega:** `ask-on-risk` · **Rama base:** `origin/main` (`99f36607`) · **Rama:** `feat/ventas-ml-bonificacion-envio-flex`

## Objetivo

En una venta Flex (`logistic_type = self_service`) donde el comprador tuvo envío gratis por un
descuento de ML, ML le paga al vendedor una "Bonificación por envío". Hoy esa plata no entra en
ningún lado de nuestro desglose. Debe aparecer como línea visible y sumar al Total Gauss.

## Problema (diagnosticado con captura real)

Venta `2000018808335864` (pack `2000015364544817`): el panel de ML muestra **$8.990** de
bonificación (IVA incluido). Datos que ya guardamos y nadie lee:

- `ml_shipments_ops.raw_costs`: `receiver.discounts = [{"rate": 1, "type": "loyal", "promoted_amount": 8990}]`,
  `receiver.save = 8990`, `receiver.cost = 0`, `gross_amount = 8990`.
- No está en el neto del pago (`net_received_amount` 13024.45), ni en billing, ni en
  `/orders/{id}/discounts` (404).

Captura: `ml-captures/order_bonus_capture_2000015364544817_20261007_135404.json`; fixture recortado
(sin datos personales) en `backend/tests/fixtures/ml_ventas_bonificacion/`.

## Requisito agregado durante la implementación

La línea expone **bruto (8990), neto (7429,75) e IVA (1560,25) como campos separados** (API:
`cadena_total_gauss.lineas[].importe`, forma única `ImporteDesglosadoSummary` para líneas de envío;
panel: junto a la línea). El IVA es informativo/fiscal: nunca resta del Total Gauss.

## Reglas confirmadas por el usuario

- Es **ingreso**, **neto de IVA**: 8990 / 1,21 = 7429,75, redondeado como el módulo (`_split`,
  HALF_UP a centavos).
- Línea visible "Bonificación por envío" en el desglose.
- **Solo Flex.** Otras logísticas: el descuento lo subsidia ML y no es ingreso del vendedor.
- Monto = suma de `promoted_amount` de `receiver.discounts`. Faltante, no numérico o negativo =
  no suma plata (fail-closed, con log).
- **Una vez por envío**, no por orden del pack.

## Decisiones

- **D1. Un resolver más en la cadena (`DEDUCCIONES`)**, `code = "bonificacion_envio"`, `orden = 4`,
  con monto NEGATIVO (una deducción negativa suma). El frontend ya pinta un monto negativo como
  `(+)` verde (`formatDeduction`). Sin esquema nuevo: `ml_venta_deducciones` es por `code`.
- **D2. Prorrateo por envío, mismo criterio que `EnvioFlexDeduccion`**: el divisor sale de la base
  (`COUNT(order_id) GROUP BY shipping_id`), nunca del batch. A diferencia del flete, el reparto es
  EXACTO en centavos (el resto va a las órdenes de menor `order_id`), para que la suma del pack dé
  el monto del envío sin deriva. Bruto y neto se reparten por separado y `iva = bruto - neto`.
- **D3. IVA**: `iva.py` trata todo lo de ML (comisiones, flete) al 21% (`IVA_ML_PCT`, "autoritativo
  según el mantenedor"). La bonificación entra con el mismo 21%. Aparece en `componentes` como
  **informativo** (mismo patrón que SIRTAC): se muestra pero NO entra en `suma_bruto` ni en
  `neto_sin_iva`, porque no está dentro de `net_received_amount` y la reconciliación exacta (D12)
  se rompería. El neto de IVA lo suma la cadena de Total Gauss, no el `neto_sin_iva`.
- **D4. Historia: FUERA de esta PR** (decisión del usuario: un único backfill al final, después de
  la PR del % varios). Esta PR NO sube `CURRENT_FORMULA_VERSION` (subirlo haría que el handler
  `order_metrics.reconcile` re-encole toda la historia apenas se despliega) y NO agrega scripts.
  Ventas nuevas y re-ingestadas toman la bonificación por el flujo normal (triggers -> cola
  -> `order_metrics.drain`). El mecanismo existente para el backfill queda documentado en el
  reporte de la PR.
- **D5. Recalcular al actualizar `raw_costs`**: hoy `raw_costs` está deliberadamente SIN trigger
  (`triggers.py`), así que una venta nueva calculada antes de que llegue el costo del envío
  quedaría sin la bonificación para siempre. Migración nueva que reemplaza el trigger UPDATE de
  `ml_shipments_ops` para incluir `raw_costs` (el DDL vigente no se edita: contrato de
  inmutabilidad de migraciones).

## Pendiente de decisión del usuario

- Fiscal: si ML paga esto contra una factura que emite el vendedor (débito fiscal 21%) no está
  modelado en `iva.py` (D13: no hay libro IVA). Aplicamos el 21% porque lo pidió el usuario y es
  el criterio de todo lo de ML; no se inventó ninguna otra alícuota.
- Descuentos parciales (`rate < 1`) no están capturados: se suman por `promoted_amount` igual
  (supuesto documentado).

## Tareas

- [x] T1 Fixture capturado + parser/reparto `bonificacion_flex.py` (tests con la captura: 8990 -> 7429,75; fail-closed)
- [x] T2 `BonificacionEnvioDeduccion` en la cadena; Total Gauss +7429,75; no-Flex no suma; pack no duplica
- [x] T3 Componente informativo en `iva.py` (21%, base/iva), sin romper la reconciliación
- [x] T4 Trigger por cambio de `raw_costs` (migración + módulo vivo + fixture) y test en Postgres
- [x] T5 (descartada por el usuario) no se sube `CURRENT_FORMULA_VERSION`; el backfill va en otra PR
- [x] T6 Frontend: etiqueta "Bonificación por envío", IVA informativo con base/IVA, test vitest
- [x] T7 Novedad en `frontend/src/novedades`
- [ ] T8 Lint (ruff, pnpm lint, lint:css), tests relacionados, GGA, push

## Checks

`pytest tests/services/ml_ventas_desglose tests/services/order_metrics tests/workers/handlers tests/integration/test_ml_ventas_ops*`
(+ `tests/services/ml_orders_ingestion` si se toca), `pnpm test ventasMl`, `ruff check app/ tests/`,
`ruff format app/ tests/ --check`, `pnpm run lint`, `pnpm run lint:css`. La suite completa la corre el CI.

## Evidencia / progreso

- RED observados: parser/resolver/cadena (cero de diferencia vs 7429,75), router (`KeyError: 'importe'`),
  trigger Postgres (`assert None is not None`), frontend (2 tests rojos). Migración: test escrito después.
- Mutaciones verificadas: sin gate self_service -> falla; bruto sin repartir en pack -> falla.
- Rutas: todo delegado directo no aplicó; implementado inline por el agente de esta tarea (un solo escritor).
- Backfill histórico: fuera de esta PR por decisión del usuario.

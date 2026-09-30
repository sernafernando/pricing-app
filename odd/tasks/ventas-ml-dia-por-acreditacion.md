# Ventas ML — el día es cuando entra la plata, no cuando se abrió la venta

## La regla (decisión del usuario, 2026-09-30)

> Una venta entra en el día en que se ACREDITÓ su plata. Una venta sin plata
> acreditada no está en ningún día.

Palabras del usuario: *"va hoy, que me importa que el tipo haya abierto la
operación hace 2 meses si entra hoy"* y *"los rechazados no deberíamos ni
verlos, es ruido"*.

Las dos frases son la misma regla. Los rechazados no hay que esconderlos:
no tienen fecha de acreditación, así que no pertenecen a ningún día y
desaparecen por consecuencia, no por una exclusión aparte.

## Evidencia

Cruce 1:1 del export de ML del 30/09 contra la base (64 filas nuestras vs 62
suyas): **61 ventas coinciden al peso, CERO diferencias de monto.** La
valuación nunca fue el problema. Lo que difiere es el CONJUNTO.

El caso que lo prueba, orden `2000018641457084`:

    creada        2026-09-25 16:28
    9 pagos       8 rejected, 1 approved
    acreditada    2026-09-30 11:42   <- ML la reporta en el 30
    monto         $ 45.311,00        <- el faltante exacto del día

`MlPaymentOps.date_approved` está poblada al 100% (35.212 de 35.212 pagos
relevantes), así que la regla tiene dónde apoyarse.

Y el panel de ML NO es la fuente de verdad: dice $7.899.363 mientras su
propio export suma $9.149.361,10, porque excluye una venta de $1.249.999 por
su estado de envío. Reconciliar contra el panel es perseguir otra métrica.

## Alcance

`date_created` no vive en un lugar:

- el filtro del día (`filters.py:418`)
- el orden de la lista y la paginación por grupo (`ml_ventas_ops.py`)
- `_group_date` (`ml_group_metrics/compute.py`), que alimenta
- `ml_group_metrics.group_date`, **77.521 filas ya backfilleadas**

Cambiar la base implica migración de criterio MÁS backfill. No es un parche.

## Decisiones tomadas (no volver a preguntarlas)

- El día de una venta es el `MAX(date_approved)` de los pagos relevantes de
  TODOS sus integrantes: la ÚLTIMA acreditación.

  Razón del usuario, y es la que manda: *"siempre la acreditación es la
  última, que es cuando el pedido va a salir... no me importa lo anterior"*.
  Si el día es cuándo puede salir el pedido, es el último peso que entra, no
  el primero. Y eso resuelve el pack solo: un pack no sale hasta que TODOS
  sus integrantes estén cobrados, así que `MAX` también entre miembros — una
  sola regla para los dos niveles.

  OJO, esto NO contradice el `MIN` de PR20 (`_group_date` sobre
  `date_created`): ahí la pregunta era "¿cuándo empezó esto?" y el mínimo era
  correcto. Acá es "¿cuándo puede salir?" y es el máximo. Distinta pregunta,
  distinto agregado. No "unificar" los dos a un mismo agregado por parecer
  más limpio.
- "Pago relevante" es `RELEVANT_PAYMENT_STATUSES` — la MISMA lista que usa
  la cadena Gauss y que #1367 dejó usando el bruto. Una tercera regla para
  decidir qué es plata ya se intentó una vez en esta feature y fue un bug.
- Una devolución cuenta en el día en que ENTRÓ la plata, no en el que salió.
  Igual que ML, cuyo "Ventas brutas" dice "sin descontar cancelaciones ni
  devoluciones".
- Una venta sin pago acreditado no está en ningún día. No se esconde: no
  tiene fecha.

## Preguntas que estaban abiertas y ya están respondidas (2026-09-30)

- Acredita / revierte / vuelve a acreditar: **siempre la última**. El
  usuario: *"con ML es bastante difícil, pero ponele que pase, siempre es la
  última, no me importa lo anterior"*.
- Una venta que hoy no cobró y mañana sí aparece mañana y nunca estuvo en
  hoy: **es lo deseado**.
- NO se conserva una vista por fecha de creación. El usuario: *"nadie tiene
  que seguir una venta que no se cobró, ML no da datos de contacto de los
  clientes para poder concretar una venta, así que es al pedo el seguimiento
  de lo que no se concretó"*. Sin datos de contacto no hay acción posible
  sobre una venta no cobrada, así que seguirla no es información: es ruido.

## Tareas

- [x] T1 — Un solo lugar que resuelva "el día de esta venta":
      `MAX(date_approved)` sobre los pagos relevantes de todos los
      integrantes. Nunca duplicado.
      `app/services/ml_sales_query/accreditation.py` (nuevo): dos entry
      points sobre la MISMA regla (`RELEVANT_PAYMENT_STATUSES`,
      `MAX(date_approved)`) — `group_accreditation_date_subquery` (SQL, para
      joins) y `member_accreditation_dates` (bulk dict, para el caller
      Python de `compute.py`). No se duplica la regla, sólo la FORMA de
      exponerla según el caller.
- [x] T2 — El filtro del día usa ese resolvedor.
      `filters.py::build_scope`: `base`/`listing_query` quedan LEFT JOIN
      contra `group_accreditation_date_subquery` SIEMPRE (no sólo si hay
      `date_range`), y el filtro de fecha compara contra esa columna, no
      contra `date_created`.
- [x] T3 — `_group_date` usa ese resolvedor. Una venta sin acreditación
      tiene `group_date` NULL y no entra en ningún rango.
      `ml_group_metrics/compute.py::_group_date` ahora recibe
      `accreditation_by_order` (de `member_accreditation_dates`) y calcula
      `max()`, no `min()` sobre `date_created`.
- [x] T4 — El orden de la lista por fecha usa la misma base, o la lista
      queda ordenada por una fecha distinta de la que filtra.
      `SalesScope.accreditation_subquery` expone la subquery para que
      `ml_ventas_ops.py`'s `key_page` ordene por
      `func.max(accreditation_date_col)`, la MISMA columna que el filtro.
- [x] T5 — Backfill de `ml_group_metrics.group_date` para las 77.521 filas.
      Con el mismo criterio que el backfill anterior: informar cuánto queda,
      y que una corrida parcial no se parezca a una completa.
      `app/scripts/backfill_group_date_accreditation.py` (nuevo): idempotente
      (sólo UPDATEa filas cuyo valor recalculado difiere del guardado),
      `remaining` es un re-scan completo de la tabla, WARNING si una corrida
      real deja `remaining > 0`. NO CORRIDO CONTRA PRODUCCIÓN todavía — eso
      queda pendiente de un deploy/operación manual fuera de este cambio.
- [x] T6 — Verificación contra datos reales: la orden `2000018641457084`
      tiene que aparecer en el 30/09 y NO en el 25/09.
      Cubierto por test (no contra la base de producción real, sino
      reproduciendo la forma exacta: 8 pagos rechazados + 1 aprobado
      acreditando 30/09 11:42, orden creada 25/09 16:28) —
      `tests/services/ml_sales_query/test_accreditation_postgres.py::TestAccreditationDayFilterThroughTheEndpointQuery::test_order_created_25th_accredited_30th_lands_in_30th_not_25th`.
      La verificación contra la base REAL de producción (cruce 1:1 con el
      export de ML) queda pendiente de correrse después del deploy.
- [x] T7 — Tests contra Postgres del filtro de día, no solo SQLite. El bug
      del `group_by` de ayer vivió tres semanas porque los tests de ese
      camino corrían en SQLite.
      `tests/services/ml_sales_query/test_accreditation_postgres.py` (nuevo,
      3 tests) + `tests/scripts/test_backfill_group_date_accreditation.py`
      (nuevo, 5 tests) — ambos `@pytest.mark.postgres`, agrupan/ordenan/pagan
      igual que el endpoint real (mismo patrón que
      `test_filters_switches_postgres.py`).

## Criterio de aceptación

El cruce 1:1 contra el export de ML del día da las mismas ventas de los dos
lados, sin filas "solo en ML" ni "solo en la base" salvo las que ML todavía
no publicó al momento del export.

## Checks

- `python -m pytest tests/ -q -p no:randomly` (SOLA: dos suites de Postgres
  en paralelo contra la misma base se pisan y fallan en módulos ajenos)
- `ruff check app/ tests/`
- `pnpm --dir frontend exec eslint src` / `exec vitest run` / `build`

## Checks — evidencia (2026-09-30)

- `ruff format app/ tests/` — 0 archivos reformateados en la corrida final
  (todo ya formateado por corridas previas del propio trabajo).
- `ruff check app/ tests/` — `All checks passed!`
- `python -m pytest tests/ -q -p no:randomly` (corrida completa, SOLA) —
  `1 failed, 7485 passed, 16 skipped, ... in 756.54s`. El único fallo
  (`test_accreditation_postgres.py::...::test_order_created_25th_accredited_30th_lands_in_30th_not_25th`)
  es el problema YA documentado en este mismo doc ("dos suites de Postgres
  en paralelo... se pisan"): confirmado en verde corriendo el archivo SOLO
  (`3 passed`) inmediatamente después. Baseline previo: 7472 passed, 16
  skipped — la suba a 7485 son los tests nuevos de este cambio.
- `pnpm --dir frontend exec eslint src` — `8 problems (0 errors, 8 warnings)`,
  las mismas 8 warnings preexistentes (no se tocó frontend en este cambio).
- `pnpm --dir frontend exec vitest run` — `Test Files 133 passed (133)`,
  `Tests 1789 passed | 2 expected fail (1791)`.
- `pnpm --dir frontend build` — `✓ built in 44.97s`.

TDD: cada comportamiento decisivo (T1/T2 filtro por acreditación, T3
`_group_date` MAX, T4 orden, T5 backfill) se escribió en rojo primero, se
confirmó el motivo del rojo, y se mutó `max→min`/`_changed_keys→[]` después
de verde para confirmar que el test lo detecta — ver mensajes de commit/PR
para el detalle por test.

## Pendiente fuera de este cambio

- Correr `python -m app.scripts.backfill_group_date_accreditation` (sin
  `--dry-run`) contra producción, y el cruce 1:1 real contra el export de
  ML del día (criterio de aceptación) — ambos requieren la base de
  producción, no corren desde este entorno.

## Estado

Creado 2026-09-30. Implementado 2026-09-30 (T1-T7 en código y tests).
Depende de que #1367 esté mergeada (ya lo está, ver git log). Pendiente:
correr el backfill contra producción y la verificación 1:1 post-deploy.

# Flex label logistics change history

Objective: keep every change of etiquetas_envio.logistica_id (old, new, who, when, source). Branch feat/flex-logistica-historial, off origin/main d5cefea9.
Delivery: PR1 = migration (table + trigger, high risk, alone); PR2 = write paths record who and source. Runner: pytest (changed tests only, `@pytest.mark.postgres` for the trigger) + ruff format/check; full suite in CI.

## Specs
- S1 (L1, confirmed 2026-10-27) Every logistica_id change is kept: old value, new value, who (usuario and/or operador), when, source (asignar / masivo / pistoleado / manual). A DB trigger records it, so a future write path cannot skip it. Unchanged values (old IS NOT DISTINCT FROM new) record nothing.
- S2 Who and source come from the write path in the same transaction (transaction-local settings read by the trigger). A path that does not set them still gets a row, with who/source empty.
- S3 Constraints: migration in its own commit/PR; tests in RED first; PRs <= ~400 lines; repo is public (no internal IPs/ports/phones); no AI attribution.
- S4 (L2, deferred: "calculo que podemos hacer L1 y despué si todo está bien hacer L2") Show the history on the label and allow undoing. Not in this feature until the owner asks.

## Tasks
- [x] T0 Confirm scope with the owner: L1 now, L2 later. route inline.
- [x] T1 Re-verify write paths on main d5cefea9. route inline. Evidence in L4.
- [x] T2 (S1, S3) Migration: history table + row trigger, Postgres tests RED first. route delegated (context backstop). PR1.
- [ ] T3 (S2) asignar_logistica, asignar_masivo, pistoleado, editar manual set usuario/operador/source before the write; tests RED first. route TBD. PR2.

## Log
- L1 2026-10-20 owner: "te consulto en envíos flex, guardamos el estado anterior de una logística? o sea ponele que lo tenía claude se lo cambiaron a gpt por error, queda que el pedido era de claude guardado?" Then "guardalo para después".
- L2 2026-10-27 owner, via pricing-app-5-2a: "si querés delegar así cosas como lo del historial de flex que no tiene nada que ver con ventas lo pueda ir gestionando otro agente."
- L3 2026-10-27 owner: "calculo que podemos hacer L1 y despué si todo está bien hacer L2 no?"
- L4 2026-10-27 T1 (main d5cefea9), writes of etiquetas_envio.logistica_id:
  - etiquetas_assignments.py:73 asignar_logistica (PUT /etiquetas-envio/{shipping_id}/logistica): old value lost.
  - etiquetas_assignments.py:~196 asignar_masivo (PUT /etiquetas-envio/asignar-masivo, bulk query.update): old value lost.
  - etiquetas_pistoleado.py:112/130/135 (pistoleado_asigna or forzar_asignacion): old value lost; operador_actividad keeps only the new id.
  - etiquetas_manual.py:533 editar manual: old kept inside operador_actividad.detalle.anterior.
  - Inserts (upload, manual create) set the first value; not a change.
  - Existing etiquetas_envio triggers (order_metrics, triggers_config.py) already enqueue metric recompute on these writes; the history trigger is separate.
- L5 Why it matters: own Flex freight in the metrics (EnvioFlexDeduccion, cordon tariff) depends on logistica_id; a wrong reassignment changes money and cannot be traced.
- L6 2026-10-27 T2 done (delegated writer). Revision `20261201_etiquetas_logistica_historial` (on `20261130_tb_item_full_row`, single head): table `etiquetas_envio_logistica_historial` (FK to logisticas for old/new like etiquetas_envio; no FK on usuario/operador so a bad setting never fails the label write; no FK to etiquetas_envio so history outlives the label), index (shipping_id, cambiado_en), ROW trigger `trg_etiquetas_envio_logistica_historial` + function `etiquetas_envio_logistica_historial_registrar`. Settings `app.logistica_usuario_id` / `app.logistica_operador_id` (digits 1-9 else NULL) / `app.logistica_origen` (NULLIF ''). Live SQL `backend/app/services/etiquetas/logistica_historial_sql.py`, frozen copy in the migration; lock_timeout 5s restored afterwards. RED: collection ModuleNotFoundError `app.services.etiquetas`; then with module but no migration `7 failed, 8 errors`. GREEN: `pytest tests/migrations/test_migration_etiquetas_logistica_historial_postgres.py`: 15 passed (local Postgres 18); ruff format/check clean. T3 must set the three settings with `set_config(name, value, true)` in the same transaction as the UPDATE.

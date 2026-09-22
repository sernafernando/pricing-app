# Tasks: Ventas ML redesign

Delivery: auto-chain, SEQUENTIAL (each PR branches fresh off `origin/main` after the previous one is MERGED — no stacking). Each PR must be safe to merge alone. ~400 authored changed lines per PR as a planning heuristic (flagged where a PR is expected to exceed it). Strict TDD: every task is RED (named failing test) → GREEN → refactor. Fixtures from real captured shapes only.

Skills: `pricing-app-testing-ci`, `pricing-app-backend`, `pricing-app-frontend`, `pricing-app-design`. Resolve `work-unit-commits` and `chained-pr` skills by registry name and follow them for branch/commit/PR mechanics.

Requirement legend: `SM`=ml-order-stored-metrics (R1-R8), `KPI`=ml-sales-kpi-aggregation (R7-R15), `PANEL`=ml-sales-detail-panel (R16-R21), `RESYNC`=ml-order-resync (R22-R24), `SEARCH`=ml-sales-search (R25-R27), `LISTING`=ml-sales-listing (R28-R31), `BREAKDOWN`=ml-order-breakdown (R32-R34), `NEG`=negative-scenarios.

## PR1 — Stored metrics tables + compute/recompute producer (inert)
Design refs: D1, D2, D7. Satisfies: SM R1, R2.

- [ ] PR1.T1 RED: unit tests for `OrderMetrics` dataclass + `GaussStatus` enum — `unresolved` forces `total_gauss=NULL` and dependent fields NULL; any other status with NULL total_gauss is rejected (SM R2).
- [ ] PR1.T2 GREEN: create `backend/app/models/ml_order_metrics.py` (`MlOrderMetrics` 1:1 `ml_orders_ops`, FK ON DELETE CASCADE; `MlOrderMetricsDirty` with `version`, `claimed_at`, `claimed_by`, `attempts`, `last_error`) and `backend/app/models/worker_job_state.py`.
- [ ] PR1.T3 RED: Alembic migration test (upgrade/downgrade round-trip) for `ml_order_metrics`, `ml_order_metrics_dirty`, `worker_job_state`, `ix_ml_order_metrics_status`, `ix_ml_order_metrics_total_gauss` (DESC NULLS LAST), `ix_ml_orders_ops_seller_date`.
- [ ] PR1.T4 GREEN: write `backend/alembic/versions/2026MMDD_ml_order_metrics.py` with full downgrade.
- [ ] PR1.T5 RED: unit tests — `compute_order_metrics(db, order_ids)` wraps existing `compute_neto_by_order_ids`, `descomponer_neto`, `calcular_total_gauss` and returns identical values to calling those functions directly (no second formula), for `ok`, `provisional`, `unresolved` fixtures (captured payloads).
- [ ] PR1.T6 GREEN: implement `backend/app/services/order_metrics/compute.py::compute_order_metrics`.
- [ ] PR1.T7 RED: unit test — `recompute_order_metrics(db, order_ids)` upserts `ml_order_metrics` + `ml_venta_deducciones` + legacy `ml_orders_ops.total_gauss*` columns, no commit (caller controls transaction).
- [ ] PR1.T8 GREEN: implement `backend/app/services/order_metrics/store.py::recompute_order_metrics`.
- [ ] PR1.T9 RED→GREEN: `persistir_total_gauss` (deducciones.py) becomes a thin delegating alias to `recompute_order_metrics`; existing deducciones tests stay green unmodified (regression guard).
- [ ] PR1.T10 Run backend suite + `ruff format app/ tests/ alembic/`; confirm no readers changed (inert deploy).

## PR2 — Generic worker runtime (idle, empty registry)
Design refs: D4, D6. No spec requirement yet satisfied directly (infra); enables SM R7.

- [ ] PR2.T1 RED: unit tests for `JobHandler` Protocol scheduling math — `run_at_local` daily-slot logic, restart does not double-run (`worker_job_state.last_success_at` vs today's slot).
- [ ] PR2.T2 GREEN: `backend/app/workers/{__init__,registry,context}.py` (empty registry list, `WorkerContext`, `JobResult`).
- [ ] PR2.T3 RED: integration test (`@pytest.mark.postgres`) — worker LISTEN via `DATABASE_URL_DIRECT` bypasses PgBouncer; if unset, runs in `poll_only` mode and logs a WARNING (never silent loss).
- [ ] PR2.T4 GREEN: `backend/app/workers/runtime.py` (LISTEN/select loop, debounce 50ms, safety-poll timeout=min(5s, next due job), startup full drain, reconnect+backoff, heartbeat via rate-limited `ctx.heartbeat()` per iteration and per handler batch).
- [ ] PR2.T5 GREEN: `backend/app/workers/run.py` (`python -m app.workers.run` entrypoint).
- [ ] PR2.T6 RED→GREEN: `backend/app/core/database.py::_is_script_context` also matches the '/workers/' path fragment → NullPool; `backend/app/core/config.py` adds `DATABASE_URL_DIRECT: Optional[str]` + worker tunables (lease, batch size, poll interval).
- [ ] PR2.T7 GREEN (non-test): `deploy/systemd/pricing-worker.service` (Restart=always, RestartSec=5, venv python, After=postgresql); `deploy.sh` step adds warn-not-fail restart of `pricing-worker` after `pricing-api`; `docs/RUNBOOKS.md` install/enable + health endpoint + `DATABASE_URL_DIRECT` section.
- [ ] PR2.T8 RED: integration test — worker with empty registry runs the loop and idles harmlessly (no crash, heartbeat updates).
- [ ] PR2.T9 OWNER: user — do not install/enable the systemd unit yet (queue is still empty; install happens at PR3 per design Migration/Rollout). Note this explicitly in the PR description.

## PR3 — Queue claim/release + drain handler + PG fixtures (ops installs unit here)
Design refs: D3 (queue table only, no triggers yet), D5. Satisfies: SM R7 (no-cron mechanism scaffolding).

- [ ] PR3.T1 RED (`@pytest.mark.postgres`, new `pg_order_metrics_engine` fixture in conftest.py): `claim_dirty` — two concurrent claimers get disjoint order sets (`FOR UPDATE SKIP LOCKED`).
- [ ] PR3.T2 RED: lease expiry (default 120s) reclaims rows of a crashed worker.
- [ ] PR3.T3 RED: `release_dirty` — version-checked delete; a write that bumps `version` during recompute leaves the row dirty (no lost update).
- [ ] PR3.T4 RED: `mark_failed` — after 5 attempts, order is `poisoned`, excluded from claim, reported in health; failure isolated per-order via savepoint (batch of 199 succeeds despite 1 bad order).
- [ ] PR3.T4a RED: 5 lost races (version-mismatch release, dirty row re-upserted by a new input write during each recompute) on the same order never increments `attempts` and never parks it — `claim_dirty` still returns it after a 6th genuine input write, no failure recorded, no entry in `poisoned_count`.
- [ ] PR3.T4b RED: a parked order (attempts == 5, excluded from claim) that then receives a new input write is un-parked by the enqueue upsert (`attempts` resets to 0, `last_error` cleared) and is claimed and recomputed on the next drain, same as any other dirty order.
- [ ] PR3.T4c RED: 5 genuine recompute failures (exception raised inside step 2 for the same order, not a version mismatch) increment `attempts` each time, park the order at `attempts == 5`, and `poisoned_count` in health reflects exactly that one order; a concurrently failing OR succeeding unrelated order's `attempts`/status is unaffected.
- [ ] PR3.T4d RED (design D5 attempts rule): simulate a worker death 5 times on the same order (claim it, never release, advance the lease past expiry, run `claim_dirty` again) ⇒ `attempts` rises by 1 per expired-lease reclaim, `last_error = 'lease_expired'`, the order is parked at `attempts == 5` and counted in `poisoned_count`; rows with `attempts > 0` are claimed alone (batch of one); an unrelated dirty order enqueued alongside is claimed, recomputed and deleted throughout (queue continues).
- [ ] PR3.T4e RED: a recompute statement exceeding `SET LOCAL statement_timeout` raises, is recorded through `mark_failed` as a normal failed attempt, and the claim is released before the lease expires.
- [ ] PR3.T4f RED (real Postgres, two sessions with threading barriers; design D5 fence): worker A claims order X at version 1 and computes from the old snapshot; A's lease expires; an input write bumps X to version 2; worker B reclaims X, recomputes the new snapshot and commits; then A attempts its store ⇒ A's claim-token fence finds no owned row, A writes nothing, and `ml_order_metrics` keeps B's newer values. Second case: a write bumps the version while A still owns the claim ⇒ A's upsert commits but the dirty row survives unclaimed (order stays `recalculating`) and the next pass converges to the newest inputs.
- [ ] PR3.T5 GREEN: implement `backend/app/services/order_metrics/queue.py` (`claim_dirty` with expired-lease charging and single-row retry claims, `fenced_store`, `mark_failed`) satisfying T1-T4f.
- [ ] PR3.T6 RED: `order_metrics.drain` handler — claims batch(200) → recompute + fenced store in one transaction, in two short `get_background_db()` blocks; stops starting new orders after `ctx.deadline`.
- [ ] PR3.T6a RED (design D4 step 5): a drain of N batches whose total duration exceeds 30 s (slowed recompute stub) calls `ctx.heartbeat()` between batches, `heartbeat_at` never ages past 30 s during the drain, health reports `worker_alive = true` and `worker_draining = true` throughout.
- [ ] PR3.T7 GREEN: `backend/app/workers/handlers/order_metrics.py::drain`; register in `registry.py` (channels=`("order_metrics_dirty",)`).
- [ ] PR3.T8 RED: end-to-end worker test — manually inserted dirty row is claimed, recomputed, and deleted within the poll interval (committed-data fixture, since NOTIFY needs commit).
- [ ] PR3.T9 GREEN: wire drain into runtime wake path; confirm queue still empty in prod (no triggers exist yet) — deploy is inert except idle polling.
- [ ] PR3.T10 OWNER: user — install and enable the systemd unit now: `sudo cp deploy/systemd/pricing-worker.service /etc/systemd/system/`, `sudo systemctl daemon-reload`, `sudo systemctl enable --now pricing-worker`, set `DATABASE_URL_DIRECT` in backend `.env` (direct Postgres, not PgBouncer), verify `systemctl status pricing-worker` and `GET /api/ml-ops/order-metrics/health` (added in PR6) once available.

## PR4 — Enqueue function + per-order triggers (producers start; consumer already live)
Design refs: D3 read-set scope for per-order tables, D8. Satisfies: SM R1, R3 (per-order path), R7.

- [ ] PR4.T1 RED (`@pytest.mark.postgres`): PL/pgSQL `order_metrics_enqueue(ids, reason)` — upserts dirty rows with `version+1` on conflict, resets `attempts` (to 0), `last_error` (to NULL), and leaves `claimed_at`, `claimed_by`, `claim_token` UNCHANGED (design D3 rev 3), fires ONE `pg_notify('order_metrics_dirty','')` per transaction even for 10k-row fan-out (folded notify).
- [ ] PR4.T1a RED (`@pytest.mark.postgres`): `order_metrics_enqueue` called against an existing row with `attempts = 5, last_error IS NOT NULL` (a parked order) resets `attempts = 0` and `last_error = NULL` on that row — a new input write is a new chance, un-parking a poisoned order at the enqueue/trigger layer, not just in `queue.py`.
- [ ] PR4.T1b RED (`@pytest.mark.postgres`): `order_metrics_enqueue_system(ids, reason)` inserts missing rows and fires the notify, but on an existing row (pending, claimed, or parked with `attempts = 5`) changes nothing — `version`, `attempts`, `last_error`, claim columns all identical before and after.
- [ ] PR4.T2 GREEN: implement both enqueue functions' DDL in `backend/app/services/order_metrics/triggers.py`.
- [ ] PR4.T3 RED: one test per table×write-kind for `ml_orders_ops` (INSERT; UPDATE OF `shipping_id`,`date_created`,`has_no_shipping_tag`,`pack_id`; DELETE; `shipping_id` change also enqueues OLD+NEW shipping siblings) — committed write ⇒ dirty row+version bump; rolled-back write ⇒ no row, no notify.
- [ ] PR4.T4 RED: same pattern for `ml_order_items_ops`, `ml_order_item_costos`.
- [ ] PR4.T5 RED: same pattern for `ml_payments_ops` (OLD/NEW `order_id`; UPDATE OF `status`,`net_received_amount`,`transaction_amount_refunded`,`shipping_amount`,`order_id`) and `ml_payment_charges` (payment_id→order_id).
- [ ] PR4.T6 RED: same pattern for `ml_shipments_ops` (UPDATE OF `logistic_type`,`receiver_address` only; confirm sender/receiver cost and `raw_costs` columns do NOT fire — negative scenario).
- [ ] PR4.T7 GREEN: row-level triggers for all six tables in `triggers.py`, applied via Alembic + an `after_create` listener firing only for `postgresql` dialect.
- [ ] PR4.T8 RED: write `backend/alembic/versions/2026MMDD_ml_order_metrics_triggers_orders.py` round-trip test (upgrade creates triggers, downgrade drops them + function).
- [ ] PR4.T9 GREEN: implement the migration.
- [ ] PR4.T10 RED: read-set guard test — `before_cursor_execute` instrumentation of `compute_order_metrics` fails if any table it reads is missing from `TRIGGERED_TABLES` (SQLite-safe, runs in normal CI).
- [ ] PR4.T11 GREEN: define `TRIGGERED_TABLES: FrozenSet[str]` and wire the guard.
- [ ] PR4.T12 RED: NOTIFY-only-on-commit test — second raw connection LISTENs, confirms zero notifications on rollback, exactly one on commit regardless of row count.

## PR5 — Etiquetas + config + transportes statement triggers; varios fan-out response
Design refs: D3 (statement-level scope), D11. Satisfies: SM R3 (config fan-out path), R3 scenario 5.

- [ ] PR5.T1 RED (`@pytest.mark.postgres`): `etiquetas_envio` row triggers — INSERT, DELETE, UPDATE OF `shipping_id`,`logistica_id`,`costo_override`,`fecha_envio`,`es_turbo`,`es_lluvia`,`transporte_id` enqueue; lat/lng-only writes do NOT (negative scenario, previously-missed writers listed in design D "Why triggers" section: toggle turbo, lluvia, lluvia masivo, pistoleado, manual edit, enrichment, reprogram, colecta/pistoleado delete).
- [ ] PR5.T2 GREEN: `etiquetas_envio` triggers in `triggers.py`.
- [ ] PR5.T3 RED: statement-level trigger with transition tables for `varios_venta_pct` — orders with `date_created` in `OLD∪NEW [fecha_desde, fecha_hasta]` enqueued via ONE set-based insert (not N).
- [ ] PR5.T4 RED: same pattern for `logistica_costo_cordon` (self_service orders whose label has that logistica_id), `codigos_postales` cordon, `configuracion` WHEN `clave IN ('lluvia_offset_tipo','lluvia_offset_valor')`, `transportes UPDATE OF cp` (orders whose label has that `transporte_id`; `transportes` INSERT needs no fan-out — no labels reference a brand-new row yet).
- [ ] PR5.T5 GREEN: all five statement-level triggers with `REFERENCING OLD TABLE / NEW TABLE`.
- [ ] PR5.T6 GREEN: `backend/alembic/versions/2026MMDD_ml_order_metrics_triggers_config.py` (round-trip tested).
- [ ] PR5.T7 RED: `configuracion.py::crear_varios_venta_pct` — response includes `recalculando: N` (count of dirty rows produced by the statement's affected-range query), no `BackgroundTask`.
- [ ] PR5.T8 GREEN: implement the response field.
- [ ] PR5.T9 RED→GREEN: update `TRIGGERED_TABLES` and the read-set guard (PR4.T10/T11) to cover the newly added tables.

## PR6 — Reconcile + divergence handlers, health/divergence endpoints (PROD GATE)
Design refs: D9, D10. Satisfies: SM R4, R8; enables Success Criterion "divergence = 0".

- [ ] PR6.T1 RED: `order_metrics.reconcile` handler (every 10 min, batches of 5000, set-based `INSERT...SELECT` into dirty, `reason='reconcile'`) enqueues orders with no metrics row OR `formula_version < CURRENT_FORMULA_VERSION` (SM R4 backfill-via-reconcile, R8 formula bump).
- [ ] PR6.T1a RED (design D3, D10; spec scenario 13): a parked order with no metrics row survives three consecutive reconcile runs still parked (`attempts == 5`, `last_error` intact, `poisoned_count` constant); a subsequent real input write (trigger path) un-parks it and the next drain recomputes it.
- [ ] PR6.T2 GREEN: implement reconcile via `order_metrics_enqueue_system` in `backend/app/workers/handlers/order_metrics.py`; register with `interval=timedelta(minutes=10)`.
- [ ] PR6.T3 RED: `order_metrics.divergence` handler (daily 04:00 AR, batches of 500) compares every stored field + status + `formula_version` vs `compute_order_metrics`, skips currently-dirty orders, writes summary to `worker_job_state.detail` JSON, opens `ml_ops_divergence` records (`kind='stored_metrics_mismatch'`, reusing `ml_orders_ops.py:463` model) for the first N ids, re-enqueues divergent orders.
- [ ] PR6.T4 GREEN: implement; register with `run_at_local=time(4,0)` (America/Argentina/Buenos_Aires).
- [ ] PR6.T5 RED: injected-mismatch integration test — divergence detects it, opens the `ml_ops_divergence` row, re-enqueues.
- [ ] PR6.T6 RED: `GET /api/ml-ops/order-metrics/health` (perm `ml_ops.ver`) — response shape `{queue_depth, oldest_dirty_age_s, claimed_count, poisoned_count, worker_heartbeat_at, worker_alive (heartbeat<30s), worker_draining, listener_mode, last_divergence, formula_version}`.
- [ ] PR6.T7 GREEN: `backend/app/routers/ml_order_metrics.py::health`.
- [ ] PR6.T8 RED: `POST /api/ml-ops/order-metrics/divergence/run` (perm `ml_ops.admin`-level) sets `worker_job_state.state='requested'`, `pg_notify('worker_jobs', name)`; worker picks it up on next wake.
- [ ] PR6.T9 GREEN: implement the on-demand trigger endpoint and worker-side channel listener for `worker_jobs`.
- [ ] PR6.T10 RED: `CURRENT_FORMULA_VERSION` bump test — per design's "Pending requirement from ml-ventas-neto-iibb-varios", the version bump must cause reconcile to requeue every row computed under the old formula (SM R8, scenario 14). Set the initial `formula_version` constant so this deploy's first value is ALREADY the bump (i.e., every pre-existing `ml_orders_ops.total_gauss` was populated under the OLD formula and has no `ml_order_metrics` row yet — reconcile's "no metrics row" branch covers full backfill AND the formula bump in one pass).
- [ ] PR6.T11 Run backend suite; deploy. Health endpoint live; queue starts draining automatically (still zero producers besides none yet — PR4/PR5 already deployed, so this is where real backfill volume starts).
- [ ] PR6.T12 OWNER: user (PROD GATE) — after deploy stabilizes, poll `GET /api/ml-ops/order-metrics/health` until `queue_depth=0`, `oldest_dirty_age_s` low, and trigger `POST /order-metrics/divergence/run`; confirm `last_divergence.divergent_count=0` and `missing_count=0` on a run, re-check after a monitoring window (design D10 gate) before authorizing PR7.

## PR7 — Readers switch to stored values (recalculating state; invariant test)
Design refs: D9 metrics_state, D13 (`, `orders/{id} invariant). Satisfies: SM R5, R6, R9(scenario), BREAKDOWN R33.
Depends on: PR6.T12 gate passing (user confirmation required before merge).

- [ ] PR7.T1 RED: `GET /orders/{id}` — `total_gauss`, `neto`, `markup` sourced from `ml_order_metrics`, NOT live `calcular_total_gauss`; chain final total equals stored `total_gauss` exactly when `metrics_state != 'recalculating'` (invariant test, BREAKDOWN R33 / SM R6).
- [ ] PR7.T2 GREEN: switch `breakdown_service.py` reader path to stored values; keep chain-line rendering from `ml_venta_deducciones`.
- [ ] PR7.T3 RED: when order is dirty (`recalculating`), detail response signals it explicitly and does NOT assert/claim the invariant (SM R6 second half).
- [ ] PR7.T4 GREEN: `metrics_state` derivation — `'recalculating'` if dirty row exists (wins), else stored `gauss_status`, else `'pending'`.
- [ ] PR7.T5 RED: listing/sort reads switch to stored `total_gauss` for the existing sort-by-total-gauss behavior (no live recompute, no per-row query loop).
- [ ] PR7.T6 GREEN: update `ml_ventas_ops.py` listing query.
- [ ] PR7.T7 Regression: existing listing/detail tests updated to stored-value fixtures (assertion mapping noted in PR description, per design D14/testing strategy).

## PR8 — Cleanup: retire live-recompute hooks
Design refs: Migration/Rollout "legacy columns kept until cleanup". Satisfies: keeps SM R3/R5 clean (no dual writers).

- [ ] PR8.T1 RED→GREEN: remove `marcar_stale` calls (7 sites: `etiquetas_upload.py:142,206`; `etiquetas_assignments.py:78,107,165,204,242`) — trigger-based capture supersedes them; confirm existing tests for those call sites still pass without the call (or are updated).
- [ ] PR8.T2 RED→GREEN: remove `refrescar_total_gauss_pendientes` slot (`sweep_service.py:1787`) and `ml_orders_ops.total_gauss_stale` usages.
- [ ] PR8.T3 Confirm `ml_orders_ops.total_gauss*` legacy columns are still WRITTEN by `recompute_order_metrics` (sort-key compatibility) but no longer read anywhere outside it; document in PR description that a later migration drops them (explicitly out of this change's scope).

## PR9 — Shared query layer extraction (pure refactor + search `q`)
Design refs: D12. Satisfies: KPI R7, R15; SEARCH R25, R26, R27.

- [ ] PR9.T1 RED: `build_scope(db, SalesFilter)` — order-level base query and group-level CTE reproduce the EXACT SAME rows/statuses as the current inline logic (`ml_ventas_ops.py:637-699` status exprs, `:566` group_key, `:702` `_collapse`), parity test against current behavior before/after extraction.
- [ ] PR9.T2 GREEN: `backend/app/services/ml_sales_query/filters.py` (`SalesFilter` dataclass, `build_scope`); `ml_ventas_ops.py` delegates to it.
- [ ] PR9.T3 RED: `q` search — digits → `order_id`, `pack_id`; `^MLA\d+$` → `item_id`; else ≥3 chars ILIKE on `buyer_nickname`, `seller_sku`, `title`; always bounded by seller+date (SEARCH R25).
- [ ] PR9.T4 GREEN: `backend/app/services/ml_sales_query/search.py`; wire `q` param into the listing router.
- [ ] PR9.T5 RED: search combines as intersection with active facets/toggles, not replacement (SEARCH R26); empty/no-match search returns explicit empty result, not an error (SEARCH R27).
- [ ] PR9.T6 GREEN: confirm via router-level test.
- [ ] PR9.T7 Confirm the extraction is dimension-pluggable per D12's `Dimension(name, join, key_expr)` contract (ships `NONE` + `DAY`) so KPI R15 (reusable by future metric consumers) holds — stub the contract even though PR9 ships no new dimension consumer yet.

## PR10 — Additive listing fields
Design refs: D13 route /sales. Satisfies: LISTING R28, R29, R31.

- [ ] PR10.T1 RED: route /sales response adds optional `item_category` (via `ml_order_item_costos.producto_item_id` → `productos_erp.categoria`; NULL when no frozen cost) without changing/removing existing fields (LISTING R28).
- [ ] PR10.T2 GREEN: implement the join; add `utils/categoryIcon.js` fallback mapping is FE (PR14), backend only returns the raw category string here.
- [ ] PR10.T3 RED: `city`, `province` (from `MlShipmentOps.receiver_address`), `shipping_substatus`, `coupon_amount` additive fields — captured-fixture based, null-safe on missing/varying JSONB shape.
- [ ] PR10.T4 GREEN: implement.
- [ ] PR10.T5 RED: server-derived unified `alert_level` (`ok`, `warning`, `error`) per D13 rule (error = unresolved/neto null; warning = provisional/recalculating/iva-not-reconciling/op-or-goods-unknown; ok) — replaces ad-hoc per-field FE flags (LISTING R29).
- [ ] PR10.T6 GREEN: implement `alert_level` derivation server-side.
- [ ] PR10.T7 RED: listing `neto`, `total_gauss`, `markup` values equal `ml_order_metrics` stored fields, not a live recompute (LISTING R31 — regression guard alongside PR7).
- [ ] PR10.T8 RED: `metrics_state` field present per row (`ok`, `provisional`, `unresolved`, `recalculating`, `pending`).

## PR11 — Doubtful switches + route /sales/kpis + aggregation
Design refs: D12 aggregate.py, D13 route /sales/kpis, D9 KPI exclusion. Satisfies: KPI R8-R14; SM R3 scenario 11 (worker_alive surfacing).
Depends on: PR6 (populated metrics), ideally PR7 (stored readers) merged first.

- [ ] PR11.T1 RED: `SalesFilter` gains `include_unknown`, `include_mixed`, `include_in_dispute`, `include_provisional` (defaults per R11: unknown OFF, in_dispute OFF, mixed ON, provisional ON) — `build_scope` applies each as an exclusion when OFF (KPI R9, R10, R11).
- [ ] PR11.T2 GREEN: extend `filters.py`.
- [ ] PR11.T3 RED: Mixta resolution — collapsed `operation_status='mixed' OR goods_status='mixed'`; `modo_logistico='mixed'` explicitly does NOT count (parity test vs `_collapse`, per design D12 resolution).
- [ ] PR11.T4 RED: `aggregate_order_metrics` — `groups_count`, `orders_count`, `gross_billed` (ARS; other currencies counted separately), `neto_sum`+`unknown_count`, `total_gauss_sum`+ok/provisional/unresolved counts, `markup_weighted_pct = SUM(tg)/SUM(costo)*100` (never average of %), `recalculating_count`, excluding recalculating orders from all sums (KPI R8, SM R3).
- [ ] PR11.T5 GREEN: `backend/app/services/ml_sales_query/aggregate.py`.
- [ ] PR11.T6 RED: `GET /sales/kpis` — per-toggle excluded counts (KPI R13); `recalculating_count` and `worker_alive` fields (derived from worker health).
- [ ] PR11.T7 GREEN: `ml_ventas_ops.py::sales_kpis` endpoint.
- [ ] PR11.T8 RED: parity test — for every switch combination (16 combos) + search + facets, route /sales/kpis aggregate equals summing exactly the rows route /sales would return for that same combination (KPI R14, R7).
- [ ] PR11.T9 RED: toggle state round-trips through URL query params (KPI R12) — backend param parsing test; full FE round-trip covered in PR16.

## PR12 — Additive detail (breakdown) fields
Design refs: D13 route /orders/{id}. Satisfies: BREAKDOWN R32, R34.
Independent of PR9-PR11 (per design dependency graph); may run in parallel chain position but ships sequentially per auto-chain constraint.

- [ ] PR12.T1 RED: route /orders/{id} response adds buyer real name (if present in `raw_order.buyer`), payment method, installments, shipment substatus — additive, existing `lines`, `item_lines`, `iva_decomposicion`, `cadena_total_gauss` unchanged (BREAKDOWN R32).
- [ ] PR12.T2 GREEN: implement in `breakdown_service.py` / router, captured-fixture based.
- [ ] PR12.T3 RED: IVA non-reconcile display includes specific `razones` sourced from existing persisted data (BREAKDOWN R34, design D5).
- [ ] PR12.T4 GREEN: implement.

## PR13 — FE layout shell: grid + SaleDetailPanel skeleton (modal removed, tests migrated)
Design refs: D14. Satisfies: PANEL R16, R18, R19, R20.

- [ ] PR13.T1 RED (Vitest+RTL): `VentasMLLayout` — CSS grid `minmax(0,1fr) var(--ventas-panel-width)` when a row is selected, single column otherwise; panel is a sticky `<aside aria-label="Detalle de venta">`, no overlay/`aria-modal`, `focus trap (PANEL R16, R20).
- [ ] PR13.T2 GREEN: implement frontend/src/components/ventasMl/VentasMLLayout.jsx` + CSS module (tokens only, light+dark).
- [ ] PR13.T3 RED: selection state driven by URL param (`orden`); Escape clears it and closes the panel without trapping focus; screen-reader live-region announces panel content changes (PANEL R19, R20).
- [ ] PR13.T4 GREEN: `useVentasMLFilters` / selection hook wiring.
- [ ] PR13.T5 RED: deselecting (no row selected) closes/hides the panel automatically (PANEL R18).
- [ ] PR13.T6 GREEN: implement.
- [ ] PR13.T7 RED: `<1280px` breakpoint — panel becomes a fixed right sheet without backdrop (still non-modal).
- [ ] PR13.T8 GREEN: implement responsive CSS.
- [ ] PR13.T9 Move `DesgloseDrawer.jsx`'s EXISTING sections (Producto/Comprador/Envío/Pago/waterfall/chain) into the new `SaleDetailPanel` shell verbatim (behavior unchanged); migrate their tests with an explicit assertion-mapping table in the PR description (54 DesgloseDrawer tests baseline, per design D14/testing strategy).
- [ ] PR13.T10 RED: table rows remain independently selectable/copyable while the panel is open (no overlay blocking pointer/selection events) (PANEL R17).
- [ ] PR13.T11 Delete `frontend/src/components/DesgloseDrawer.jsx` (+css/test) only after PR13.T9 migration is verified green.

## PR14 — FE listing restyle + search bar + chips + recalculating badge
Design refs: D14. Satisfies: LISTING (visual), SEARCH R25-R27 (FE), SM R3/R9 (recalculating UI).

- [ ] PR14.T1 RED: `SalesToolbar` search input — debounced, updates URL `q` param, calls route /sales with combined filters (SEARCH R25, R26).
- [ ] PR14.T2 GREEN: implement `SalesToolbar` + `useSales` hook.
- [ ] PR14.T3 RED: empty/no-match search shows explicit "sin resultados" state, not an error (SEARCH R27).
- [ ] PR14.T4 GREEN: implement.
- [ ] PR14.T5 RED: `SalesTable`, `SaleGroupRow`, `SaleOrderSubRow` restyle — `ProductCell` (placeholder thumbnail + title + SKU + MLA + qty, `CategoryIcon` from `utils/categoryIcon.js` keyed by `productos_erp.categoria`, fallback `Package`), stacked operation/goods badges, `EnvioCell` (mode + substatus), `MoneyCell` (importe+coupon, neto/Total Gauss/markup in `--font-mono`), `AlertIcon` from server `alert_level`.
- [ ] PR14.T6 GREEN: implement components + CSS modules (tokens only, light+dark, lucide icons).
- [ ] PR14.T7 RED: `FacetChips` show live counts consistent with the active filter set (LISTING R30).
- [ ] PR14.T8 GREEN: implement.
- [ ] PR14.T9 RED: `RecalculatingBadge` on a row whose `metrics_state='recalculating'` — no stale value presented as current (SM R3/R9 FE side).
- [ ] PR14.T10 GREEN: implement.
- [ ] PR14.T11 Migrate/extend the 57-test `VentasML.jsx` baseline with assertion-mapping table per PR description.

## PR15 — FE new panel sections
Design refs: D14. Satisfies: PANEL R21, BREAKDOWN R32/R34 (FE rendering), SM R6 (FE recalculating indicator).

- [ ] PR15.T1 RED: `CompradorSection` renders buyer real name (when present) + nickname; `EnvioSection` renders city/province/substatus; `PagoSection` renders method/installments/approval/paid/coupon (PANEL R21, BREAKDOWN R32).
- [ ] PR15.T2 GREEN: implement the three sections.
- [ ] PR15.T3 RED: `NetoWaterfall` + `IvaPorAlicuota` render per-rate breakdown + `razones` when IVA does not reconcile, no invented text (PANEL R21, BREAKDOWN R34).
- [ ] PR15.T4 GREEN: implement.
- [ ] PR15.T5 RED: `GaussChain` + markup render from the stored total; when `metrics_state='recalculating'`, shows an explicit recalculating indicator INSTEAD of asserting chain==stored (PANEL R21, SM R6 second half).
- [ ] PR15.T6 GREEN: implement.
- [ ] PR15.T7 Assertion-mapping update for the migrated DesgloseDrawer test set (completes the 54-test baseline migration started in PR13).

## PR16 — FE KPI strip + toggle switches + worker-down banner
Design refs: D14, D9. Satisfies: KPI R9, R10, R11, R12, R13.

- [ ] PR16.T1 RED: `KpiStrip`, `KpiCard` render count, gross billed, neto ML, SUM Total Gauss, average markup from route /sales/kpis response only (no client-side computation).
- [ ] PR16.T2 GREEN: implement + `useSalesKpis` hook.
- [ ] PR16.T3 RED: `DoubtfulSwitches`, `Switch` — four `role="switch"` controls ("A revisar", "Mixta", "En disputa", "Provisorio"), default states OFF/ON/OFF/ON on first load with no URL params (KPI R9, R11).
- [ ] PR16.T4 GREEN: implement.
- [ ] PR16.T5 RED: toggling updates BOTH table and KPI strip identically (shared params sent to route /sales and route /sales/kpis); state round-trips through URL query params (KPI R10, R12).
- [ ] PR16.T6 GREEN: implement.
- [ ] PR16.T7 RED: KPI strip shows per-toggle excluded counts when a toggle is OFF (KPI R13).
- [ ] PR16.T8 GREEN: implement.
- [ ] PR16.T9 RED: worker-down banner — shown when `worker_alive=false` and `queue_depth>0` ("Recálculo detenido"), sourced from route /sales/kpis (or health) response (SM R3 scenario 11 FE side).
- [ ] PR16.T10 GREEN: implement.
- [ ] PR16.T11 Light+dark visual pass against `docs/design/ventas-ml/{listado,detalle}.{html,jpg}` refs (pricing-app-design skill).

## PR17 — Resync endpoint + button
Design refs: D13 route /orders/{id}/resync. Satisfies: RESYNC R22, R23, R24.
Depends on: PR7 (stored readers) — resync must trigger the same recompute pipeline.

- [ ] PR17.T1 RED: `POST /orders/{id}/resync` (perm `ml_ops.resincronizar`) — HTTP fetch before write block, ingestion writes commit → triggers fire → order enqueued (RESYNC R22, R23; SM R3 scenario 8).
- [ ] PR17.T2 GREEN: implement, reusing the existing single-order ingestion fetch path (confirm reusability per design open dependency; if not reusable, flag as a blocking discovery before continuing this PR).
- [ ] PR17.T3 RED: endpoint polls (≤2s, 100ms step, short read blocks) for the dirty row to disappear; on success returns fresh detail; on timeout returns a body with `metrics_state='recalculating'` (explicit, not silent) (RESYNC R24, SM R3 scenario 8).
- [ ] PR17.T4 GREEN: implement polling + response shapes.
- [ ] PR17.T5 RED: concurrent resync on the same order — second request gets 409 via `pg_try_advisory_xact_lock(order_id)`.
- [ ] PR17.T6 GREEN: implement the advisory lock guard.
- [ ] PR17.T7 RED: resync failure (fetch error, permission denied) surfaces an explicit error state, no partial/silent success (RESYNC R24).
- [ ] PR17.T8 GREEN: implement error handling.
- [ ] PR17.T9 RED (FE): "Resincronizar" button in `SaleDetailPanel` — disabled while in-flight, shows recalculating/error states from the endpoint.
- [ ] PR17.T10 GREEN: implement FE button + wiring.

## Negative scenarios (woven throughout, tracked here for visibility)
Satisfies: `negative-scenarios` spec.

- [ ] NEG.T1 (PR4/PR5) Rolled-back writes never enqueue or notify — covered per-table in PR4.T3-T6, PR5.T1.
- [ ] NEG.T2 (PR3) Poisoned orders after 5 failed attempts never block other orders — PR3.T4.
- [ ] NEG.T3 (PR6/PR7) Worker down: orders stay `recalculating` indefinitely, UI shows "Recálculo detenido", never presented as fresh — PR6 health, PR16.T9.
- [ ] NEG.T4 (PR1/PR7) `unresolved` never renders a fabricated number in listing/detail/KPI — PR1.T1, PR10.T8, PR15.T5.
- [ ] NEG.T5 (PR9/PR10) Empty search / empty filtered set is explicit, not an error and not a false-zero KPI — PR9.T5, PR14.T3.
- [ ] NEG.T6 (PR17) Resync failure is explicit, never silent partial success — PR17.T7.
- [ ] NEG.T7 (all BE PRs) `ruff format app/ tests/ alembic/` run before every push (project convention, CI enforces `ruff format`).

## Chain / Dependency Graph

```
PR1 -> PR2 -> PR3 -> PR4 -> PR5 -> PR6 [GATE: OWNER user] -> PR7 -> PR8
                                                  \
                                                   -> PR9 -> PR10 -> PR11 (needs PR6, ideally PR7)
PR12 (independent of PR9-11; additive detail fields)
PR13 -> PR14 (after PR10 for stored/additive fields)
     -> PR15 (after PR12 for buyer/payment/shipment fields)
     -> PR16 (after PR11 for KPI/toggles)
PR17 (after PR7; resync needs stored-metrics recompute pipeline live)
```

Sequential auto-chain order actually merged (one branch at a time off `origin/main`): **PR1, PR2, PR3, PR4, PR5, PR6, PR7, PR8, PR9, PR10, PR11, PR12, PR13, PR14, PR15, PR16, PR17.** PR12 could move earlier (independent) but stays in chain order for auto-chain simplicity; note in PR12's description that it has no BE dependency beyond PR1.

## Review Workload Forecast

| PR | Scope | Est. lines | Depends on | Risk |
|---|---|---|---|---|
| PR1 | Tables, models, compute/recompute producer, migration | ~380 | — | Low (inert, additive) |
| PR2 | Generic worker runtime, systemd unit, deploy.sh, runbook | ~350 | PR1 | Med (new infra pattern, LISTEN/PgBouncer subtlety) |
| PR3 | Claim/release/drain, PG fixtures, concurrency tests | ~350 | PR2 | Med (SKIP LOCKED/lease correctness) |
| PR4 | Enqueue fn + per-order triggers + read-set guard | ~420 (flagged: 6 tables × write-kind tests) | PR3 | High (correctness-critical, first live producers) |
| PR5 | Etiquetas + config + transportes statement triggers | ~400 | PR4 | High (5 fan-out sources, previously-missed writers) |
| PR6 | Reconcile + divergence + health/divergence endpoints | ~350 | PR5 | High (PROD GATE, formula_version bump correctness) |
| PR7 | Readers switch to stored values + invariant | ~300 | PR6 gate passed | High (money-path regression surface) |
| PR8 | Cleanup: remove legacy hooks | ~150 | PR7 | Low |
| PR9 | Shared query layer extraction + search | ~380 | PR8 (chain order; logically only needs PR1) | Med (parity refactor) |
| PR10 | Additive listing fields | ~300 | PR9 | Low-Med (JSONB shape variance) |
| PR11 | Doubtful switches + KPI endpoint + aggregation | ~400 | PR10, PR6 (data), PR7 (ideally) | Med (parity tests, weighted markup math) |
| PR12 | Additive detail fields | ~200 | PR1 (chain: after PR11) | Low |
| PR13 | FE layout shell + panel skeleton + test migration | ~400 (flagged: 54-test migration) | PR7 | Med (accessibility/non-modal correctness) |
| PR14 | FE listing restyle + search + chips + badge | ~420 (flagged: many small components) | PR10, PR13 | Low-Med (visual + design tokens) |
| PR15 | FE new panel sections | ~350 | PR12, PR13 | Low-Med (test migration tail) |
| PR16 | FE KPI strip + switches + worker banner | ~350 | PR11, PR13 | Med (URL state, parity with BE toggles) |
| PR17 | Resync endpoint + button | ~350 | PR7 | Med (advisory lock, polling, external ML call) |

Bottleneck: PR6's PROD GATE (owner confirmation of divergence=0) blocks PR7, which in turn blocks PR11(data), PR13, PR16, PR17 — the single largest serialization point. PR4/PR5/PR6 are money-path-critical (missed trigger = silently wrong metric) and warrant the most review attention per the design's own risk table.

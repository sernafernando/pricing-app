# Design: Ventas ML redesign (authoritative stored metrics + LISTEN/NOTIFY worker + shared query layer + fixed detail panel + KPI strip)

Revision 4 (2026-09-22): liveness and lease decoupled from work — a dedicated heartbeat thread writes the worker heartbeat and renews the leases of claims held by this process every ~5 s (D4 step 5); each batch is bounded by wall time, and a batch timeout charges nobody and retries the batch one order at a time (D5).
Revision 3 (2026-09-22): worker review fixes — expired leases count as failed attempts (D5), separate input-write vs system enqueue so reconcile never un-parks (D3, D10), time-based per-batch heartbeat (D4), claim-token fence on the metrics write against stale overwrites (D3, D5).
Revision 2 (2026-09-21). Replaces D4 (before_commit same-txn recompute + cron drain) by BINDING USER DECISION: no cron anywhere, no global before_commit hook; triggers enqueue + pg_notify, a dedicated long-running worker (systemd) recomputes. Skills: pricing-app-backend, pricing-app-testing-ci (+ -frontend, -design, -pricing-logic, -ml-integration from rev 1). Inputs: proposal #2104 (rev 2), spec #2105 (rev 1), explore #2103.

## Technical Approach

Three layers, bottom-up, each shippable alone:

1. **Stored metrics (domain-neutral)** — package `app/services/order_metrics/` owning `ml_order_metrics` (1:1 with `ml_orders_ops`). One producer `compute_order_metrics()` wraps the EXISTING formula functions (`compute_neto_by_order_ids`, `descomponer_neto`, `calcular_total_gauss`); one writer `recompute_order_metrics()` (absorbs `persistir_total_gauss`, which becomes a thin delegating alias). No second formula anywhere.
2. **Change capture + asynchronous recompute** — column-scoped DB triggers on every table the formula reads upsert affected `order_id`s into `ml_order_metrics_dirty` and `pg_notify('order_metrics_dirty', '')` inside the writer's transaction (notify delivered only on COMMIT; rolled-back writes neither enqueue nor wake). A generic long-running worker process (`app/workers/`, systemd unit `pricing-worker`) LISTENs, claims dirty orders in batches with `FOR UPDATE SKIP LOCKED` + lease, recomputes via the single producer in short `get_background_db()` blocks, and deletes the queue row only if its version did not change meanwhile. Target latency < 1 s. Orders in the queue are explicitly "recalculating": excluded from KPI sums and counted visibly.
3. **Shared ML sales query layer** — `app/services/ml_sales_query/`: one filter/scope builder used by listing, KPI and future metric consumers; one aggregation function over stored metrics with a pluggable dimension contract.

Frontend (unchanged from rev 1): VentasML container with URL-driven filter state; non-modal fixed side panel; KPI strip + four `role="switch"` toggles; all numbers from the API.

## Why triggers (the load-bearing finding — unchanged)

The formula reads 12 tables; ~30 write sites; the existing `marcar_stale` hooks cover only 7 (etiquetas_upload.py:142,206; etiquetas_assignments.py:78,107,165,204,242). Already MISSED today: toggle turbo (etiquetas_assignments.py:276), lluvia (:346), lluvia masivo (:379), pistoleado logistica (etiquetas_pistoleado.py:112,130,135), manual label edit (etiquetas_manual.py:520,533,534), enrichment turbo (etiqueta_enrichment_service.py:149,419,509), reprogram fecha_envio (cron_reprogramar_envios_no_entregados.py:193), colecta delete (etiquetas_colecta.py:1033), pistoleado delete (etiquetas_pistoleado.py:416), rma labels (rma_seguimiento.py:1805,2087), retiro labels (etiqueta_retiro_service.py:180), all config tables. Hand-placed hooks rot; capture must live where writes land.

## Architecture Decisions

### D1 — Dedicated table `ml_order_metrics` (unchanged)
**Choice**: new table keyed by `order_id` (FK ON DELETE CASCADE), owned by `app/services/order_metrics/`.
**Alternatives**: extend `ml_orders_ops` (already has `total_gauss`, `_at`, `_stale`, `_provisional`).
**Rationale**: `ml_orders_ops` is an ingestion mirror; mixing derived metrics couples ingestion upserts (`ON CONFLICT ... WHERE ml_last_updated < `) with metric writes and makes the upsert trigger-recursive. Separate lifecycle (formula_version, backfill, divergence), joinable from any consumer; future grains (per-item) are siblings. Legacy `ml_orders_ops.total_gauss*` keep being written during transition (sort key), dropped in a later cleanup PR.

### D2 — What is stored (unchanged except "recalculating" source)
| column | type | meaning |
|---|---|---|
| order_id | BIGINT PK FK | |
| neto | NUMERIC(14,2) NULL | from `compute_neto_by_order_ids` |
| neto_sin_iva | NUMERIC(14,2) NULL | from `descomponer_neto` |
| iva_reconcilia | BOOLEAN NULL | |
| costo_mercaderia | NUMERIC(14,2) NULL | chain line, for weighted markup |
| total_gauss | NUMERIC(14,2) NULL | NULL iff status=unresolved |
| markup_pct | NUMERIC(9,2) NULL | total_gauss / costo * 100 (existing formula) |
| gauss_status | VARCHAR(16) NOT NULL CHECK IN ('ok','provisional','unresolved') | |
| provisional_falta | VARCHAR(64) NULL | |
| unresolved_reason | VARCHAR(64) NULL | |
| formula_version | SMALLINT NOT NULL | bump → reconcile job re-enqueues all |
| computed_at | TIMESTAMPTZ NOT NULL | |
Chain lines stay in `ml_venta_deducciones` (written by the same recompute). Indexes: PK; `ix_ml_order_metrics_status`; `ix_ml_order_metrics_total_gauss` (DESC NULLS LAST). KPI scope from `ml_orders_ops` (seller_id is indexed; date_created is NOT indexed — add `ix_ml_orders_ops_seller_date (seller_id, date_created)` in PR 1). Unresolved is NULL + status, never 0. "Recalculating" is NOT a stored status: derived as `EXISTS (dirty row for order_id)` — a value is never claimed fresh while queued.

### D3 — Capture via column-scoped triggers into a versioned dirty queue + pg_notify (revised: PG-only, versioned, notify)
**Choice**: table
`ml_order_metrics_dirty(order_id BIGINT PK, version BIGINT NOT NULL DEFAULT 1, reason VARCHAR(32) NOT NULL, enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now(), claimed_at TIMESTAMPTZ NULL, claimed_by VARCHAR(64) NULL, claim_token UUID NULL, attempts SMALLINT NOT NULL DEFAULT 0, last_error TEXT NULL, suspect BOOLEAN NOT NULL DEFAULT false)` + index on (enqueued_at). `suspect` marks orders released uncharged by a batch timeout so they are retried alone, durably across restarts (D5).
Two PL/pgSQL enqueue helpers with DIFFERENT conflict semantics (rev 3, review finding: reconcile must not un-park):
- **Input-write enqueue** `order_metrics_enqueue(ids BIGINT[], reason TEXT)` — the ONLY one called by triggers:
`INSERT ... SELECT unnest(ids) ON CONFLICT (order_id) DO UPDATE SET version = dirty.version + 1, enqueued_at = now(), reason = EXCLUDED.reason, attempts = 0, last_error = NULL, suspect = false` then `PERFORM pg_notify('order_metrics_dirty', '')`. It does NOT touch `claimed_at`, `claimed_by`, `claim_token`: an in-flight claim stays owned by its worker, the version bump alone makes that worker's release keep the row dirty (D5 fence). Resetting `attempts`/`last_error` is intentional: a new input write is a new chance, so this upsert un-parks a previously poisoned order the moment its inputs change again.
- **System enqueue** `order_metrics_enqueue_system(ids BIGINT[], reason TEXT)` — used by `order_metrics.reconcile` and the divergence re-enqueue: `INSERT ... SELECT unnest(ids) ON CONFLICT (order_id) DO NOTHING` + the same notify. An existing dirty row (claimed, pending, or parked) is left untouched: no version bump, no `attempts`/`last_error` reset. A parked order therefore stays parked across reconcile cycles (spec scenario 13, `poisoned_count` stable) and only a real input write un-parks it. Empty payload on purpose: Postgres folds identical (channel, payload) notifications within one transaction into ONE delivery, so a 10k-row fan-out wakes the worker once. Row triggers for per-order tables; STATEMENT-level triggers with transition tables (`REFERENCING OLD TABLE / NEW TABLE`) for config tables and bulk-prone tables so fan-outs are one set-based insert, not N.
Scope (unchanged column lists): ml_orders_ops (INSERT; UPDATE OF shipping_id, date_created, has_no_shipping_tag, pack_id; DELETE; shipping_id change also enqueues siblings of OLD and NEW shipping_id — Flex split divisor), ml_order_items_ops, ml_order_item_costos, ml_payments_ops (OLD/NEW order_id; UPDATE OF status, net_received_amount, transaction_amount_refunded, shipping_amount, order_id), ml_payment_charges (payment_id → order_id), ml_shipments_ops (UPDATE OF logistic_type, receiver_address; sender/receiver cost and raw_costs NOT in read set → `_sync_shipment_costs` stays trigger-free), etiquetas_envio (INSERT; DELETE; UPDATE OF shipping_id, logistica_id, costo_override, fecha_envio, es_turbo, es_lluvia, transporte_id; lat/lng writes do not fire). Config fan-out: varios_venta_pct (orders with date_created in OLD∪NEW [fecha_desde, fecha_hasta]), logistica_costo_cordon (self_service orders whose label has that logistica_id), codigos_postales cordon, configuracion WHEN clave IN ('lluvia_offset_tipo','lluvia_offset_valor'), **transportes UPDATE OF cp** (RESOLVED: column is `transportes.cp`, read by breakdown_service.py:423-432 as `coalesce(Transporte.cp, eff_zip)`; writers transportes.py:147 create — no labels yet, no fan-out needed — and :196 update → orders whose label has that transporte_id).
DDL in ONE module `app/services/order_metrics/triggers.py` (Postgres only), applied by the Alembic migrations and by an `after_create` listener that fires ONLY for `postgresql` dialect (so `@pytest.mark.postgres` fixtures get identical triggers; SQLite `create_all` gets none).
**Alternatives**: (a) explicit hooks per writer (proven to rot); (b) ORM events (miss Core upserts, bulk update, scripts, psql); (c) CDC/logical replication (over-engineering); (d) SQLite trigger twins (rejected in rev 2 — see D8).
**Rationale**: storage-layer capture is complete by construction, including scripts and manual SQL. Versioning makes re-dirty-while-recomputing detectable (D5). Structural guard: a read-set test instruments `compute_order_metrics` with `before_cursor_execute` and fails if any read table is missing from `TRIGGERED_TABLES`.

### D4 — Recompute by a dedicated LISTEN/NOTIFY worker (REPLACES rev 1 before_commit + cron drain)
**Choice**: new generic package `app/workers/` run as `python -m app.workers.run` under systemd unit `pricing-worker.service` (versioned in repo at `deploy/systemd/pricing-worker.service`; `deploy.sh` step 6 restarts it after `pricing-api`, same warn-not-fail pattern as deploy.sh:370). Loop:
1. Open a DEDICATED listener connection with `DATABASE_URL_DIRECT` (existing setting, `app/core/config.py:16`, already used by `alembic/env.py` and configured in production) — psycopg2 raw connection, autocommit, `LISTEN order_metrics_dirty`. **Must bypass PgBouncer**: `DATABASE_URL` points at PgBouncer in transaction mode (database.py:40-64), where LISTEN is not supported (session not pinned). Writers' `pg_notify` via PgBouncer is fine (it is a statement inside their txn). If `DATABASE_URL_DIRECT` is unset → run in poll-only mode and log a WARNING (degraded latency, never silent loss).
2. `select()` on the listener socket with timeout = min(safety_poll_interval (5 s), next scheduled job due). On wake: drain notifies, debounce 50 ms, run the order-metrics drain handler until the queue is empty of claimable rows. On timeout: run the drain anyway (safety poll for missed notifies: worker restart, listener reconnect) and any due scheduled job.
3. On startup: full drain before first LISTEN wait (covers anything enqueued while down).
4. Listener connection loss → reconnect with backoff; drain immediately after reconnect.
5. Heartbeat thread (rev 4, REPLACES the rev 3 in-handler heartbeat; review finding: `statement_timeout` bounds one statement, not a batch, and `compute_order_metrics` runs several statements per batch with no heartbeat inside, so a live worker could read as dead and overrun its lease). The worker process starts a dedicated daemon thread `HeartbeatThread` (`app/workers/heartbeat.py`) that, every `heartbeat_interval` (5 s), independently of whatever the main thread is doing:
   (a) upserts `worker_job_state` row `name='worker'` (`heartbeat_at`, pid, host, `detail = {draining: bool, drained_in_run: int}`, values read from a lock-protected in-process snapshot the main thread updates);
   (b) renews the lease of every claim this process currently holds: `UPDATE ml_order_metrics_dirty SET claimed_at = now() WHERE claimed_by = :worker AND claim_token = ANY(:tokens)`, where `:tokens` is the lock-protected in-process set of live claim tokens (added by `claim_dirty`, removed after `fenced_store`/`mark_failed`/release commits). The token filter means a renewal can never resurrect a claim another worker already took.
   **Connection choice**: each tick is its own short `get_background_db()` block (NullPool under `/workers/`, D4 DB sessions) with `SET LOCAL statement_timeout = '5s'` and `lock_timeout = '2s'`, one transaction for (a)+(b), committed immediately. Chosen over a dedicated long-lived direct connection because: it works identically when `DATABASE_URL_DIRECT` is unset (poll_only mode), NullPool gives the thread its own physical connection so no Session or connection is ever shared across threads, it follows the post-2026-06-24 short-block rule, and a PgBouncer or network blip costs one missed tick instead of a reconnect state machine. The renewal UPDATE touches rows the batch transaction does not lock until its final fence step (D5 step 2), and the fence holds each row lock only for the final write, so the tick waits at most milliseconds; if `lock_timeout` fires, the tick logs and retries next interval (the 120 s lease tolerates many missed ticks).
   **Consequences**: `worker_alive` = `now() - heartbeat_at < 30 s` depends ONLY on the process and its heartbeat thread being alive, never on batch, statement, or backfill duration. A lease expires only if the PROCESS died or the heartbeat thread is wedged/dead, so `lease_expired` is a fair charge (D5). Health exposes `worker_draining` from `detail.draining`.
   **Thread death detection**: the main loop checks `heartbeat_thread.is_alive()` and the thread's last successful tick on every iteration and between batches; if the thread is dead, or has not completed a tick for `3 × heartbeat_interval`, the main thread logs CRITICAL, stops starting work, and exits non-zero (`sys.exit(70)`) so systemd (`Restart=always`) restarts the process. Its claims then expire and are charged like any death, which is correct: the worker was no longer able to prove liveness.
DB sessions: `_is_script_context()` extended to treat `/workers/` like `/scripts/` → NullPool through PgBouncer (one short connection per block; the worker never holds a pool). All DB work in short `get_background_db()` blocks (post-2026-06-24 incident rule). `statement_timeout` does not apply under NullPool checkout event; handlers set `SET LOCAL statement_timeout = '30s'` per block.
**Alternatives**: (a) global `Session.before_commit` recompute (rejected by user; also silently missed non-ORM writers and bloated writer txns); (b) cron drain (rejected by user; minute-granularity latency); (c) asyncio task inside `pricing-api` under the existing flock bg lock (main.py:124-249) — rejected: restarts with every API deploy, shares the API's 15+10 pool (pool-exhaustion incident surface), and the user asked for a dedicated service; (d) Celery/RQ + Redis — new infra, violates boring-tech rule; Postgres is already the queue.
**Rationale**: notify-on-commit gives sub-second latency without cron; the queue table is the durable source of truth, NOTIFY is only a wake-up hint, so lost notifies cost latency, never correctness.

### D5 — Claim / recompute / version-checked delete (concurrency)
Per batch (default 200), two short blocks (rev 3: recompute and release are ONE fenced transaction):
1. **Claim** (own txn). First, in the same txn, charge expired leases: `UPDATE ml_order_metrics_dirty SET attempts = attempts + 1, last_error = 'lease_expired', claimed_at = NULL, claimed_by = NULL, claim_token = NULL WHERE claimed_at < now() - :lease` (rows locked by a live claimer are skipped via a `FOR UPDATE SKIP LOCKED` subselect). Then claim: `UPDATE ml_order_metrics_dirty d SET claimed_at = now(), claimed_by = :me, claim_token = gen_random_uuid() FROM (SELECT order_id FROM ml_order_metrics_dirty WHERE claimed_at IS NULL AND attempts = 0 AND NOT suspect ORDER BY enqueued_at LIMIT :n FOR UPDATE SKIP LOCKED) c WHERE d.order_id = c.order_id RETURNING d.order_id, d.version, d.claim_token, d.attempts`. Commit → locks released immediately, so writers' trigger upserts never wait on the worker. Lease default 120 s; SKIP LOCKED lets a second worker coexist.
2. **Recompute + fenced release** (one txn, per-order SAVEPOINT): compute from committed inputs; then per order `SELECT version FROM ml_order_metrics_dirty WHERE order_id = :id AND claim_token = :token FOR UPDATE`. No row → this worker no longer owns the claim (lease expired and another worker reclaimed, or row deleted) → ROLLBACK TO SAVEPOINT, nothing written. Row found → upsert ml_order_metrics + ml_venta_deducciones + legacy columns, then: version unchanged → `DELETE` the dirty row; version changed (an input write landed meanwhile) → `UPDATE ... SET claimed_at = NULL, claimed_by = NULL, claim_token = NULL` so the row is re-claimed next pass. Commit. The fence row lock is taken only at the end, so a writer's trigger upsert waits at most for this final write, never for the compute.

**Ordering is enforced on the metrics write itself (rev 3, review finding: lost update between two workers).** Only the current claim-token holder can commit an ml_order_metrics write, and the fence check, the metrics upsert and the delete/unclaim happen under one row lock in one transaction. A worker whose lease expired (slow, or a zombie) finds its token gone and writes nothing, so an older snapshot can never commit after a newer one. The input-write enqueue (D3) never clears a claim; it only bumps `version`, which forces the owner to leave the row dirty. Any metrics value committed by the owner from a snapshot older than a concurrent input write is therefore always covered by a still-present dirty row (`recalculating`, excluded from KPI) until a later recompute replaces it. Rejected: a `source_version` column on ml_order_metrics with a conditional upsert — the dirty `version` restarts at 1 whenever the row is deleted and re-inserted, so it is not monotonic across queue lifetimes and would need a separate sequence; the fence token gives the same guarantee with no extra state on the metrics table.

**Attempts rule (precise).** `attempts` increments in exactly two cases: (a) an exception raised while recomputing that order (Failure below); (b) its claim is found with an EXPIRED lease and no release — because the heartbeat thread renews every held claim every ~5 s (D4 step 5), this happens only when the worker PROCESS died (OOM, segfault, SIGKILL, exit on heartbeat-thread death) or its heartbeat thread is wedged; a live but slow batch keeps renewing its leases and is never charged this way. It NEVER increments on a normal claim, on a version-changed release (a lost race is a re-dirty, not a failure), or on a batch-level timeout (below). At `attempts >= 5` the row is parked: excluded from claim, counted in `poisoned_count`. To keep an innocent order from being charged for a batch-mate that killed the process, a row with `attempts > 0` is claimed in a batch of ONE (a separate claim query `WHERE claimed_at IS NULL AND attempts < 5 AND (attempts > 0 OR suspect) ... LIMIT 1` runs before the normal batch, which only takes `attempts = 0 AND NOT suspect`), so a process-killing order isolates itself and parks after 5 expired leases while the rest of the queue keeps draining. **Batch wall-time bound (rev 4).** Lease renewal alone would let a live batch hold its fence locks and claims forever, so each batch is also bounded in total wall time: the recompute+fenced-release transaction sets `SET LOCAL statement_timeout = '30s'` (one statement) AND runs under a per-batch wall-clock budget `batch_timeout` (default 60 s), enforced by the drain checking elapsed time between statements/orders and, for a single statement, by the statement timeout. When the budget is exceeded (or a statement timeout fires while computing the BULK batch, before any per-order attribution is possible), the drain raises `BatchTimeout`, ROLLS BACK the whole batch transaction, and releases the batch's claims WITHOUT charging anyone and marks them `suspect = true` (`UPDATE ... SET claimed_at = NULL, claimed_by = NULL, claim_token = NULL, suspect = true WHERE claim_token = ANY(:tokens)`, attempts unchanged). The `suspect` flag is DURABLE: the singleton retry does not depend on in-process memory, so a worker restart between the release and the retry still retries each of those orders alone and never puts them back into a 200-row batch (no livelock). `suspect` is cleared when the order is recomputed successfully (row deleted) and by the input-write enqueue upsert (a new input is a new chance). Those orders are then retried ONE BY ONE (the same singleton path as the "suspects retried singly" rule above: each is claimed alone, recomputed alone under the same bounds). Only an order that exceeds the bound or raises while ALONE is charged through `mark_failed` (`last_error = 'timeout'` or the exception). Innocent batch-mates of a slow order therefore never accrue attempts. `ctx.deadline` still stops starting new batches so scheduled jobs get their slot. Batch size (default 200) is tunable downward if production batches approach `batch_timeout`.
Failure: exception in step 2 → rollback to the order's savepoint, increment `attempts`, set `last_error`, clear claim (fenced by token). Per-order isolation: savepoints (precedent: ingestion quarantine per-order SAVEPOINT, conftest pg_orders_ops_engine) so one bad order does not block 199. Parked rows are visible, never silently dropped; only the input-write enqueue (D3) un-parks them — the system enqueue used by reconcile does not.
Metrics inputs are recomputed from committed state only; no multi-order locking needed because recompute is idempotent and the claim token plus version check serialize outcomes.

### D6 — Generic worker, pluggable job handlers (seed for crontab migration)
```python
class JobHandler(Protocol):
    name: str                       # 'order_metrics.drain'
    channels: Tuple[str, ...]       # LISTEN channels that wake it; () = schedule-only
    interval: Optional[timedelta]   # periodic schedule; None = event/poll only
    run_at_local: Optional[time]    # daily wall-clock slot (America/Argentina/Buenos_Aires)
    def run(self, ctx: WorkerContext) -> JobResult: ...   # must use short get_background_db blocks, respect ctx.deadline
```
`app/workers/registry.py` holds an explicit list (no auto-discovery). `worker_job_state(name PK, last_run_at, last_success_at, state, detail, heartbeat_at)` persists schedule state so restarts do not re-run daily jobs twice (run if `last_success_at` < today's slot). Jobs run sequentially in one thread; a job's `run` yields between batches via `ctx.deadline` so the drain stays responsive (a long job runs in time slices, drain gets priority on each wake). Shipped handlers ONLY: `order_metrics.drain` (event + safety poll), `order_metrics.reconcile` (every 10 min), `order_metrics.divergence` (daily 04:00). Migrating existing cron jobs is explicitly out of scope.

### D7 — One producer, compute split from persist (unchanged)
`compute_order_metrics(db, ids) -> Dict[int, OrderMetrics]` (pure reads, bulk, O(1) queries per batch) and `recompute_order_metrics(db, ids)` (compute + upsert, no commit). Divergence job calls `compute_*` and compares; backfill = enqueue + drain; resync = ingestion writes → triggers → worker.

### D8 — Postgres-only triggers tested on real Postgres (REVISED: drop SQLite twins)
Verified: CI already runs a `postgres:16` service in the backend job (.github/workflows/ci.yml:76-136): `pytest -m "not postgres" -n 4` then `pytest -m postgres` serially with `POSTGRES_TEST_URL`; conftest.py:352-540 has per-domain PG engine fixtures (pg_payments_engine, pg_orders_ops_engine) that create only needed tables. Decision: triggers, NOTIFY, SKIP LOCKED, version-checked delete and worker loop are tested ONLY under `@pytest.mark.postgres` with a new `pg_order_metrics_engine` fixture (creates the 12 input tables + metrics/dirty/job-state tables, then applies `triggers.py` DDL). SQLite suite gets no triggers → the ~6400 existing tests are unaffected (they never see dirty rows) and pure compute/status tests stay on SQLite. **No CI change needed.** Rationale: SQLite twins would be a second implementation to keep in sync with no LISTEN/SKIP LOCKED equivalents — a green SQLite trigger test would prove nothing about production (same argument that created pg_payments_engine). Cost: ~40 more serial PG tests (each fixture txn-rolled-back; worker tests need committed data → use a separate schema-per-test truncate fixture, since NOTIFY is only delivered on commit).

### D9 — Recalculating state, KPI exclusion, observability
- `metrics_state` per order: 'recalculating' if dirty row exists (wins over stored status), else stored gauss_status, else 'pending' (no metrics row yet).
- KPI: orders in the queue are excluded from all sums and reported as `recalculating_count`; UI shows "N recalculando" chip. Never a stale number as good.
- Health: `GET /api/ml-ops/order-metrics/health` (perm `ml_ops.ver`): `{queue_depth, oldest_dirty_age_s, claimed_count, poisoned_count, worker_heartbeat_at, worker_alive (heartbeat < 30 s, written every ~5 s by the heartbeat thread — see D4 step 5), worker_draining, listener_mode ('notify'|'poll_only'), last_divergence: {run_at, divergent_count, missing_count}, formula_version}`. Worker down ⇒ queue grows, oldest age grows, heartbeat stale — visible in the endpoint and the KPI strip banner ("Recálculo detenido" when worker_alive=false and queue_depth>0).
- KPI response carries `recalculating_count` and `worker_alive` so the screen itself surfaces a dead worker.

### D10 — Backfill, reconcile, divergence (REVISED: no scripts/cron; worker jobs)
- `order_metrics.reconcile` (every 10 min, batches of 5000 via set-based call to the SYSTEM enqueue `order_metrics_enqueue_system`, reason 'reconcile', ON CONFLICT DO NOTHING — see D3): enqueues orders with no metrics row, or `formula_version < CURRENT_FORMULA_VERSION`, that have no dirty row yet. It never resets `attempts` or `last_error`, so a parked (never-succeeded, hence metrics-less) order stays parked across reconcile cycles. This IS the backfill: deploying PR "reconcile" makes the worker populate every pre-existing order automatically, throttled; bumping formula_version self-re-enqueues. No manual script.
- `order_metrics.divergence` (daily 04:00 AR): batches of 500 in short blocks; compares every stored field + status + formula_version vs `compute_order_metrics`, skipping orders currently dirty; writes summary to `worker_job_state.detail` (JSON) and opens `ml_ops_divergence` records kind `stored_metrics_mismatch` (reuse existing table, models ml_orders_ops.py:463) for the first N ids, then re-enqueues divergent orders via the system enqueue (self-heal, still visible). On-demand run: `POST /api/ml-ops/order-metrics/divergence/run` (perm `ml_ops.admin`-level; sets `worker_job_state.state='requested'`, worker picks it on next wake via `pg_notify('worker_jobs', name)`).
- GATE: readers-switch PR merges only after prod health shows backlog drained, missing_count=0 and divergent_count=0 on a run, re-checked over a monitoring window.

### D11 — "% de varios" and other fan-outs
Config write commits fast (statement trigger enqueues N rows set-based, one notify). `crear_varios_venta_pct` (configuracion.py:315) returns `recalculando: N` (count of dirty rows it produced, from the statement's affected range query). No BackgroundTask. Worker drains at batch speed; affected orders show 'recalculating' until done.

### D12 — Shared query layer `app/services/ml_sales_query/` (unchanged, Mixta resolved)
- `filters.py`: `SalesFilter` + `build_scope(db, f)` returning order-level base query (status exprs moved verbatim from ml_ventas_ops.py:637-699) and group-level CTE (group_key string per ml_ventas_ops.py:566, collapsed statuses via `CASE WHEN count(DISTINCT x)>1 THEN 'mixed' ELSE min(x)`, parity-tested against `_collapse` ml_ventas_ops.py:702), any_provisional, any_unresolved, any_recalculating.
- Group semantics unchanged: filter selects GROUPS; ANY member matches; all members returned.
- Switch classes (group level): A revisar = collapsed op_status 'unknown' OR goods_status 'unknown' (spec R9); En disputa = op_status 'in_dispute'; **Mixta (RESOLVED) = collapsed operation_status = 'mixed' OR goods_status = 'mixed'** — spec R9 says "pack status mixed" and both are the pack's status axes rendered as badges; `modo_logistico` 'mixed' (ml_ventas_ops.py:592-595) is a logistics attribute, NOT a status, and does not count; Provisorio = any member 'provisional'. Excluded if in ANY switched-off class; explicit facet selection overrides its switch; response echoes effective switches.
- Search `q` (unchanged): digits → order_id/pack_id; `^MLA\d+$` → item_id; else ≥3 chars ILIKE on buyer_nickname, seller_sku, title; always bounded by seller + date. pg_trgm only if EXPLAIN demands and available.
- `aggregate.py`: measures over stored metrics, excluding recalculating orders: groups_count, orders_count, gross_billed (ARS; other currencies counted), neto_sum + unknown_count, total_gauss_sum + ok/provisional/unresolved counts, markup_weighted_pct = SUM(tg)/SUM(costo)*100 (never average of %), recalculating_count. Dimension contract `Dimension(name, join, key_expr)`; ships NONE + DAY. Per-item grain = future sibling table.

### D13 — Endpoints (additive, router ml_ventas_ops.py)
- `GET /sales`: optional `q`, 4 switches; per-order additive: city, province, shipping_substatus, coupon_amount, metrics_state ('ok'|'provisional'|'unresolved'|'recalculating'|'pending'), alert_level (error = unresolved/neto null; warning = provisional/recalculating/iva not reconciling/op or goods unknown; ok), **item_category (RESOLVED)**: `productos_erp.categoria` via `ml_order_item_costos.producto_item_id` → `productos_erp.item_id` (frozen cost linkage, already per order line); NULL when no frozen cost → FE fallback icon Package. ML `raw_item.category_id` rejected: opaque MLA category ids, no human mapping stored.
- `GET /sales/kpis`: as rev 1 plus `recalculating_count`, `worker_alive`.
- `GET /orders/{id}`: additive detail fields; total_gauss from stored row; invariant chain final == stored total_gauss (only asserted when not recalculating; when recalculating the panel shows the recalculating badge).
- `POST /orders/{id}/resync` (perm `ml_ops.resincronizar`): HTTP fetch before write block, ingestion writes → triggers → worker. Endpoint then polls (≤ 2 s, 100 ms step, short read blocks) for the dirty row to disappear and returns the fresh detail; on timeout returns 202-style body with `metrics_state='recalculating'` (spec R24: explicit, not silent). Concurrent resyncs: per-order `pg_try_advisory_xact_lock(order_id)` around the write block → second request gets 409.
- `GET /order-metrics/health`, `POST /order-metrics/divergence/run` (D9, D10).

### D14 — Frontend architecture (unchanged from rev 1)
Container `pages/VentasML.jsx` + `useVentasMLFilters` (URL state), `useSales`, `useSalesKpis`, `useSaleDetail`; presentational `components/ventasMl/*` (VentasMLLayout, SalesToolbar, FacetChips, KpiStrip+KpiCard, DoubtfulSwitches+Switch role=switch, SalesTable, SaleGroupRow, SaleOrderSubRow, ProductCell+CategoryIcon, StatusBadges, EnvioCell, MoneyCell, AlertIcon, SaleDetailPanel with PanelHeader/ProductoSection/CompradorSection/EnvioSection/PagoSection/NetoWaterfall/IvaPorAlicuota/GaussChain). New: RecalculatingBadge (row + panel) and KPI banner for worker down. Layout: CSS grid `minmax(0,1fr) var(--ventas-panel-width)` when selected; sticky `<aside aria-label="Detalle de venta">`; non-modal (no overlay/aria-modal/trap), Escape clears `orden`; <1280px fixed right sheet without backdrop. Tokens only (`--font-mono`, `--brand-primary`, `--success|--warning|--error`, `--cf-*`), no hex. lucide map + `utils/categoryIcon.js` keyed by productos_erp.categoria (fallback Package). Test migration: DesgloseDrawer 54 + VentasML 57 → ≥ baseline with assertion mapping table per FE PR.

## Data Flow

    writer (sweep / endpoint / script / psql)
        | INSERT/UPDATE/DELETE of read-set columns
        v
    trigger (same txn) --> ml_order_metrics_dirty upsert (version+1) + pg_notify('order_metrics_dirty','')
        | COMMIT (rollback => nothing enqueued, nothing notified)
        v
    pricing-worker (systemd)  LISTEN via DATABASE_URL_DIRECT  | safety poll 5s | startup drain
        | charge expired leases (attempts+1) ; claim batch (SKIP LOCKED, lease, claim_token) -> commit
        | one txn per batch: recompute ; per order FOR UPDATE fence on claim_token ->
        |   owner: upsert ml_order_metrics + ml_venta_deducciones ; DELETE if version unchanged else unclaim
        |   not owner: rollback to savepoint (no stale write) -> commit
        |   batch over batch_timeout: rollback, release claims uncharged, retry each order alone
        | heartbeat THREAD (every ~5 s, own short block): worker heartbeat + renew leases of held claim_tokens
        v
    readers: /sales, /sales/kpis, /orders/{id} -> ml_sales_query.build_scope -> stored metrics
             (dirty => 'recalculating', excluded from KPI, counted)
    worker scheduled jobs: reconcile (10 min: missing/old formula_version -> enqueue)
                           divergence (daily: compute vs stored -> ml_ops_divergence + re-enqueue)
    /order-metrics/health: queue_depth, oldest age, heartbeat, poisoned, last divergence

## Write-path inventory (all captured by triggers — unchanged, plus transportes)
| Input table | Writers (file:line) | Txn boundary |
|---|---|---|
| ml_orders_ops / ml_order_items_ops | ingestion_service.upsert_order :334 (:130,:173,:141); sweep process_batch sweep_service.py:1420; retry_quarantined_orders ingestion_service.py:480 (sweep_service.py:1763, activity_receiver_service.py:331); backfill_service.py:256,266; activity_receiver_service.py:435 | get_background_db block |
| ml_order_item_costos | costeo_service.congelar :229 (:308); scripts/backfill_costo_congelado.py:613 | caller / script |
| ml_payments_ops, ml_payment_charges | upsert_payment :109 (:72,:93,:106) via sync_payments_for_order :650 ← process_batch :1484, deferred rechecks :1040 (commit :1060), backfill_payments_costs_service.py:512; scripts/repair_deferred_refunds.py:168 | block / explicit commit |
| ml_shipments_ops (logistic_type, receiver_address) | upsert_shipment ingestion_service.py:216 (:201) ← sweep_service.py:1521 | process_batch block |
| etiquetas_envio | etiquetas_upload.py:142,206, delete :240/:299; etiquetas_assignments.py:74,103,146,204,242,276,346,379; etiquetas_pistoleado.py:112,130,135, delete :416; etiquetas_manual.py:185,329,520,533,534; etiquetas_shared.py:499; etiquetas_enrichment.py:629; etiqueta_enrichment_service.py:149,419,509; etiqueta_retiro_service.py:180; rma_seguimiento.py:1805,2087; etiquetas_colecta.py:1033; scripts/cron_reprogramar_envios_no_entregados.py:193 | request / script |
| varios_venta_pct | configuracion.py:315 (:336,:338) | request (fan-out) |
| logistica_costo_cordon | config_operaciones.py:673 (:698) | request (fan-out) |
| configuracion lluvia keys | config_operaciones.py:832 | request (fan-out) |
| codigos_postales cordon | codigos_postales.py:159 (:182), :222 (:194,:322,:325) | request (fan-out) |
| transportes.cp | api/endpoints/transportes.py:196 (update; create :147 has no labels) | request (fan-out) |
Not inputs: shipment sender/receiver cost (sweep_service.py:1259-1302), label lat/lng (etiquetas_shared.py:211), logistica name.
Retired after readers switch: `marcar_stale` (7 sites), `refrescar_total_gauss_pendientes` (sweep_service.py:1787 slot), `ml_orders_ops.total_gauss_stale`.

## "Rendimiento de métricas" (DashboardMetricasML) — what NOT to repeat (unchanged)
frontend/src/pages/DashboardMetricasML.jsx → backend/app/api/endpoints/dashboard_ml.py over `MLVentaMetrica`, filled by cron `agregar_metricas_ml_local`. Faults: (1) second formula producer in a cron script; (2) freshness by rolling 30/90-day re-processing windows (stale by design); (3) lying zeros (`or Decimal("0")`, markup 0 without cost); (4) private filter builder `aplicar_filtros_comunes`, 6 Query params re-declared on 7 endpoints, ISO dates without 422; (5) dimensions copied onto metric rows → drift; (6) one endpoint per group-by → 7 requests per filter change. This design: single producer, event capture (now also no cron), NULL+status, shared builder, dimensions joined, one aggregate with dimension parameter.

## File Changes
| File | Action | Description |
|---|---|---|
| backend/app/models/ml_order_metrics.py | Create | MlOrderMetrics, MlOrderMetricsDirty (version/claim/attempts) |
| backend/app/models/worker_job_state.py | Create | generic job state + heartbeat |
| backend/alembic/versions/2026MMDD_ml_order_metrics.py | Create | tables + indexes + ix_ml_orders_ops_seller_date (downgrade) |
| backend/alembic/versions/2026MMDD_ml_order_metrics_triggers_orders.py | Create | enqueue fn + per-order triggers |
| backend/alembic/versions/2026MMDD_ml_order_metrics_triggers_config.py | Create | etiquetas + config + transportes triggers |
| backend/app/services/order_metrics/{compute,store,triggers,queue}.py | Create | producer, writer, PG DDL registry + TRIGGERED_TABLES, claim/release |
| backend/app/workers/{__init__,run,runtime,registry,context}.py | Create | generic worker loop, LISTEN, safety poll, scheduler, heartbeat-thread supervision |
| backend/app/workers/heartbeat.py | Create | HeartbeatThread: worker heartbeat + lease renewal of held claim tokens every ~5 s |
| backend/app/workers/handlers/order_metrics.py | Create | drain, reconcile, divergence handlers |
| backend/app/core/database.py | Modify | `_is_script_context` also matches `/workers/` (NullPool) |
| backend/app/core/config.py | Modify | `DATABASE_URL_DIRECT: Optional[str]`, worker tunables |
| deploy/systemd/pricing-worker.service | Create | Restart=always, RestartSec=5, venv python -m app.workers.run, After=postgresql |
| deploy.sh | Modify | restart pricing-worker after pricing-api (warn-not-fail) |
| docs/RUNBOOKS.md | Modify | install/enable unit, health endpoint, DATABASE_URL_DIRECT |
| backend/tests/conftest.py | Modify | pg_order_metrics_engine / committed-data fixture |
| backend/app/services/ml_ventas_desglose/deducciones.py | Modify | persistir_total_gauss delegates; later remove marcar_stale/refrescar |
| backend/app/services/ml_orders_ingestion/sweep_service.py | Modify | cleanup PR: remove :1787 refrescar slot |
| backend/app/routers/ml_order_metrics.py | Create | health + divergence run endpoints |
| backend/app/services/ml_sales_query/{filters,search,aggregate}.py | Create | shared scope + aggregation |
| backend/app/routers/ml_ventas_ops.py | Modify | builder, additive fields, /sales/kpis, resync |
| backend/app/api/endpoints/configuracion.py | Modify | varios response `recalculando` |
| backend/app/api/endpoints/etiquetas_{upload,assignments}.py | Modify | remove marcar_stale (cleanup PR) |
| frontend/src/pages/VentasML.jsx (+css, test) | Modify | container, layout, search, KPI |
| frontend/src/components/ventasMl/* | Create | presentational + tests (incl. RecalculatingBadge, worker-down banner) |
| frontend/src/hooks/{useVentasMLFilters,useSales,useSalesKpis,useSaleDetail}.js | Create | |
| frontend/src/components/DesgloseDrawer.jsx (+css, test) | Delete (after migration) | |
| frontend/src/utils/categoryIcon.js | Create | lucide map by ERP categoria |
Removed vs rev 1: app/events/order_metrics_hooks.py, app/scripts/{enqueue,drain,check_divergence}_order_metrics.py.

## Interfaces / Contracts
```python
class GaussStatus(str, Enum): OK="ok"; PROVISIONAL="provisional"; UNRESOLVED="unresolved"

@dataclass(frozen=True)
class OrderMetrics:
    order_id: int; neto: Optional[Decimal]; neto_sin_iva: Optional[Decimal]; iva_reconcilia: Optional[bool]
    costo_mercaderia: Optional[Decimal]; total_gauss: Optional[Decimal]; markup_pct: Optional[Decimal]
    gauss_status: GaussStatus; provisional_falta: Optional[str]; unresolved_reason: Optional[str]
    lineas: List[Tuple[str, Optional[Decimal], Optional[str]]]; formula_version: int

def compute_order_metrics(db: Session, order_ids: Sequence[int]) -> Dict[int, OrderMetrics]: ...
def recompute_order_metrics(db: Session, order_ids: Sequence[int]) -> Dict[int, OrderMetrics]: ...  # no commit
@dataclass(frozen=True)
class Claim: order_id: int; version: int; claim_token: UUID; attempts: int
def claim_dirty(db: Session, *, limit: int, lease: timedelta, worker_id: str) -> List[Claim]: ...  # charges expired leases first
def fenced_store(db: Session, claims: Sequence[Claim], metrics: Dict[int, OrderMetrics]) -> FencedResult: ...  # per-order FOR UPDATE on claim_token; upsert + delete-or-unclaim; skips lost claims
def mark_failed(db: Session, claim: Claim, error: str) -> None: ...  # fenced by claim_token
def release_uncharged(db: Session, claims: Sequence[Claim]) -> None: ...  # batch timeout: clear claims, attempts unchanged
def renew_leases(db: Session, *, worker_id: str, tokens: Sequence[UUID]) -> int: ...  # heartbeat thread only
class HeartbeatThread(threading.Thread): ...  # tick(): heartbeat + renew_leases in one short block; last_tick_at
# SQL: order_metrics_enqueue(ids, reason) = input write (bump version, reset attempts); order_metrics_enqueue_system(ids, reason) = ON CONFLICT DO NOTHING
TRIGGERED_TABLES: FrozenSet[str]
NOTIFY_CHANNEL = "order_metrics_dirty"

@dataclass(frozen=True)
class JobResult: processed: int; more_pending: bool; detail: Optional[dict] = None
@dataclass
class WorkerContext: worker_id: str; deadline: datetime; logger: logging.Logger
class JobHandler(Protocol): name: str; channels: Tuple[str, ...]; interval: Optional[timedelta]; run_at_local: Optional[time]
    def run(self, ctx: WorkerContext) -> JobResult: ...

@dataclass(frozen=True)
class SalesFilter:
    date_range: Optional[Tuple[datetime, datetime]]; operation_status: Optional[str]; goods_status: Optional[str]
    q: Optional[str]; include_unknown: bool = False; include_mixed: bool = True
    include_in_dispute: bool = False; include_provisional: bool = True
def build_scope(db: Session, f: SalesFilter, *, apply_switches: bool = True) -> SalesScope: ...
def aggregate_order_metrics(db: Session, scope: SalesScope, dimension: Optional[Dimension] = None) -> List[AggregateRow]: ...
```
Health response: `{queue_depth:int, oldest_dirty_age_s:Optional[float], claimed_count:int, poisoned_count:int, worker_heartbeat_at:Optional[datetime], worker_alive:bool, worker_draining:bool, listener_mode:str, last_divergence:Optional[{run_at, divergent_count, missing_count}], formula_version:int}`.

## Testing Strategy (strict TDD, RED first)
| Layer | What | How |
|---|---|---|
| Unit | compute == existing functions; status mapping; None never 0; JobHandler scheduling math (daily slot, restart no double-run) | SQLite / pure, captured payloads only |
| Integration PG | one test per input table × write kind: committed write ⇒ dirty row + version bump; rolled-back write ⇒ no row, no notify; non-read columns (lat/lng, sender_cost) ⇒ no row | @pytest.mark.postgres, pg_order_metrics_engine |
| Integration PG | NOTIFY delivered only after commit and folded to one per txn; statement-trigger fan-out set-based | second raw connection LISTENs |
| Integration PG | claim SKIP LOCKED (two claimers disjoint); lease expiry reclaims; write during recompute ⇒ version-checked delete leaves row; poisoned after 5 attempts; per-order savepoint isolation | committed-data fixture |
| Integration PG (rev 3) | expired-lease reclaim ×5 ⇒ parked, queue continues; reconcile never un-parks, input write does; heartbeat stays fresh through a drain longer than 30 s; two interleaved workers ⇒ older snapshot committing last never overwrites newer (fence) | committed-data fixture, two real sessions, threading barriers |
| Integration PG (rev 4) | heartbeat thread: a single bulk compute stubbed to take > 30 s keeps `worker_alive` true and `claimed_at` renewed; a slow-but-alive batch running past 120 s charges no attempts; process killed (subprocess SIGKILL) ⇒ lease expires ⇒ attempt charged; heartbeat thread killed ⇒ process exits non-zero; batch over `batch_timeout` ⇒ no attempts charged, orders retried singly, only the slow order alone is charged | subprocess worker, committed-data fixture |
| Integration PG | worker loop end-to-end: write+commit ⇒ metrics row within 1 s; missed notify recovered by safety poll; startup drain; poll_only mode without direct URL | run runtime in thread with short intervals |
| Integration | read-set guard (TRIGGERED_TABLES ⊇ tables read by compute) | before_cursor_execute capture (SQLite ok) |
| Integration | reconcile enqueues missing/old-version; divergence detects injected mismatch, opens ml_ops_divergence, re-enqueues | PG |
| Integration | listing vs KPI parity for every switch combination; recalculating excluded + counted; facet override; `_collapse` parity (incl. Mixta = op OR goods mixed, modo_logistico ignored); search | router tests |
| Integration | detail chain final == stored total_gauss; resync 409 on concurrent, recalculating body on timeout | |
| FE | panel non-modal, URL state, switches role=switch, KPI from API only, recalculating badge, worker-down banner, light/dark smoke | Vitest + RTL; assertion mapping from 111 tests |

## Threat Matrix
N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary in the product code. The new systemd unit is a static deploy artifact running the app's own Python module (no dynamic command construction). Resync calls ML via the existing client; permission-gated, single order, fail-closed.

## Migration / Rollout
Additive migrations with downgrade (drop triggers/function, tables). Consumer before producer: the worker + drain ship BEFORE any trigger (inert on an empty queue), so no deploy leaves an undrained queue growing. One-time ops step (before PR 3 deploy): install `deploy/systemd/pricing-worker.service`, `systemctl enable --now pricing-worker`, set `DATABASE_URL_DIRECT` in backend .env (direct Postgres, not PgBouncer). Triggers before readers; readers switch only after reconcile has populated all orders and divergence = 0 (health endpoint). Rollback: revert readers PR → live-recompute readers return; drop triggers migration → capture stops; stop worker → queue grows visibly, no data loss; legacy columns kept until cleanup.
Spec impact: spec R3 ("committed in the same transaction") and scenarios 1/2/5/8 conflict with the binding user decision; the observable contract becomes "recomputed from committed inputs within ~1 s, and until then explicitly 'recalculating' and excluded from KPI". Spec must be revised to match.

## PR slicing (auto-chain, ~400 authored lines each, each safe alone)
1. BE tables (metrics, dirty w/ version+claim, worker_job_state) + models + seller/date index + compute/recompute (persistir delegates) + tests. Inert.
2. BE worker runtime (generic loop, registry, LISTEN via DATABASE_URL_DIRECT + poll_only fallback, scheduler, heartbeat) + NullPool for /workers/ + systemd unit + deploy.sh + runbook. Registry empty → idles harmlessly.
3. BE queue claim/release + `order_metrics.drain` handler + PG fixture + concurrency tests. Queue still empty (no triggers). Ops installs unit here.
4. BE enqueue function + per-order triggers (orders, items, costos, payments, charges, shipments) + read-set guard + per-table PG tests. Producers start; consumer already live.
5. BE etiquetas + config + transportes statement triggers + varios `recalculando` response.
6. BE reconcile + divergence handlers + health/divergence endpoints. PROD GATE (backfill happens automatically after this deploy).
7. BE readers switch (listing/detail/sort read stored; recalculating state; invariant test).
8. BE cleanup: remove marcar_stale hooks, refrescar + sweep slot, total_gauss_stale usage (drop legacy cols in a later migration).
9. BE ml_sales_query extraction (pure refactor, parity) + search `q`.
10. BE additive listing fields (item_category, city, alert_level, metrics_state).
11. BE doubtful switches in builder + /sales/kpis + aggregation (recalculating excluded, worker_alive) + parity tests.
12. BE additive detail fields.
13. FE layout shell: grid + SaleDetailPanel with existing sections (modal removed, tests migrated).
14. FE listing restyle + search bar + chips + recalculating badge.
15. FE new panel sections.
16. FE KPI strip + switches + worker-down banner.
17. BE+FE resync endpoint (advisory lock, bounded wait) + button.
Chains: 1→2→3→4→5→6→7→8 (metrics); 9→10→11 (query; 11 reads stored metrics, needs 6 populated, ideally 7); 12 independent; FE 13..16 after their BE; 17 after 7.

## Open Questions
Resolved from code (rev 2):
- [x] Mixta = collapsed operation_status OR goods_status 'mixed'; modo_logistico excluded.
- [x] item_category = productos_erp.categoria via ml_order_item_costos.producto_item_id; fallback Package.
- [x] Transportes CP = `transportes.cp`; writer transportes.py:196 (update), :147 create needs no fan-out.
- [x] INLINE_MAX cap — moot (no inline recompute).
- [x] CI Postgres — already present (postgres:16, serial `-m postgres` step); no CI change.
Need production info (for the user):
- [x] Production PostgreSQL major version: 17.11, server version confirmed by the user with `SELECT version()` on 2026-09-22. Satisfies ≥ 10; CI runs 16.
- [x] Direct Postgres URL: the existing `DATABASE_URL_DIRECT` setting (already used by `alembic/env.py`) is the non-PgBouncer connection in production, confirmed by the user 2026-09-22. No new setting needed.
- [ ] `pg_trgm` availability (only if search EXPLAIN demands it).
- [ ] Who installs/enables the new systemd unit on the server (the pricing-api unit itself is not versioned in the repo today).
- [x] Spec revision of R3 (same-txn) to the "≤ ~1 s + explicit recalculating" contract — applied 2026-09-22.

## Key Learnings
- PgBouncer runs in transaction mode (database.py:40-64): LISTEN cannot go through DATABASE_URL; the worker needs a direct connection just for listening, and NOTIFY-as-hint + durable queue + safety poll keeps correctness independent of notify delivery.
- CI already has real Postgres 16 with a marked serial step and per-domain PG fixtures, so PG-only triggers are testable without SQLite twins.
- Version-checked delete after a lock-releasing claim avoids writers blocking on the worker, but alone it does NOT stop an older snapshot from a stale claimant overwriting a newer metrics row; the fence (claim token checked under FOR UPDATE in the same txn as the metrics upsert) does.
- Attempts must also count deaths, not just exceptions: a process-killing order raises nothing, so an expired lease is charged as a failed attempt and such rows are retried alone.
- Reconcile and input writes need different ON CONFLICT semantics; sharing one upsert made reconcile un-park poisoned orders every cycle.
- Heartbeat must be time-based inside long handlers, otherwise a backfill drain reads as a dead worker.
- In-handler heartbeats are not enough: a statement timeout bounds one statement, not a multi-statement batch. Liveness and lease renewal belong to a separate heartbeat thread so they depend only on the process being alive; the batch is bounded separately by wall time, and a batch-level timeout charges nobody (retry singly, charge only an order that fails alone).
- The API already runs in-process background loops under a flock lock (main.py:124-249); the worker deliberately does not join them (pool isolation, deploy independence).

## Pending requirement from ml-ventas-neto-iibb-varios

**What:** When `ventas-ml-rediseno` resumes, its worker's reconcile/backfill MUST recompute EVERY stored Total Gauss (ml_orders_ops.total_gauss and the new ml_order_metrics), because the formula changed in SDD `ml-ventas-neto-iibb-varios`.
**Why:** The user backfilled `ml_orders_ops.total_gauss` manually with the OLD formula. The `ml-ventas-neto-iibb-varios` change deliberately does NOT re-mark stored values stale (its PR4 was dropped, user decision 2026-09-21). The displayed values are computed live, so only the stored column goes stale; today it is used only as a sort key.
**Where:** bump `formula_version` in the redesign so its reconcile job requeues every row calculated under an older version.
**Formula changes being shipped:** SIRTAC added back to neto (informational); débitos/créditos doubled in the IVA split for ALL orders that carry it, independent of SIRTAC; % varios = pct × operation amount WITHOUT IVA (frozen precio_unitario/iva_pct per item), subtracted from neto_sin_iva.

# Tasks: Ventas ML redesign

Delivery: auto-chain, SEQUENTIAL (each PR branches fresh off `origin/main` after the previous one is MERGED — no stacking). Each PR must be safe to merge alone. ~400 authored changed lines per PR as a planning heuristic (flagged where a PR is expected to exceed it). Strict TDD: every task is RED (named failing test) → GREEN → refactor. Fixtures from real captured shapes only.

Skills: `pricing-app-testing-ci`, `pricing-app-backend`, `pricing-app-frontend`, `pricing-app-design`. Resolve `work-unit-commits` and `chained-pr` skills by registry name and follow them for branch/commit/PR mechanics.

Requirement legend: `SM`=ml-order-stored-metrics (R1-R8), `KPI`=ml-sales-kpi-aggregation (R7-R15), `PANEL`=ml-sales-detail-panel (R16-R21), `RESYNC`=ml-order-resync (R22-R24), `SEARCH`=ml-sales-search (R25-R27, R25a), `LISTING`=ml-sales-listing (R28-R31), `BREAKDOWN`=ml-order-breakdown (R32-R34), `PFILT`=ml-sales-product-filters (R35-R43), `NEG`=negative-scenarios.

## PR1 — Stored metrics tables + compute/recompute producer (inert)
Design refs: D1, D2, D7. Satisfies: SM R1, R2.

- [x] PR1.T1 RED: unit tests for `OrderMetrics` dataclass + `GaussStatus` enum — `unresolved` forces `total_gauss=NULL` and dependent fields NULL; any other status with NULL total_gauss is rejected; `markup_pct` is NULL when `costo_mercaderia` is NULL or zero even with status `ok` or `provisional` (never 0% nor a division by zero) (SM R2).
- [x] PR1.T2 GREEN: create `backend/app/models/ml_order_metrics.py` (`MlOrderMetrics` 1:1 `ml_orders_ops`, FK ON DELETE CASCADE, with EVERY design D2 column: `order_id` BIGINT PK FK, `neto`, `neto_sin_iva`, `iva_reconcilia`, `costo_mercaderia`, `total_gauss`, `markup_pct`, `gauss_status` (CHECK IN ok/provisional/unresolved), `provisional_falta`, `unresolved_reason`, `formula_version` SMALLINT NOT NULL, `computed_at` TIMESTAMPTZ NOT NULL; `MlOrderMetricsDirty` with EVERY design D3 column: `order_id` BIGINT PK, `version` BIGINT NOT NULL DEFAULT 1, `reason` VARCHAR(32) NOT NULL, `enqueued_at` TIMESTAMPTZ NOT NULL DEFAULT now(), `claimed_at` TIMESTAMPTZ NULL, `claimed_by` VARCHAR(64) NULL, `claim_token` UUID NULL, `attempts` SMALLINT NOT NULL DEFAULT 0, `last_error` TEXT NULL, `suspect` BOOLEAN NOT NULL DEFAULT false, plus index on `enqueued_at`) and `backend/app/models/worker_job_state.py` (`name` PK, `last_run_at`, `last_success_at`, `state`, `detail` JSON, `heartbeat_at`). The PR1 migration is the ONLY DDL for these three tables; later PRs add functions/triggers, never columns.
- [x] PR1.T3 RED: Alembic migration test (upgrade/downgrade round-trip) for `ml_order_metrics`, `ml_order_metrics_dirty` (asserting every PR1.T2 column incl. `claim_token` UUID and `formula_version`), `worker_job_state`, `ix_ml_order_metrics_status`, `ix_ml_order_metrics_total_gauss` (DESC NULLS LAST), `ix_ml_orders_ops_seller_date`.
- [x] PR1.T4 GREEN: write `backend/alembic/versions/2026MMDD_ml_order_metrics.py` with full downgrade.
- [x] PR1.T5 RED: unit tests — `compute_order_metrics(db, order_ids)` wraps existing `compute_neto_by_order_ids`, `descomponer_neto`, `calcular_total_gauss` and returns identical values to calling those functions directly (no second formula), for `ok`, `provisional`, `unresolved` fixtures (captured payloads).
- [x] PR1.T6 GREEN: implement `backend/app/services/order_metrics/compute.py::compute_order_metrics`.
- [x] PR1.T7 RED: unit test — `recompute_order_metrics(db, order_ids)` upserts `ml_order_metrics` + `ml_venta_deducciones` + legacy `ml_orders_ops.total_gauss*` columns, no commit (caller controls transaction).
- [x] PR1.T8 GREEN: implement `backend/app/services/order_metrics/store.py::recompute_order_metrics`.
- [x] PR1.T9 RED→GREEN: `persistir_total_gauss` (deducciones.py) becomes a thin delegating alias to `recompute_order_metrics`; existing deducciones tests stay green unmodified (regression guard).
- [x] PR1.T10 Run backend suite + `ruff format app/ tests/ alembic/`; confirm no readers changed (inert deploy).

**Review fixes (post-PR1, before merge):**
- `compute_order_metrics` now skips (never raises, never stores) an `order_id` with no `ml_orders_ops` row — the exact tolerance `persistir_total_gauss` had pre-PR1 — instead of risking a `KeyError` upstream and an FK-violating `ml_order_metrics` insert downstream.
- `markup_pct` is normalized to `None` (with a warning log) whenever it would disagree with `costo_mercaderia` being `None`/zero, so the producer can never crash on `OrderMetrics.__post_init__`'s own invariant.
- `test_compute.py`'s provisional/OK tests now assert unconditionally (with a real provisional fixture and a reconciling OK fixture), instead of asserting only inside `if expected_resultado.provisional:`.
- `test_migration_ml_order_metrics.py` cleanup now drops only the tables the test itself created (CASCADE, dependency order), never masks the original assertion error, and `test_is_single_head` asserts single-head + ancestry instead of pinning the head to this exact revision.

## PR2 — Generic worker runtime (idle, empty registry)
Design refs: D4, D6. No spec requirement yet satisfied directly (infra); enables SM R7.

- [x] PR2.T1 RED: unit tests for `JobHandler` Protocol scheduling math — `run_at_local` daily-slot logic, restart does not double-run (`worker_job_state.last_success_at` vs today's slot).
- [x] PR2.T2 GREEN: `backend/app/workers/{__init__,registry,context}.py` (empty registry list, `WorkerContext`, `JobResult`).
- [x] PR2.T3 RED: integration test (`@pytest.mark.postgres`) — worker LISTEN via `DATABASE_URL_DIRECT` bypasses PgBouncer; if unset, runs in `poll_only` mode and logs a WARNING (never silent loss).
- [x] PR2.T4 GREEN: `backend/app/workers/runtime.py` (LISTEN/select loop, debounce 50ms, safety-poll timeout=min(5s, next due job), startup full drain, reconnect+backoff, start and supervise the heartbeat thread). Deviation: safety-poll timeout is the fixed `safety_poll_interval` (default 5s), not `min(5s, next due job)` — the registry is empty in PR2 so there is no due job to shorten it against yet; revisit when PR6 registers `run_at_local` handlers.
- [x] PR2.T4a RED (design D4 step 5 rev 4): `HeartbeatThread` writes `worker_job_state.heartbeat_at` every ~5 s while the main thread is blocked in a stubbed handler for > 30 s; `worker_alive` (computed as `now() - heartbeat_at < 30 s`) stays true throughout. Lease renewal hook is called each tick with the current held-token set (empty in PR2; the real `renew_leases` arrives in PR3). Implemented with scaled-down intervals (0.05s/0.3s instead of 5s/30s) — same mechanism, fast test.
- [x] PR2.T4b RED: heartbeat thread death (stub raises inside `tick`, or no completed tick for 3 × interval) ⇒ main loop logs CRITICAL, stops starting work, and the process exits non-zero. Deviation: covered by a unit test mocking `HeartbeatThread.is_healthy()` and asserting `WorkerRuntime._check_heartbeat_or_die()` raises `SystemExit(70)` with a CRITICAL log — not a real subprocess test. `HeartbeatThread.is_healthy()` itself (death / stalled-tick detection) IS covered against a real thread in `test_heartbeat.py::TestHeartbeatDeathDetection`.
- [x] PR2.T4c GREEN: `backend/app/workers/heartbeat.py::HeartbeatThread` (own short `get_background_db()` block per tick, `SET LOCAL statement_timeout='5s'`, `lock_timeout='2s'`, lock-protected token set and draining snapshot) + supervision in `runtime.py`.
- [x] PR2.T5 GREEN: `backend/app/workers/run.py` (`python -m app.workers.run` entrypoint).
- [x] PR2.T6 RED→GREEN: `backend/app/core/database.py::_is_script_context` also matches the '/workers/' path fragment → NullPool; `backend/app/core/config.py` adds worker tunables (lease, batch size, poll interval, batch timeout, heartbeat interval) — `DATABASE_URL_DIRECT: Optional[str]` already existed pre-PR2 (confirmed at `config.py:16`).
- [x] PR2.T7 GREEN (non-test): `deploy/systemd/pricing-worker.service` (Restart=always, RestartSec=5, venv python, After=postgresql); `deploy.sh` step adds warn-not-fail restart of `pricing-worker` after `pricing-api`; `docs/RUNBOOKS.md` install/enable + health endpoint + `DATABASE_URL_DIRECT` section (new "6) Pricing Worker" runbook).
- [x] PR2.T8 RED: integration test — worker with empty registry runs the loop and idles harmlessly (no crash, heartbeat updates).
- [ ] PR2.T9 OWNER: user — do not install/enable the systemd unit yet (queue is still empty; install happens at PR3 per design Migration/Rollout). Note this explicitly in the PR description.

## PR3 — Queue claim/release + drain handler + PG fixtures (ops installs unit here)
Design refs: D3 (queue table only, no triggers yet), D5. Satisfies: SM R7 (no-cron mechanism scaffolding).

- [x] PR3.T1 RED (`@pytest.mark.postgres`, new `pg_order_metrics_engine` fixture in conftest.py): `claim_dirty` — two concurrent claimers get disjoint order sets (`FOR UPDATE SKIP LOCKED`).
- [x] PR3.T2 RED: lease expiry (default 120s) reclaims rows of a crashed worker.
- [x] PR3.T3 RED: `fenced_store` — per order, `SELECT ... FOR UPDATE` on the row matching `order_id` AND `claim_token`; owner with unchanged `version` ⇒ metrics upserted and dirty row deleted; owner with bumped `version` (test bumps it with a direct SQL UPDATE, no enqueue function needed) ⇒ metrics upserted and dirty row kept with claim columns cleared (no lost update); token no longer present ⇒ nothing written for that order.
- [x] PR3.T4 RED: `mark_failed` — after 5 attempts, order is `poisoned`, excluded from claim, counted by `queue.py::poisoned_count(db)` (the health endpoint in PR6 reuses it); failure isolated per order by its own store transaction, not a savepoint (design D5 rev 6): a batch of 199 succeeds despite 1 bad order, and at most one order's row lock is held at any time.
- [x] PR3.T4a RED: 5 lost races (version-mismatch release; the test bumps `version` with a direct SQL UPDATE during each recompute, simulating an input write) on the same order never increments `attempts` and never parks it — `claim_dirty` still returns it on the 6th pass, no failure recorded, `poisoned_count(db)` unchanged.
- [x] PR3.T4c RED: 5 genuine recompute failures (exception raised inside step 2 for the same order, not a version mismatch) increment `attempts` each time, park the order at `attempts == 5`, and `poisoned_count(db)` reflects exactly that one order; a concurrently failing OR succeeding unrelated order's `attempts`/status is unaffected.
- [x] PR3.T4d RED (design D5 attempts rule): simulate a worker death 5 times on the same order (claim it, never release, advance the lease past expiry, run `claim_dirty` again) ⇒ `attempts` rises by 1 per expired-lease reclaim, `last_error = 'lease_expired'`, the order is parked at `attempts == 5` and counted by `poisoned_count(db)`; rows with `attempts > 0` are claimed alone (batch of one); an unrelated dirty order enqueued alongside is claimed, recomputed and deleted throughout (queue continues).
- [ ] PR3.T4e RED (design D5 rev 4): a recompute statement exceeding `SET LOCAL statement_timeout` while an order is processed ALONE raises and is recorded through `mark_failed` as a normal failed attempt (`last_error='timeout'`); the same timeout during a multi-order batch charges nobody (see PR3.T6d).
- [x] PR3.T4f RED (real Postgres, two sessions with threading barriers; design D5 fence): worker A claims order X at version 1 and computes from the old snapshot; A's lease expires; a direct SQL UPDATE bumps X to version 2 (simulated input write); worker B reclaims X, recomputes the new snapshot and commits; then A attempts its store ⇒ A's claim-token fence finds no owned row, A writes nothing, and `ml_order_metrics` keeps B's newer values. Second case: a write bumps the version while A still owns the claim ⇒ A's upsert commits but the dirty row survives unclaimed (order stays `recalculating`) and the next pass converges to the newest inputs. Deviation: implemented as one same-process two-worker sequential simulation (no real thread barrier), same fence assertions.
- [x] PR3.T5 GREEN: implement `backend/app/services/order_metrics/queue.py` (`claim_dirty` with expired-lease charging and single-row retry claims, `fenced_store`, `mark_failed`, `release_uncharged`, `renew_leases`, `poisoned_count`) satisfying T1-T4f.
- [x] PR3.T6 RED: `order_metrics.drain` handler — claims batch(200) → COMPUTE phase (read-only bulk, no row locks) → STORE phase with one short transaction per order (fence, upsert, delete or unclaim, commit); stops starting new orders after `ctx.deadline`. Deadline reached mid-STORE: already-stored orders stay committed, and only the unstored ones are released uncharged and NOT suspect (design D5 rev 6).
- [x] PR3.T6a RED (design D4 step 5 rev 4, deviation — see below): held-token registration with `ctx.held_tokens` (the same set object the runtime feeds the heartbeat's `token_provider`) verified directly — token present in the set during the STORE call, absent after. NOT covered: the literal "stub a bulk compute at >30s, assert `heartbeat_at` never ages" real-time integration (would need a running `WorkerRuntime` + `HeartbeatThread` + a slow stub wired through the full loop); flagged as remaining work.
- [ ] PR3.T6b RED (isolates lease renewal): with `batch_timeout` set ABOVE the lease in this test (the default 60 s cap is below the 120 s lease and would take the BatchTimeout path instead, covered by PR3.T6d), a slow-but-alive batch whose total duration exceeds the lease (lease and intervals scaled down) completes with ZERO `attempts` charged to any of its orders and no `lease_expired` entries; no other claimer can take its rows meanwhile. NOT DONE this slice (needs the full runtime+heartbeat integration harness) — flagged as remaining work.
- [x] PR3.T6c RED (subprocess worker): SIGKILL the worker mid-batch ⇒ renewals stop, the lease expires, the next `claim_dirty` charges `attempts + 1` with `last_error='lease_expired'` to exactly the killed batch's orders. A REAL `subprocess` + `SIGKILL` (not mocked): a standalone helper script claims via `claim_dirty`, starts a real `HeartbeatThread` renewing the claim, prints `READY`, then blocks; the parent test SIGKILLs it, waits past the lease, and reclaims. Deviation: `claim_dirty`'s own "attempts > 0 rows are claimed ALONE" rule (design D5 Attempts rule) means one post-kill `claim_dirty` call charges all 3 killed orders in its charge phase but returns only 1 in its claim phase (singleton pass) — asserted directly against the DB rows, not solely against the claim-phase return value.
- [ ] PR3.T6d RED (design D5 batch wall-time bound) -- REOPENED: the wall-time bound is NOT enforced during the compute (`_compute_batch` only checks the budget BEFORE starting; once the bulk compute runs, its only bound is the per-statement 30s timeout while the heartbeat keeps renewing the lease). The test that marked this done stubs `_compute_batch`, so it never exercised the real path. a batch exceeding `batch_timeout` ⇒ the compute is abandoned (nothing was stored, no row locks were held), claims released via `release_uncharged` with `attempts` unchanged for all, each order then retried alone; only an order still failing alone is charged (`last_error='timeout'`); orders that succeed once retried alone are recomputed and deleted. Implemented via a stubbed `_compute_batch` (raises `BatchTimeout` only for a multi-order batch), not a real wall-clock stall.
- [ ] PR3.T6e RED (design D5 durable suspect): after a `BatchTimeout` releases a batch with `suspect = true`, RESTART the worker before any singleton retry; the suspect orders are still claimed one at a time (never re-enter a 200-row batch), the slow one parks after 5 lone failures, and the rest are recomputed and deleted — no livelock. NOT DONE this slice (needs a real worker-restart harness) — flagged as remaining work. The `suspect` flag IS durable by construction (a plain committed DB column, no in-process state), and PR3.T6d's test already proves a suspect row survives being claimed by a fresh `claim_dirty()` call.
- [x] PR3.T6f RED (`@pytest.mark.postgres`, design D5 rev 6): while a batch of many orders is in its STORE phase, (a) an input writer upserting the dirty row of an order not yet stored completes without waiting for the rest of the batch, and (b) every heartbeat lease renewal tick succeeds. Real Postgres, two real sessions, threading (a real `HeartbeatThread` + `drain.run()` on a background thread, an injected block on one order's `store_order_metrics` call, a concurrent writer on a DIFFERENT order's dirty row). REAL DEFECT FOUND AND FIXED: `HeartbeatThread._renew_leases` (and `queue.py::renew_leases`) used a blanket `UPDATE ... WHERE claim_token = ANY(...)`, which contended for the row lock `fenced_store`'s `SELECT ... FOR UPDATE` legitimately holds on the SAME row during STORE; with `lock_timeout='2s'` in the same tick, the whole tick — including the `worker_job_state` heartbeat write, same transaction — failed, making a perfectly alive worker report unhealthy. Fixed both call sites to `FOR UPDATE SKIP LOCKED`: a row locked by this process's own in-flight store is simply skipped and renewed next tick, well inside the lease window.
- [x] PR3.T7 GREEN: `backend/app/workers/handlers/order_metrics.py::drain` (held-token registration with the heartbeat thread via `ctx.held_tokens`, `batch_timeout` wall-clock bound, uncharged release + singleton retry) satisfying T6/T6a/T6d; registered in `registry.py` (channels=`("order_metrics_dirty",)`). `WorkerContext` gained `held_tokens`; `WorkerRuntime._run_handler` feeds it `self._held_tokens` (the same set the heartbeat's `token_provider` reads) and toggles `self._draining` around the call; `WorkerRuntime.drain_once` now also runs every channel-driven (schedule-less) handler unconditionally, not just due scheduled ones.
- [x] PR3.T8 RED: end-to-end handler test — a manually inserted dirty row is claimed, recomputed, and deleted by `drain.run()` (committed-data fixture; the full LISTEN/NOTIFY runtime loop is PR2's own regression-tested surface, not re-proven here).
- [x] PR3.T9 GREEN: `drain_once` wired to run `order_metrics.drain` on every pass (channel-driven, no schedule) — confirmed via the T7 registry test and T8's handler-level pass; queue stays empty in prod until PR4 ships the enqueue triggers (no producers yet).
- [ ] PR3.T10 OWNER: user — install and enable the systemd unit now: `sudo cp deploy/systemd/pricing-worker.service /etc/systemd/system/`, `sudo systemctl daemon-reload`, `sudo systemctl enable --now pricing-worker`, set `DATABASE_URL_DIRECT` in backend `.env` (direct Postgres, not PgBouncer), verify `systemctl status pricing-worker` and `GET /api/ml-ops/order-metrics/health` (added in PR6) once available.

### PR3 defects found by review (both fixed in this slice)

- **Heartbeat blocked by its own store.** `HeartbeatThread._renew_leases` (and `queue.py::renew_leases`) renewed with a blanket `UPDATE`, which waited on the very row lock this same process's `fenced_store` legitimately held. With `lock_timeout = '2s'` in the same tick, the WHOLE tick failed -- including the `worker_job_state` liveness write -- so a healthy worker read as dead and, by the PR2 rule, exited(70). Fixed with `FOR UPDATE SKIP LOCKED`: a row locked by our own in-flight store is skipped for one tick and renewed the next, far inside the lease window. Covered by PR3.T6f.
- **Drain livelock on an order with no computable metrics.** When the bulk COMPUTE returned nothing for a claimed order (no `ml_orders_ops` row is the reachable case), `drain` released it uncharged, so it went back to `attempts = 0`, not suspect, and the next `claim_dirty` of the SAME `run()` loop claimed it again at once: never failed, never parked, and the pass spun claim/compute/release against the database until its deadline, on every drain. Fixed by charging it through `mark_failed` so the normal attempts rule parks it. A LOST RACE stays uncharged and must not be confused with this: there the recompute did happen and another write simply won.

### PR3 open debt (declared, not silently skipped)

PR3.T4e, PR3.T6b, PR3.T6d and PR3.T6e are NOT implemented. They cover the statement-timeout path, lease renewal isolated above the batch timeout, and durable `suspect` surviving a worker restart. Each needs its own subprocess or restart harness, and T6d needs the compute itself to become interruptible. They are open, not covered by a lighter equivalent.

## PR4 — Enqueue function + per-order triggers (producers start; consumer already live)
Design refs: D3 read-set scope for per-order tables, D8. Satisfies: SM R1, R3 (per-order path), R7.

- [x] PR4.T1 RED (`@pytest.mark.postgres`): PL/pgSQL `order_metrics_enqueue(ids, reason)` — upserts dirty rows with `version+1` on conflict, resets `attempts` (to 0), `last_error` (to NULL), `suspect` (to false), and leaves `claimed_at`, `claimed_by`, `claim_token` UNCHANGED (design D3 rev 3), fires ONE `pg_notify('order_metrics_dirty','')` per transaction even for 10k-row fan-out (folded notify).
- [x] PR4.T1a RED (`@pytest.mark.postgres`): `order_metrics_enqueue` called against an existing row with `attempts = 5, last_error IS NOT NULL` (a parked order) resets `attempts = 0` and `last_error = NULL` on that row — a new input write is a new chance, un-parking a poisoned order at the enqueue/trigger layer, not just in `queue.py`.
- [x] PR4.T1c RED (`@pytest.mark.postgres`, moved from PR3 because it needs the PR4 enqueue function): a parked order (attempts == 5, excluded from `claim_dirty`) that then receives `order_metrics_enqueue` (input write) is un-parked (`attempts` 0, `last_error` NULL) and is claimed and recomputed on the next drain, same as any other dirty order.
- [x] PR4.T1d RED (`@pytest.mark.postgres`): a `suspect = true` row that receives `order_metrics_enqueue` (input write, through the real PL/pgSQL function) ends with `suspect = false` and goes back to normal batch claiming; the system enqueue (`order_metrics_enqueue_system`) leaves `suspect` unchanged.
- [x] PR4.T1b RED (`@pytest.mark.postgres`): `order_metrics_enqueue_system(ids, reason)` inserts missing rows and fires the notify, but on an existing row (pending, claimed, or parked with `attempts = 5`) changes nothing — `version`, `attempts`, `last_error`, claim columns all identical before and after.
- [x] PR4.T2 GREEN: implement both enqueue functions' DDL in `backend/app/services/order_metrics/triggers.py`.
- [x] PR4.T3 RED: one test per table×write-kind for `ml_orders_ops` (INSERT; UPDATE OF `shipping_id`,`date_created`,`has_no_shipping_tag`,`pack_id`; DELETE; `shipping_id` change also enqueues OLD+NEW shipping siblings) — committed write ⇒ dirty row+version bump; rolled-back write ⇒ no row, no notify.
- [x] PR4.T4 RED: same pattern for `ml_order_items_ops`, `ml_order_item_costos`.
- [x] PR4.T5 RED: same pattern for `ml_payments_ops` (OLD/NEW `order_id`; UPDATE OF `status`,`net_received_amount`,`transaction_amount_refunded`,`shipping_amount`,`order_id`) and `ml_payment_charges` (payment_id→order_id).
- [x] PR4.T6 RED: same pattern for `ml_shipments_ops` (UPDATE OF `logistic_type`,`receiver_address` only; confirm sender/receiver cost and `raw_costs` columns do NOT fire — negative scenario).
- [x] PR4.T6a RED (`@pytest.mark.postgres`, design D3 rev 5): for every row-trigger table, an idempotent re-upsert that sets a read column to the SAME value (e.g. the sweep rewriting `status`, `net_received_amount` unchanged) enqueues NOTHING and fires no notify; changing the value does enqueue. A parked order stays parked across repeated no-op sweep writes.
- [x] PR4.T7 GREEN: row-level triggers for all six tables in `triggers.py`, applied via explicit `create_triggers`/`drop_triggers` calls from the Alembic migration and from the `pg_order_metrics_triggers_engine` test fixture — never an `after_create` listener (deviation: a global listener on the shared `ml_order_metrics_dirty` table broke pre-existing PR1/PR3 fixtures that create it without the six sibling input tables this DDL references; see post-review fix pass for `ml_shipments_ops` INSERT/DELETE coverage, `ml_shipments_ops`/`ml_payment_charges` sibling/payment-id fanout, and the migration's frozen DDL copy — fixed 2026-09-23).
- [x] PR4.T8 RED: write `backend/alembic/versions/2026MMDD_ml_order_metrics_triggers_orders.py` round-trip test (upgrade creates triggers, downgrade drops them + function).
- [x] PR4.T9 GREEN: implement the migration.
- [x] PR4.T10 RED: read-set guard test — `before_cursor_execute` instrumentation of `compute_order_metrics` fails if any table it reads is missing from `TRIGGERED_TABLES` (SQLite-safe, runs in normal CI).
- [x] PR4.T11 GREEN: define `TRIGGERED_TABLES: FrozenSet[str]` and wire the guard.
- [x] PR4.T12 RED: NOTIFY-only-on-commit test — second raw connection LISTENs, confirms zero notifications on rollback, exactly one on commit regardless of row count.

## PR5 — Etiquetas + config + transportes statement triggers; varios fan-out response
Design refs: D3 (statement-level scope), D11. Satisfies: SM R3 (config fan-out path), R3 scenario 5.

- [x] PR5.T1 RED (`@pytest.mark.postgres`): `etiquetas_envio` row triggers — INSERT, DELETE, UPDATE OF `shipping_id`,`logistica_id`,`costo_override`,`fecha_envio`,`es_turbo`,`es_lluvia`,`transporte_id` enqueue; lat/lng-only writes do NOT (negative scenario, previously-missed writers listed in design D "Why triggers" section: toggle turbo, lluvia, lluvia masivo, pistoleado, manual edit, enrichment, reprogram, colecta/pistoleado delete).
- [x] PR5.T1a RED (`@pytest.mark.postgres`, design D3 rev 5): statement-level triggers enqueue only the rows whose read columns changed (OLD TABLE vs NEW TABLE, IS DISTINCT FROM); a bulk UPDATE that rewrites identical values enqueues nothing.
- [x] PR5.T2 GREEN: `etiquetas_envio` triggers in `triggers_config.py` (new module, alongside the five config tables — PR4's `triggers.py`/its migration stay frozen per the immutability contract).
- [x] PR5.T3 RED: statement-level trigger with transition tables for `varios_venta_pct` — orders with `date_created` in `OLD∪NEW [fecha_desde, fecha_hasta]` enqueued via ONE set-based insert (not N).
- [x] PR5.T4 RED: same pattern for `logistica_costo_cordon` (self_service orders whose label has that logistica_id), `codigos_postales` (actual table `cp_cordones`) cordon, `configuracion` (the key filter `clave IN ('lluvia_offset_tipo','lluvia_offset_valor')` lives INSIDE the trigger function over the transition tables, because a statement-level WHEN cannot read row values), `transportes` AFTER UPDATE with NO column list (Postgres rejects transition tables on a trigger with a column list), with the function comparing OLD TABLE and NEW TABLE and enqueuing only rows whose `cp` IS DISTINCT FROM its old value (orders whose label has that `transporte_id`; `transportes` INSERT needs no fan-out — no labels reference a brand-new row yet).
- [x] PR5.T5 GREEN: all five config tables covered by `REFERENCING OLD TABLE / NEW TABLE` triggers, none with a column list (`UPDATE OF`) and none with a WHEN clause; column and key filtering happens inside each trigger function (Postgres restrictions, design D3 rev 7). Deviation (discovered as a genuine RED — real `psycopg2.errors.FeatureNotSupported`, not assumed): Postgres additionally forbids transition tables on a trigger declared for MORE THAN ONE event ("transition tables cannot be specified for triggers with more than one event"), so each of the four multi-event tables (`ml_venta_varios_pct`, `logistica_costo_cordon`, `cp_cordones`, `configuracion`) ships THREE triggers sharing one function (INSERT with `NEW TABLE` only, UPDATE with both, DELETE with `OLD TABLE` only) instead of one combined `AFTER INSERT OR UPDATE OR DELETE` trigger; `transportes` (UPDATE-only) needed no split. The migration test runs against real Postgres so an invalid trigger definition fails in CI.
- [x] PR5.T6 GREEN: `backend/alembic/versions/20260923_ml_order_metrics_triggers_config.py` (round-trip tested, frozen copy of `triggers_config.py`).
- [x] PR5.T7 RED: `configuracion.py::crear_varios_venta_pct` — response includes `recalculando: N` (count of dirty rows produced by the statement's affected-range query), no `BackgroundTask`.
- [x] PR5.T8 GREEN: implement the response field. Implemented independently of whether the Postgres trigger actually fires (a plain `ml_orders_ops` count from `min(new fecha_desde, every closed version's OLD fecha_desde)` forward — every closed version's window is always a SUPERSET of its own narrowed replacement, so the union collapses to that single lower bound), since the endpoint must report a correct count on SQLite too.
- [x] PR5.T9 RED→GREEN: extended `TRIGGERED_TABLES` (`triggers.py`) with the six PR5 tables using their REAL DB table names (`ml_venta_varios_pct` for the `VariosVentaPct` model, `cp_cordones` for `CodigoPostalCordon` — both previously mismatched in the exception set, a latent guard gap since PR4); `read_set_guard.KNOWN_INPUT_TABLES` now equals `TRIGGERED_TABLES` (no "not yet triggered" exceptions left).

## PR6 — Reconcile + divergence handlers, health/divergence endpoints (PROD GATE)
Design refs: D9, D10. Satisfies: SM R4, R8; enables Success Criterion "divergence = 0".

- [x] PR6.T1 RED: `order_metrics.reconcile` handler (every 10 min, batches of 5000, set-based `INSERT...SELECT` into dirty, `reason='reconcile'`) enqueues orders with no metrics row OR `formula_version < CURRENT_FORMULA_VERSION` (SM R4 backfill-via-reconcile, R8 formula bump).
- [x] PR6.T1a RED (design D3, D10; spec scenario 13): a parked order with no metrics row survives three consecutive reconcile runs still parked (`attempts == 5`, `last_error` intact, `poisoned_count` constant); a subsequent real input write (trigger path) un-parks it and the next drain recomputes it.
- [x] PR6.T2 GREEN: implement reconcile via `order_metrics_enqueue_system` in `backend/app/workers/handlers/order_metrics.py`; register with `interval=timedelta(minutes=10)`.
- [x] PR6.T3 RED: `order_metrics.divergence` handler (daily 04:00 AR, batches of 500) compares every stored field + status + `formula_version` vs `compute_order_metrics`, skips currently-dirty orders, writes summary to `worker_job_state.detail` JSON, opens `ml_ops_divergence` records (`kind='stored_metrics_mismatch'`, reusing `ml_orders_ops.py:463` model) for the first N ids, re-enqueues divergent orders.
- [x] PR6.T4 GREEN: implement; register with `run_at_local=time(4,0)` (America/Argentina/Buenos_Aires).
- [x] PR6.T5 RED: injected-mismatch integration test — divergence detects it, opens the `ml_ops_divergence` row, re-enqueues.
- [x] PR6.T6 RED: `GET /api/ml-ops/order-metrics/health` (perm `ml_ops.ver`) — response shape `{queue_depth, oldest_dirty_age_s, claimed_count, missing_metrics_count, poisoned_count, worker_heartbeat_at, worker_alive (heartbeat<30s), worker_draining, listener_mode, last_divergence, formula_version}`.
- [x] PR6.T7 GREEN: `backend/app/routers/ml_order_metrics.py::health`.
- [x] PR6.T8 RED: `POST /api/ml-ops/order-metrics/divergence/run` (perm `ml_ops.admin`-level) sets `worker_job_state.state='requested'`, `pg_notify('worker_jobs', name)`; worker picks it up on next wake. Deviation: implemented as `ml_ops.gestionar` (this router family's existing write-level permission, distinct from `ml_ops.ver`) — no literal `ml_ops.admin` permission code exists in this codebase.
- [x] PR6.T9 GREEN: implement the on-demand trigger endpoint and worker-side channel listener for `worker_jobs`.
- [x] PR6.T10 RED: `CURRENT_FORMULA_VERSION` bump test — per design's "Pending requirement from ml-ventas-neto-iibb-varios", the version bump must cause reconcile to requeue every row computed under the old formula (SM R8, scenario 14). Set the initial `formula_version` constant so this deploy's first value is ALREADY the bump (i.e., every pre-existing `ml_orders_ops.total_gauss` was populated under the OLD formula and has no `ml_order_metrics` row yet — reconcile's "no metrics row" branch covers full backfill AND the formula bump in one pass). `CURRENT_FORMULA_VERSION=2` already ships this from PR1; covered here by `test_enqueues_order_with_stale_formula_version`/`test_does_not_enqueue_order_with_current_formula_version`.
- [ ] PR6.T11 Run backend suite; deploy. Health endpoint live; queue starts draining automatically (still zero producers besides none yet — PR4/PR5 already deployed, so this is where real backfill volume starts). Backend suite run (see apply report); DEPLOY is explicitly out of scope for this apply pass (owner action) — left open pending deploy.
- [x] PR6.T11a RED: gate accounting — a parked order (attempts >= 5, no metrics row) is NOT counted in `missing_count`, IS counted in `poisoned_count`, and the health response lists its order_id and `last_error`; with only parked orders left, the gate figures read missing_count=0, divergent_count=0, poisoned_count=N.
- [ ] PR6.T12 OWNER: user (PROD GATE) — after deploy stabilizes, poll `GET /api/ml-ops/order-metrics/health` until `queue_depth=0`, `oldest_dirty_age_s` low, and trigger `POST /order-metrics/divergence/run`; confirm `missing_metrics_count=0` (the TOP-LEVEL field: orders with no metrics row at all, parked ones excluded -- NOT `last_divergence.missing_count`, which only covers orders that already have a row and therefore reads 0 on an un-backfilled database) and `last_divergence.divergent_count=0` on a run, re-check after a monitoring window, and REVIEW the parked list (`poisoned_count` with order_ids and `last_error` from the health endpoint), explicitly accepting it (design D10 gate) before authorizing PR7. **`last_divergence.divergent_count=0` only means anything when `last_divergence.complete=true`.** A single run is bounded by the handler's own deadline and only ever inspects a slice of the table; the pass resumes from a persisted cursor and needs several runs (daily wake, or repeated `POST /divergence/run`) to traverse everything once. If `complete` is `false` or missing, the run proved nothing — trigger it again and re-check.

## PR7 — Readers switch to stored values (recalculating state; invariant test)
Design refs: D9 metrics_state, D13 (route /orders/{id} invariant). Satisfies: SM R5, R6, R9(scenario), BREAKDOWN R33.
Depends on: PR6.T12 gate passing (user confirmation required before merge).

- [x] PR7.T1 RED: `GET /orders/{id}` — `total_gauss`, `neto`, `markup` sourced from `ml_order_metrics`, NOT live `calcular_total_gauss`; chain final total equals stored `total_gauss` exactly when `metrics_state != 'recalculating'` (invariant test, BREAKDOWN R33 / SM R6).
- [x] PR7.T2 GREEN: switch `breakdown_service.py` reader path to stored values; keep chain-line rendering from `ml_venta_deducciones`. Implemented as a new `app/services/order_metrics/read.py` (`read_stored_metrics`) consumed from the router, rather than a change inside `breakdown_service.py` itself — `iva_decomposicion`/`breakdown` (product/buyer/shipment) stay live, unaffected (out of SM R5/R6's Total-Gauss-only scope).
- [x] PR7.T3 RED: when order is dirty (`recalculating`), detail response signals it explicitly and does NOT assert/claim the invariant (SM R6 second half).
- [x] PR7.T3a RED: a parked order (dirty row with attempts >= 5) has `metrics_state='failed'`, never `'recalculating'`. KPI `failed_count`/`recalculating_count` wiring is PR11 scope; PR7 ships the correct per-order `metrics_state` value the KPI aggregator will read.
- [x] PR7.T4 GREEN: `metrics_state` derivation — `'failed'` if the dirty row is parked (attempts >= 5; wins), else `'recalculating'` if a dirty row exists, else stored `gauss_status`, else `'pending'`. Implemented as `read.metrics_state_for_orders` (bulk, 2 queries).
- [x] PR7.T5 RED: listing/sort reads switch to stored `total_gauss` for the existing sort-by-total-gauss behavior (no live recompute, no per-row query loop). Scope: the SORT KEY only (ORDER BY), joined against `ml_order_metrics` instead of the legacy `MlOrdersOps.total_gauss` mirror; per-row listing values stay live in PR7 (PR10.T7 switches those).
- [x] PR7.T6 GREEN: update `ml_ventas_ops.py` listing query (one conditional `outerjoin(MlOrderMetrics, ...)`, applied only when `sort=total_gauss`).
- [x] PR7.T7 Regression: existing listing/detail tests updated to stored-value fixtures (assertion mapping noted in PR description, per design D14/testing strategy).

## PR8 — Cleanup: retire live-recompute hooks
Design refs: Migration/Rollout "legacy columns kept until cleanup". Satisfies: keeps SM R3/R5 clean (no dual writers).

- [x] PR8.T1 RED→GREEN: remove `marcar_stale` calls (7 sites: `etiquetas_upload.py:142,206`; `etiquetas_assignments.py:78,107,165,204,242`) — trigger-based capture supersedes them; confirm existing tests for those call sites still pass without the call (or are updated). Rewrote `test_etiquetas_assignments_total_gauss_invalidation.py`'s 9 tests from asserting the retired `total_gauss_stale` flag to asserting the trigger's write PRECONDITION per site (the exact `etiquetas_envio` column/row-insert each endpoint performs); the actual enqueue is proven in `test_triggers_config_postgres.py`, out of SQLite's reach. Every rewritten assertion verified RED via mutation (site write disabled → matching test failed) before being confirmed GREEN again. Also fixed two dead `if`-blocks (`etiquetas_upload.py`, in `upload_etiquetas` and `registrar_manual`) left syntactically broken by the call removal (empty `if` body after deleting the only statement inside it) — the `if` wrapper itself was removed since the guarded variable is used unconditionally later in both functions.
- [x] PR8.T2 RED→GREEN: remove `refrescar_total_gauss_pendientes` slot (`sweep_service.py:1787`) and `ml_orders_ops.total_gauss_stale` usages — confirmed already done (no call site remains in `sweep_service.py`).
- [x] PR8.T3 Confirmed `ml_orders_ops.total_gauss*` legacy columns (`total_gauss`, `total_gauss_at`, `total_gauss_stale`, `total_gauss_provisional`) are still WRITTEN, exclusively, by `store_order_metrics` (`app/services/order_metrics/store.py:96-99`, called from `recompute_order_metrics`). The only remaining READS of these columns outside `store.py` are inside `deducciones.py`'s own `marcar_stale`/`refrescar_total_gauss_pendientes` (still exercised by `tests/services/ml_ventas_desglose/test_deducciones.py`, so left in place per this PR's scope — no production call site reaches them any more after T1/T2). Every consumer-facing read (`app/routers/ml_ventas_ops.py`) explicitly reads `MlOrderMetrics`/stored-metrics rows instead, with inline comments pinning "never `MlOrdersOps.total_gauss`" at lines 547, 661, 1043, 1111. A later migration drops the legacy columns; explicitly out of this change's scope.

## PR8b — Index on ml_order_item_costos.producto_item_id (own PR, before the joins)
Design refs: D12a. Satisfies: PFILT R43.
Migration only, no readers: it must be merged and DEPLOYED before PR9 adds any join that crosses this column (spec R43 requires a separate, earlier PR).

- [ ] PR8b.T1 RED: Alembic migration round-trip test (upgrade/downgrade) for a new index `ix_ml_order_item_costos_producto_item_id` on `ml_order_item_costos.producto_item_id` (PFILT R43) — asserted absent today (no existing index on that column, verified: only `id`, `order_id`, `item_id` are indexed).
- [ ] PR8b.T2 GREEN: write and apply `backend/alembic/versions/20260922_ix_producto_item_id.py`, index-only, single head, full downgrade. Merge and deploy this migration before PR9 ships any join against the column.

## PR9 — Shared query layer extraction (pure refactor + search `q` + product-level filters)
Design refs: D12, D12a. Satisfies: KPI R7, R15; SEARCH R25, R25a, R26, R27; PFILT R35-R43.

- [x] PR9.T1 RED: `build_scope(db, SalesFilter)` — order-level base query and group-level CTE reproduce the EXACT SAME rows/statuses as the current inline logic (`ml_ventas_ops.py:637-699` status exprs, `:566` group_key, `:702` `_collapse`), parity test against current behavior before/after extraction.
- [x] PR9.T2 GREEN: `backend/app/services/ml_sales_query/filters.py` (`SalesFilter` dataclass, `build_scope`); `ml_ventas_ops.py` delegates to it.
- [x] PR9.T3 RED: `q` search — digits → `order_id`, `pack_id`; `^MLA\d+$` → `item_id`; else ≥3 chars ILIKE on `buyer_nickname`, `seller_sku`, `title`; always bounded by seller+date (SEARCH R25).
- [x] PR9.T4 GREEN: `backend/app/services/ml_sales_query/search.py`; wire `q` param into the listing router.
- [x] PR9.T5 RED: search combines as intersection with active facets/toggles, not replacement (SEARCH R26); empty/no-match search returns explicit empty result, not an error (SEARCH R27).
- [x] PR9.T6 GREEN: confirm via router-level test.
- [ ] PR9.T7 Confirm the extraction is dimension-pluggable per D12's `Dimension(name, join, key_expr)` contract (ships `NONE` + `DAY`) so KPI R15 (reusable by future metric consumers) holds — stub the contract even though PR9 ships no new dimension consumer yet. — NOT shipped in PR9a: the `Dimension` stub had no consumer, so it was removed on review (code minimalism). It lands with `aggregate.py` in PR11, which is its first real user.

**Product-level filters (design D12a, spec PFILT R35-R43, user binding decision 2026-09-22) — land the index BEFORE the joins below:**

- [x] PR9.T10 RED: `SalesFilter` gains `marcas`, `subcategorias`, `pms` (PFILT R35); `build_scope` joins via `ml_order_item_costos.producto_item_id` to `productos_erp` for marcas/subcategorias/pms (reusing the exact pair-resolution `productos_listing.py::listar_productos`'s `pms` branch uses, no second implementation) (PFILT R36).
- [x] PR9.T10a RED: a request carrying a publication-status or official-store filter returns EXACTLY the same rows and KPI figures as the same request without it (comparison test, not just a 200): unknown params are dropped by FastAPI anyway, so only this comparison proves nothing is filtered by today's catalog state (PFILT R36a, R37).
- [x] PR9.T11 GREEN: implement the joins in `filters.py` (guarded by the PR8b index already being live).
- [x] PR9.T12 RED: pack/group ANY-item-matches semantics for every product-level filter (PFILT R38) — a pack with items from two different brands matches a single-brand filter; a filter matching none of a sale's items excludes that sale/pack (both listing and KPI, parity with KPI R14).
- [x] PR9.T13 RED: an order-item with no `ml_order_item_costos` row (LEFT JOIN, `producto_item_id IS NULL`) never matches a product-level filter on its own (PFILT R39 direct case) AND does not cause its sale/pack to be silently dropped from an UNRELATED filter's results when a sibling item in the same pack matches (PFILT R39 pack case).
- [x] PR9.T15a RED: facet CONJUNCTION (PFILT R38) — with `marcas` and `subcategorias` both active, a pack whose items match one facet EACH is NOT returned; a pack with one item matching BOTH is returned whole. Implemented as a single EXISTS carrying every active condition, never one EXISTS per facet.
- [x] PR9.T14 GREEN: implement T12/T13/T15a via a SINGLE correlated `EXISTS` over the group's member order-items carrying EVERY active facet condition (AND-ed inside the EXISTS, never one EXISTS per facet), matching the existing promo group semantics for returning the whole group.
- [x] PR9.T15 RED: confirm NONE of stock, con_precio, web_transferencia, Tienda Nube, colores, con/sin MLA presence, nuevos_ultimos_7_dias, auditoría are exposed as sales-screen filter params (PFILT R40, negative/absence test on the router's accepted query params).
- [ ] PR9.T16 EXPLAIN capture (review artifact, not a test): `EXPLAIN ANALYZE` for `GET /sales` (LIMIT-bounded, ≤200 rows) and `GET /sales/kpis` (whole filtered set, no LIMIT) with a representative combination (brand + subcategoría + date range), attached to the PR description, confirming `ix_ml_order_item_costos_producto_item_id` is used (Index/Bitmap Index Scan, not Seq Scan) for both shapes. NOT DONE this slice — optional per orchestrator scope, no local Postgres with representative data available in this worktree.
- [x] PR9.T16a RED: facet value contract (design D12a) — `marcas` are brand NAMES matched case-insensitively; `subcategorias` and `pms` are integer ids. A non-numeric id or an empty CSV entry fails with HTTP 422 (spec scenario 12); duplicates are de-duplicated; an id or name that matches no product yields an empty result, never an error and never "no filter". The listing and the KPI validate identically.
- [x] PR9.T16b RED: `pms` resolution — a PM with assigned marca+categoría pairs filters by exactly those pairs; a PM with NO assigned pairs returns an EMPTY result (never every sale), asserted against the pair table.
- [x] PR9.T16c RED: with NO product filter active, an order whose only item has no `producto_item_id` is still returned by the listing and still counted by the KPI (PFILT R39 — an unresolved item must not drop the sale from unrelated results).
- [x] PR9.T16d RED: a pack matched through ONE item's brand returns the WHOLE group, and its KPI amounts are the group's, not that item's — pinned so nobody reads the KPI total as brand-specific revenue (PFILT R38).
- [x] PR9.T17 GREEN: wire `marcas`, `subcategorias`, `pms` query params into the `GET /sales` and `GET /sales/kpis` routers (CSV parsing mirroring `productos_listing.py`'s equivalent params). `GET /sales/kpis` does not exist yet (ships PR11) — satisfied at the shared `build_scope` level (same builder, same facet application) per PR9a precedent.
- [x] PR9.T18 Document in the PR description: no promo/PxQ param is added (PFILT R42, deferred — historical-state gap out of scope); any future markup/rebate/oferta filter on this screen MUST read `ml_order_item_costos` frozen fields only, never `ProductoPricing` (PFILT R41) — noted as a constraint for a later PR, since none ships in PR9.

## PR10 — Additive listing fields
Design refs: D13 route /sales. Satisfies: LISTING R28, R29, R31.

- [ ] PR10.T1 RED: route /sales response adds optional `item_category` (via `ml_order_item_costos.producto_item_id` → `productos_erp.categoria`; NULL when no frozen cost) without changing/removing existing fields (LISTING R28).
- [ ] PR10.T2 GREEN: implement the join; add `utils/categoryIcon.js` fallback mapping is FE (PR14), backend only returns the raw category string here.
- [ ] PR10.T3 RED: `city`, `province` (from `MlShipmentOps.receiver_address`), `shipping_substatus`, `coupon_amount` additive fields — captured-fixture based, null-safe on missing/varying JSONB shape.
- [ ] PR10.T4 GREEN: implement.
- [ ] PR10.T5 RED: server-derived unified `alert_level` (`ok`, `warning`, `error`) per D13 rule (error = unresolved/neto null; warning = provisional/recalculating/iva-not-reconciling/op-or-goods-unknown; ok) — replaces ad-hoc per-field FE flags (LISTING R29).
- [ ] PR10.T6 GREEN: implement `alert_level` derivation server-side.
- [ ] PR10.T7 RED: listing `neto`, `total_gauss`, `markup` values equal `ml_order_metrics` stored fields, not a live recompute (LISTING R31 — regression guard alongside PR7).
- [ ] PR10.T8 RED: `metrics_state` field present per row (`ok`, `provisional`, `unresolved`, `recalculating`, `failed`, `pending`).

## PR11 — Doubtful switches + route /sales/kpis + aggregation
Design refs: D12 aggregate.py, D13 route /sales/kpis, D9 KPI exclusion. Satisfies: KPI R8-R14; SM R3 scenario 11 (worker_alive surfacing).
Depends on: PR6 (populated metrics), ideally PR7 (stored readers) merged first.

- [ ] PR11.T1 RED: `SalesFilter` gains `include_unknown`, `include_mixed`, `include_in_dispute`, `include_provisional` (defaults per R11: unknown OFF, in_dispute OFF, mixed ON, provisional ON) — `build_scope` applies each as an exclusion when OFF (KPI R9, R10, R11).
- [ ] PR11.T2 GREEN: extend `filters.py`.
- [ ] PR11.T3 RED: Mixta resolution — collapsed `operation_status='mixed' OR goods_status='mixed'`; `modo_logistico='mixed'` explicitly does NOT count (parity test vs `_collapse`, per design D12 resolution).
- [ ] PR11.T4 RED: `aggregate_order_metrics` — `groups_count`, `orders_count`, `gross_billed` (ARS; other currencies counted separately), `neto_sum`+`unknown_count`, `total_gauss_sum`+ok/provisional/unresolved counts, `markup_weighted_pct = SUM(tg)/SUM(costo)*100` (never average of %), `recalculating_count`, excluding recalculating orders from all sums (KPI R8, SM R3).
- [ ] PR11.T5 GREEN: `backend/app/services/ml_sales_query/aggregate.py`.
- [ ] PR11.T6 RED: `GET /sales/kpis` — per-toggle excluded counts (KPI R13); `recalculating_count`, `pending_count` (orders with no metrics row: excluded from every sum, counted, never summed as NULL — SM R2, R3) and `worker_alive` fields (derived from worker health).
- [ ] PR11.T7 GREEN: `ml_ventas_ops.py::sales_kpis` endpoint.
- [ ] PR11.T8 RED: parity test — for every switch combination (16 combos) + search + facets, route /sales/kpis aggregate equals summing exactly the rows route /sales would return for that same combination, excluding recalculating and pending rows, and listed rows = summed rows + `recalculating_count` + `pending_count` (KPI R14, R7). Include a case with a non-empty queue.
- [ ] PR11.T9 RED: toggle state round-trips through URL query params (KPI R12) — backend param parsing test; full FE round-trip covered in PR16.

## PR12 — Additive detail (breakdown) fields
Design refs: D13 route /orders/{id}. Satisfies: BREAKDOWN R32, R34.
Independent of PR9-PR11 (per design dependency graph); may run in parallel chain position but ships sequentially per auto-chain constraint.

- [x] PR12.T1 RED: route /orders/{id} response adds buyer real name (if present in `raw_order.buyer`), payment method, installments, shipment substatus — additive, existing `lines`, `item_lines`, `iva_decomposicion`, `cadena_total_gauss` unchanged (BREAKDOWN R32).
- [x] PR12.T2 GREEN: implement in `breakdown_service.py` / router, captured-fixture based.
- [x] PR12.T3 RED: IVA non-reconcile display includes specific `razones` sourced from existing persisted data (BREAKDOWN R34, design D5).
- [x] PR12.T4 GREEN: implement.

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
- [ ] PR16.T11 Light+dark visual pass against `docs/design/ventas-ml/{listado,detalle}.{html,jpg}` refs (pricing-app-design skill). The mockups are a VISUAL reference only (layout, hierarchy, icons, typography); every number and money rule comes from the specs (e.g. Neto includes SIRTAC and shows the "MP $X · SIRTAC $Y" sub-line, per openspec/specs/ml-ventas-desglose-ui).

## PR17 — Resync endpoint + button
Design refs: D13 route /orders/{id}/resync. Satisfies: RESYNC R22, R23, R24.
Depends on: PR7 (stored readers) — resync must trigger the same recompute pipeline.

- [ ] PR17.T1 RED: `POST /orders/{id}/resync` (perm `ml_ops.resincronizar`) — HTTP fetch before write block, ingestion writes commit → triggers fire → order enqueued (RESYNC R22, R23; SM R3 scenario 8).
- [ ] PR17.T2 GREEN: implement, reusing the existing single-order ingestion fetch path (confirm reusability per design open dependency; if not reusable, flag as a blocking discovery before continuing this PR).
- [ ] PR17.T3 RED: endpoint polls (≤2s, 100ms step, short read blocks) for the dirty row to disappear; on success returns fresh detail; on timeout returns a body with `metrics_state='recalculating'` (explicit, not silent) (RESYNC R24, SM R3 scenario 8).
- [ ] PR17.T4 GREEN: implement polling + response shapes.
- [ ] PR17.T1a RED (`@pytest.mark.postgres`): a resync whose re-fetched data is IDENTICAL to what is stored (capture triggers enqueue nothing) still enqueues the order through `order_metrics_enqueue_system` and the order is recomputed (RESYNC R23).
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

**Delivery order (REVISED 2026-09-22, user decision: move forward everything that does not need stored metrics).** Still sequential: one PR open at a time, each off `origin/main` after the previous is merged. Order: **PR1** (tables + producer, inert) → **PR9** (shared query layer + search; needs only PR1) → **PR12** (additive detail fields) → **PR13** (panel layout shell; renders today's live values) → **PR15** (new panel sections, live values) → **PR10** (additive listing fields: product, category, city, substatus, coupon) → **PR14** (listing restyle + search bar + chips) → **PR2** → **PR3** → **PR4** → **PR5** → **PR6** [PROD GATE, OWNER: user] → **PR7** (readers switch to stored values) → **PR7b** (stored-state UI, see below) → **PR8** → **PR11** → **PR16** → **PR17**.

**PR7b — stored-state UI (moved out of PR10, PR14 and PR15 because they need stored metrics):** PR10.T5 (the `recalculating`/`failed`/`pending` inputs of `alert_level`; the rest of alert_level ships in PR10 from live values), PR10.T7, PR10.T8, PR14.T9, and the stored-total part of PR15.T5 (the recalculating indicator). These tasks keep their IDs; they are implemented in PR7b, right after PR7. Until then the screen shows today's live values and has no recalculating badge (nothing is stored yet, so there is nothing stale to hide).

Previous strict order (superseded): Sequential auto-chain order actually merged (one branch at a time off `origin/main`): **PR1, PR2, PR3, PR4, PR5, PR6, PR7, PR8, PR9, PR10, PR11, PR12, PR13, PR14, PR15, PR16, PR17.** PR12 could move earlier (independent) but stays in chain order for auto-chain simplicity; note in PR12's description that it has no BE dependency beyond PR1.

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
| PR9 | Shared query layer extraction + search + product-level filters (flagged: exceeds ~400, includes its own index migration + 3 new facet params) | ~620 | PR8 (chain order; logically only needs PR1) | Med (parity refactor + new join surface, mitigated by dedicated index + EXPLAIN artifact) |
| PR10 | Additive listing fields | ~300 | PR9 | Low-Med (JSONB shape variance) |
| PR11 | Doubtful switches + KPI endpoint + aggregation | ~400 | PR10, PR6 (data), PR7 (ideally) | Med (parity tests, weighted markup math) |
| PR12 | Additive detail fields | ~200 | PR1 (chain: after PR11) | Low |
| PR13 | FE layout shell + panel skeleton + test migration | ~400 (flagged: 54-test migration) | PR7 | Med (accessibility/non-modal correctness) |
| PR14 | FE listing restyle + search + chips + badge | ~420 (flagged: many small components) | PR10, PR13 | Low-Med (visual + design tokens) |
| PR15 | FE new panel sections | ~350 | PR12, PR13 | Low-Med (test migration tail) |
| PR16 | FE KPI strip + switches + worker banner | ~350 | PR11, PR13 | Med (URL state, parity with BE toggles) |
| PR17 | Resync endpoint + button | ~350 | PR7 | Med (advisory lock, polling, external ML call) |

Bottleneck: PR6's PROD GATE (owner confirmation of divergence=0) blocks PR7, which in turn blocks PR11(data), PR13, PR16, PR17 — the single largest serialization point. PR4/PR5/PR6 are money-path-critical (missed trigger = silently wrong metric) and warrant the most review attention per the design's own risk table.

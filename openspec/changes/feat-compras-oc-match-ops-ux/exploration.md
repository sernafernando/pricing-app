# Exploration: feat-compras-oc-match-ops-ux

Post-live follow-up to `feat-compras-oc-match` (PR #1304). Operators need mid-flight stage visibility, a reclaim window that survives Gemini 503 backoff, and list/detail UX that matches TabPedidosCompra (`PedidoCompra.numero`, wrap errors, slightly wider detail pane).

Parent locked decisions stay: job table + poll, status CHECK `queued|running|done|error|skipped`, two short worker sessions with **no Session during Gemini**, MIME gate, mail OFF, tab permisos.

---

## Exploration: OC Match ops + UX follow-up

### Current State

**Lifecycle.** Jobs persist `queued → running → done|error` (or `skipped` at enqueue). List/detail/retry call `reclaim_stale_running` before serialize. A Coolify-style loop in `app.main.oc_match_reclaim_task` also sweeps every 600s. Reclaim is **clock-only on `started_at`**: `running` and `started_at <= now - 15m` → retryable `error` with `STALE_MESSAGE`. There is no heartbeat. Claim sets `started_at` once; the worker does not touch the row until `_persist` at the end.

**Why 15m fires in production.** `GeminiPool.generate_json` retries 503 with `time.sleep(15 * (n+1))` for attempts 1–7: **15+30+45+60+75+90+105 = 420s (7 min) per call**. The pipeline makes **two** Gemini calls (`extract_one`, then one batched `match_renglones`). Worst-case sleep alone is ~14 min, plus PDF inference. The two-session design holds **no DB session during Gemini**, so those sleeps cannot bump `updated_at`. A live job then looks identical to a dead uvicorn worker.

**UI.** `TabOcMatch` list column `pedido_id` (e.g. `202`) and detail `<dd>{selected.pedido_id}</dd>`. TabPedidosCompra shows `PedidoCompra.numero` (`String(32)`, generated at create — operators know that, not the PK). Error cells use `.tdError { white-space: nowrap; text-overflow: ellipsis }`. Detail pane is `grid-template-columns: minmax(0, 1fr) minmax(16rem, 24rem)`. Poll is 3s while `queued|running` (`useOcMatch` `OC_MATCH_ACTIVE`).

**API.** `OcMatchJobResponse` has `pedido_id`, not `numero`. List does **not** `joinedload(OcMatchJob.pedido)` today (join exists only for optional `empresa_id` filter). Relationship `OcMatchJob.pedido` already exists.

**Worker stages (natural, not persisted):** claim+load maestro → extract → match → excel → persist.

### Affected Areas

- `backend/app/services/oc_match/enqueue.py` — `RECLAIM_AFTER`, `STALE_MESSAGE`, reclaim predicate; clear phase on retry.
- `backend/app/services/oc_match/worker.py` — write mid-flight phase between Gemini/excel (short session); keep no Session during `generate_json`.
- `backend/app/services/oc_match/gemini_pool.py` — **read-only this change** (backoff math is the reclaim driver; do not couple the pool to the job table).
- `backend/app/models/oc_match_job.py` + Alembic — optional `progress_phase` column; do **not** widen `ck_oc_match_jobs_status`.
- `backend/app/schemas/oc_match.py` — `pedido_numero`, `progress_phase`.
- `backend/app/routers/administracion_compras.py` — `joinedload(OcMatchJob.pedido)` on list/detail; serialize `pedido.numero`.
- `backend/app/models/pedido_compra.py` — read `numero` only.
- `backend/tests/unit/test_oc_match_reclaim.py` (+ list/schema tests) — new minutes and phase/numero contracts.
- `frontend/src/components/compras/TabOcMatch.jsx` + `.module.css` + `TabOcMatch.test.jsx` — numero, phase subtitle, wrap errors, wider pane.
- `frontend/src/hooks/useOcMatch.js` — poll set stays `queued|running` (no new statuses).
- Parent specs to **modify** later: `openspec/changes/feat-compras-oc-match/specs/compras-oc-match-jobs/spec.md` (15-minute reclaim), `.../compras-oc-match-ui/spec.md` (list identity + running presentation).

### Approaches

#### A. Mid-flight progress: expand `status` enum vs `progress_phase` column

1. **Expand status CHECK** (`extracting|matching|excel` as first-class statuses)
   - Pros: one field; badge is the source of truth.
   - Cons: breaks list filters, `OC_MATCH_ACTIVE`, reclaim (`status == running`), retry CAS, parent spec, Alembic CHECK; poll/filter must learn every stage; reclaim false-positives still use `started_at`.
   - Effort: **High** (wrong seam)

2. **`progress_phase` column** (nullable `String`; status stays `running`) — **recommended**
   - Pros: orthogonal to lifecycle; poll/reclaim/retry unchanged; UI can show “Procesando · Extrayendo”; writing the phase in a **short session between stages** also bumps `updated_at` (cheap liveness between Gemini calls).
   - Cons: extra column + migration; phase is stale during an in-call 503 sleep (no Session by design).
   - Effort: **Low–Medium**

3. **FE-only inferred progress** (elapsed time heuristics)
   - Pros: zero schema.
   - Cons: lies during 503 backoff; cannot distinguish extract vs match.
   - Effort: Low (wrong)

#### B. Reclaim window: 45 vs 60 (and heartbeat)

Clock today: `started_at` + 15m. One full 503 backoff is 7 min; two calls ≈ 14 min sleep + inference. Production already lost a live job.

1. **45 minutes** — 3× current; covers two full backoffs (~14 min) + extract/match latency with margin. Zombie `running` after crash is visible within 45m (sweep every 10m, or sooner on tab poll).
2. **60 minutes** — extra pad for huge PDFs / future extra Gemini calls; zombies sit an extra 15m.
3. **Heartbeat-on-`updated_at` only, keep 15m** — phase writes between stages reset the clock, so wall-clock 18m jobs can survive 15m **if** extract itself stays under 15m including its own 7m sleep. Still false-positive if a **single** `generate_json` exceeds 15m (7m sleep + slow PDF).
4. **Heartbeat callback inside `gemini_pool.time.sleep`** — most correct liveness; **out of scope**: violates two-session rule unless a new short session is opened from the pool, coupling Gemini to the job row.

**Recommend:** raise to **45 minutes** on `started_at` (Gabe’s requested lever) **and** persist `progress_phase` between stages. Do **not** move reclaim onto `updated_at` in this change (phase writes help operators, not the 503-sleep window). Do **not** heartbeat from `gemini_pool`. Leave 60m as Gabe’s conservative alternative.

#### C. Pedido identity: BE `pedido_numero` join vs FE-only

1. **Backend join** — `joinedload(OcMatchJob.pedido)`, add `pedido_numero: str | None` on `OcMatchJobResponse` / detalle. List+detail same field. Keep `pedido_id` for identity.
   - Pros: one round-trip; matches TabPedidosCompra “Número”; no N+1; list already imports `PedidoCompra`.
   - Cons: small schema + test fixture updates.
   - Effort: **Low**

2. **Frontend-only** — map `pedido_id` → numero via extra pedidos fetch.
   - Pros: no migration.
   - Cons: extra ACL/pagination mismatch; list flashes PK then numero; N+1 or a second bulk endpoint.
   - Effort: Medium (worse UX)

**Recommend:** backend join. Column width ~160px like TabPedidosCompra.

#### D. Error column + detail width (no alternatives worth splitting)

- Error: drop nowrap/ellipsis on `.tdError`; `white-space: pre-wrap`; cap with `line-clamp: 3` so `table-layout: fixed` rows do not explode. Full text remains in `title` + detail pane (already unclipped).
- Detail pane: `minmax(16rem, 24rem)` → **`minmax(20rem, 28rem)`** (+4rem min and max). Stacked layout under 960px unchanged.

### Recommendation

**One cohesive change** (single PR expected; well under chained-PR threshold):

| Item | Decision |
|------|----------|
| Progress | Add nullable `progress_phase` (`extracting` \| `matching` \| `excel`). Status stays `running`. Worker writes phase in a short session **between** stages; clear on `queue_retry` / reclaim / persist. UI: badge still “Procesando”; secondary label for phase. Poll set unchanged. |
| Reclaim | `RECLAIM_AFTER = timedelta(minutes=45)` (pending Gabe vs 60). Predicate stays `started_at`. Update `STALE_MESSAGE`, reclaim tests, parent jobs spec. |
| Pedido | BE `pedido_numero` via `joinedload(pedido)`. FE list+detail show numero, keep `pedido_id` in payload. |
| Error | Multiline wrap, 3-line clamp, TabOcMatch CSS only (do not change shared `DataTable`). |
| Pane | `minmax(20rem, 28rem)`. |

**Out of scope:** expanding status enum; FE-only numero; Gemini retry/backoff retune; heartbeat from `gemini_pool`; Celery; mail; MIME/idempotency.

**Spec impact:** MODIFY parent “15-minute reclaim” requirement; ADD UI scenarios for phase subtitle, `pedido_numero`, wrapped error, pane width.

### Risks

- **45m still false-positive** if a single Gemini call (sleep + inference) exceeds 45m — unlikely with current 8-attempt backoff; 60m is the pad.
- **45m zombies:** crashed workers stay `running` longer. Tab still shows “Procesando”; operators retry only after reclaim. Acceptable vs killing live 503 backoff.
- **Phase write vs two-session rule:** must use a **new short `get_background_db()`** between stages, never a Session across `generate_json`. If the write fails, continue the pipeline (phase is UX, not correctness).
- **Alembic head:** new migration must revise current tip at merge (parent already hit this with `compras_040`).
- **List N+1:** join `pedido` on list/detail or the numero field will be null / extra queries.
- **Error clamp vs “full multiline”:** 3 lines is a table-height compromise; unbounded wrap can dwarf the list.

### Open Questions (Gabe)

1. **Reclaim minutes: 45 or 60?** Recommend **45**. 60 only if we want extra pad for huge PDFs. (Blocks propose lock.)
2. **Heartbeat from Gemini sleep in a later change?** Recommend **no** for this slice. Raise the clock instead.
3. **Error column: 3-line clamp or fully unbounded wrap?** Recommend **clamp 3**.
4. **Detail pane: `28rem` max vs `32rem`?** Recommend **`minmax(20rem, 28rem)`** (“slightly”).

### Ready for Proposal

**Yes**, after Gabe picks 45 vs 60. If silent, propose **45** and note the conservative 60 alternative.

---

### Gemini backoff (evidence)

```
# gemini_pool.generate_json attempts=8; on 503 if n < 7:
wait = 15 * (n + 1)  # n = 0..6 → 15,30,45,60,75,90,105 s = 420 s
```

Two calls (`extract.py` + `match.py`) → up to ~14 min idle with `status=running` and frozen `started_at`. Reclaim at 15 min is shorter than that window.

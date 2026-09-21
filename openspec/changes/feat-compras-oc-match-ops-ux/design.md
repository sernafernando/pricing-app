# Design: feat-compras-oc-match-ops-ux

## Technical Approach

Keep the parent two-session worker and status CHECK. Add nullable `progress_phase` as UX between extract/match/excel. Reclaim 45 minutes on `started_at`. `joinedload(OcMatchJob.pedido)` → `pedido_numero` (keep `pedido_id`). TabOcMatch: selected job expands full-width under the list (no side pane). Specs: jobs, pipeline, ui.

## Architecture Decisions

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Expand status CHECK vs `progress_phase` | Enum breaks poll, reclaim CAS, filters | **Column.** Status stays `running`. |
| Reclaim 45m vs 60m vs `updated_at` | 45m covers ~14m 503 sleep; 60m extra zombies; `updated_at` still false-positives one long `generate_json` | **45m on `started_at`.** |
| Heartbeat from `gemini_pool.sleep` | True liveness; Session during Gemini | **Rejected.** |
| BE `joinedload(pedido)` vs FE fetch | One round-trip vs N+1 / ACL mismatch | **BE `pedido_numero`.** Keep `pedido_id`. |
| Error nowrap vs clamp-3 vs unbounded | Table height vs readability | **`pre-wrap` + `line-clamp: 3`**, TabOcMatch CSS only. |
| Side pane 28rem vs modal vs expand-below | 24rem clips renglones | **Expand-below full-width.** 28rem pane **rejected**. |
| Phase write vs pipeline correctness | Extra short sessions | **Fail-soft.** Job result ignores phase. |

## Data Flow

```
claim session (queued→running) ──close──►
  write extracting ──► extract_one (NO Session)
  write matching  ──► match_renglones (NO Session)
  write excel     ──► generar (NO Session)
persist: status done|error, progress_phase=null
poll ──► reclaim(started_at>45m) ──► serialize + pedido.numero
```

## Worker phase write points

`_write_progress_phase(job_id, phase)`: `with get_background_db()`, set `progress_phase` + `updated_at`, not `status`. Wrap the `with` in `except Exception` (log warning). Never call from `gemini_pool`. Stale during in-call 503 sleep (by design).

| When | Value |
|------|-------|
| Enter extract (after claim closed) | `extracting` |
| Enter match | `matching` |
| Enter excel | `excel` |
| `_persist` success | `null` |
| `queue_retry` / `reclaim_stale_running` | `null` |

## Data model / API

`progress_phase` `String(20)` nullable. CHECK `progress_phase IS NULL OR progress_phase IN ('extracting','matching','excel')` (`ck_oc_match_jobs_progress_phase`). Do not alter `ck_oc_match_jobs_status`. No phase index.

`OcMatchJobResponse` (Pydantic v2 `ConfigDict(from_attributes=True)`): add `progress_phase` and `pedido_numero` (`str | None`). Keep `pedido_id`.

Serialize list/detail/retry with the existing `model_copy` pattern: `pedido_numero = getattr(getattr(job, "pedido", None), "numero", None)`.

`listar_oc_match_jobs`: `.options(joinedload(OcMatchJob.pedido))` even when `empresa_id` already joins `PedidoCompra`. `_obtener_oc_match_job_o_404`: add `joinedload(pedido)` beside renglones. Missing pedido → `pedido_numero=null`, 200.

## UI layout

`.layout` → single column. Remove `minmax(16rem, 24rem)` grid and the 960px stack. Reuse `detailBody`. Render detail only when `selected`; no empty aside, no modal. Renglones use full width.

Pedido column: `pedido_numero || '—'`, ~160px; `pedido_id` stays in payload. Badge stays “Procesando”; secondary label `Extrayendo` / `Matcheando` / `Excel`. `useOcMatch` / `OC_MATCH_ACTIVE` unchanged. `.tdError`: drop nowrap/ellipsis; `pre-wrap` + `-webkit-line-clamp: 3`; keep `title`.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/alembic/versions/compras_041_oc_match_progress_phase.py` | Create | Column + CHECK. `down_revision` = unique `alembic heads` at merge (branch tip `compras_040_oc_match`). |
| `backend/app/models/oc_match_job.py` | Modify | Column + CHECK. |
| `backend/app/services/oc_match/enqueue.py` | Modify | 45m reclaim, `STALE_MESSAGE`, clear phase. |
| `backend/app/services/oc_match/worker.py` | Modify | Helper; three writes; persist clear. |
| `backend/app/schemas/oc_match.py` | Modify | `progress_phase`, `pedido_numero`. |
| `backend/app/routers/administracion_compras.py` | Modify | `joinedload(pedido)`; inject numero. |
| `backend/tests/unit/test_oc_match_reclaim.py` | Modify | 46m reclaim; 15m lives; phase cleared. |
| `backend/tests/integration/test_oc_match_enqueue.py` | Modify | `pedido_numero` + `pedido_id`. |
| `backend/tests/integration/test_oc_match_worker.py` | Modify | Phase sequence, fail-soft, persist null. |
| `frontend/src/components/compras/TabOcMatch.jsx` | Modify | Numero, phase, stacked detail. |
| `frontend/src/components/compras/TabOcMatch.module.css` | Modify | Column layout; error clamp. |
| `frontend/src/components/compras/TabOcMatch.test.jsx` | Modify | Numero, phase, expand-below, title. |

Unchanged: `useOcMatch.js`, `gemini_pool.py`, `pedido_compra.py` (read `numero` only).

## Interfaces / Contracts

No new routes. List/detail/retry gain nullable `progress_phase` and `pedido_numero`. Status filter unchanged.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|--------------|----------|
| Unit | 45m reclaim vs 15m live; retry/reclaim clear phase | `test_oc_match_reclaim.py` |
| Unit | Phase write fail-soft continues pipeline | Raise in helper; extract still runs |
| Integration | List/detail numero + id; missing pedido null | `test_oc_match_enqueue.py` |
| Integration | extracting→matching→excel then null | Spy helper in `test_oc_match_worker.py` |
| FE | Numero; Procesando+phase; no aside; error `title` | `TabOcMatch.test.jsx` |
| FE | Poll set `queued\|running` | Existing `useOcMatch.test.js` |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR, executable-file, or process-integration boundary.

## Migration / Rollout

Add-column + CHECK; existing rows null. Retarget `compras_041` `down_revision` to the unique head at merge (same trap as `compras_040`). Downgrade drops column/CHECK. No flag. Single PR.

## Open Questions

- None. Locked in `state.yaml`.

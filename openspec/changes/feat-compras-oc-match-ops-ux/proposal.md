# Proposal: feat-compras-oc-match-ops-ux

## Intent

Live OC Match (PR #1304) reclaim at 15 minutes kills jobs during Gemini 503 backoff (~14 min sleep, no Session). Operators see `pedido_id` not `PedidoCompra.numero`, clipped errors, and a narrow side pane. Need stage labels, a 45-minute reclaim, and TabPedidosCompra-aligned list/detail UX.

## Scope

### In Scope
- Nullable `progress_phase` (`extracting` | `matching` | `excel`); status CHECK unchanged.
- Worker writes phase in a short `get_background_db()` session **between** stages; clear on retry/reclaim/persist.
- `RECLAIM_AFTER = 45 minutes` on `started_at`; update `STALE_MESSAGE` + tests.
- List/detail `joinedload(OcMatchJob.pedido)`; `pedido_numero` on response; keep `pedido_id`.
- Error cells: wrap + `line-clamp: ~3` (TabOcMatch CSS only); full text in `title` + detail.
- Stacked list + **expand-below full-width** detail (reuse existing JSX); renglones use full interface width.
- Single PR.

### Out of Scope
- Expand status enum; `gemini_pool` heartbeat or backoff retune; reclaim on `updated_at`; 60-minute reclaim; side pane 24→28rem; modal; FE-only numero; Celery; mail; MIME/idempotency.

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `compras-oc-match-jobs`: reclaim 15m → 45m on `started_at`; add `progress_phase` + `pedido_numero`.
- `compras-oc-match-pipeline`: persist `progress_phase` between extract/match/excel; no Session during Gemini.
- `compras-oc-match-ui`: `pedido_numero` + phase subtitle; wrap/clamp errors; expand-below full-width detail (not side pane).

## Approach

Two-session worker. Phase writes are UX between stages, not a Gemini heartbeat. Reclaim stays clock-on-`started_at`. Poll remains `queued|running`. Badge stays “Procesando”; secondary label for phase.

## Affected Areas

- Modified: `oc_match_job.py` + Alembic (`progress_phase`); `worker.py` (short-session phase writes); `enqueue.py` (45m reclaim, clear phase); `schemas/oc_match.py`; `administracion_compras.py` (`joinedload(pedido)`); `test_oc_match_reclaim.py`; `TabOcMatch.jsx` + CSS + test (numero, phase, clamp, stacked expand-below).
- Unchanged: `useOcMatch.js` poll set; `gemini_pool.py`.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| One Gemini call exceeds 45m | Low | 8-attempt backoff max ~7 min/call |
| Crashed workers stay `running` 45m | Med | Accept vs killing live 503; 10m sweep + poll |
| Phase write fails | Low | Fail-soft; continue pipeline |
| Alembic multi-head at merge | Med | Revise current tip |
| List N+1 / null numero | Med | `joinedload(pedido)` on list and detail |

## Rollback Plan

Downgrade Alembic (drop `progress_phase`). Restore `RECLAIM_AFTER=15`. Revert TabOcMatch layout/CSS and schema fields. Status enum untouched.

## Dependencies

- Parent `feat-compras-oc-match` (PR #1304). No new Gemini keys.

## Success Criteria

- [ ] `running` jobs expose `progress_phase` without new statuses; poll stays `queued|running`.
- [ ] `running` >45 min on `started_at` → retryable `error`; 15 min live jobs survive.
- [ ] List and detail show `pedido.numero`; payload still has `pedido_id`.
- [ ] Error column wraps, clamps ~3 lines; selected job expands full-width under the list; renglones use full width; no side pane/modal; `gemini_pool.py` unchanged.

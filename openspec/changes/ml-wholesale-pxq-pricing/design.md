# Design: MercadoLibre Wholesale (PxQ) Pricing

Binding constraints from the user (B2C out, bulk authoring out, weight-derived shipping removed
entirely, dedicated permission, nothing silent) are treated as settled. This document specifies HOW.

## Technical Approach

Four independent seams: (1) a pure quantity-aware markup wrapper that never sees a per-unit shipping
value; (2) a local `ml_pxq_tier` mirror that is the sole source of truth for the array-replace diff;
(3) a kill-switched write service mirroring `ml_promotions_write_service.py`; (4) a collapse epoch in
`treeViewStore.js`. No existing pricing column is written anywhere.

## Architecture Decisions

| # | Decision | Alternatives rejected | Rationale |
|---|---|---|---|
| D1 | New module `backend/app/services/pxq_markup.py` wraps `calcular_comision_ml_total` + `calcular_limpio` with `precio_unitario * cantidad_minima`; `pricing_calculator.py` is **not** modified | Add a `cantidad` param to `calcular_limpio`; new endpoint | The formula is correct; only its inputs were wrong. Touching a shared money function risks every existing caller. Zero-regression seam. |
| D2 | Shipping is a required, defaultless parameter typed as a distinct value object `ShipmentShippingCost` (total for the whole shipment), produced only by `resolve_tier_shipping(tier) -> ShipmentShippingCost \| None` | Optional `costo_envio: float = 0.0`, precedence chain with per-unit fallback | Makes the forbidden silent fallback *structurally* impossible: a caller holding only `producto.envio` (a float) cannot construct the type, and there is no default to fall through to. `None` propagates as `estado='incompleto'`. |
| D3 | PxQ code must not import `ProductoPricing` at all | Import it and "just not write it" | Convention is not an invariant. An AST import-scan test over `pxq_markup.py` / `ml_pxq_write_service.py` / the PxQ router turns the boundary into a failing test. Plus a runtime assert that `db.dirty | db.new` contains no `ProductoPricing` before commit. |
| D4 | Local mirror table is authoritative for the diff; divergence vs live **refuses** the write (409) and offers an explicit `adopt-live` action | Local-wins overwrite; live-wins auto-import | `POST /prices/standard/quantity` replaces the whole array; an unmirrored live tier would be silently deleted. No implicit resolution anywhere. |
| D5 | Dedicated permissions `pxq.ver` / `pxq.escribir`, backfilled from the *actual* live grants of `promos.escribir` (roles **and** user overrides, including negative ones) | Reuse `promos.escribir`; hardcode role list | Money-path transparency; a hardcoded role list would drift from production. Copying `concedido=false` overrides prevents a user explicitly revoked from promo writes silently gaining PxQ writes. |
| D6 | Collapse epoch counter + tri-state in the store, **not persisted**; nodes sync in `useEffect([epoch])` | Store per-node open map; persist the mode | Manual per-node toggles never touch the store, so the epoch does not change and the global state cannot fight them. Not persisting avoids a reload forcing every node open. |

## Data Model

`ml_pxq_tier` (Alembic `20260801_add_ml_pxq_tier.py`, explicit types, FKs indexed):

| Column | Type | Notes |
|---|---|---|
| `id` | `Integer` PK | |
| `publicacion_ml_id` | `Integer` FK → publicaciones ML, **indexed** | |
| `item_id` | `String(32)`, indexed | MLA, denormalized for live compare |
| `cantidad_minima` | `Integer` | `> 1` (CheckConstraint); unique with `publicacion_ml_id` |
| `precio_unitario` | `Numeric(14,2)` | |
| `costo_envio_total` | `Numeric(14,2)` nullable | whole-shipment; NULL ⇒ incompleto |
| `ml_price_id` | `String(64)` nullable | live id last confirmed |
| `estado` | `String(16)` | `incompleto` \| `listo` \| `sincronizado` \| `desconocido` |
| `usuario_id` | `Integer` FK, indexed | |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | tz-aware |

Max 5 rows per `publicacion_ml_id`, enforced in the service (validated, 422) — not a DB constraint.

## Reconcile + Diff Algorithm

```
sync(item_id):
  1. settings.PXQ_WRITE_ENABLED is False        -> disabled_outcome (no ML traffic)
  2. permission pxq.escribir                    -> else 403
  3. eligibility: seller `business` tag, item `standard_price_by_quantity`
                                                -> else rejected_not_eligible
  4. LIVE read (fresh, never cached) via ml_webhook_client
       None -> rejected_read_unavailable
  5. desired = tiers with estado != 'incompleto' (costo_envio_total NOT NULL)
  6. three-way merge of each desired tier against LIVE and the SNAPSHOT
     (cantidad_sincronizada/precio_sincronizado -- what ML confirmed at the
     last successful sync; NULL means never synced):
       local vs snapshot | live vs snapshot | outcome
       ------------------|------------------|--------------------------------
       unchanged         | unchanged        | keep    -> {"id": ml_price_id}
       CHANGED           | unchanged        | modify  -> delete old id (omit)
                          |                  |           + create without id
       unchanged         | CHANGED          | 409 refuse (writing would revert
                          |                  |   MercadoLibre's own change)
       CHANGED           | CHANGED          | 409 refuse (genuine concurrent edit)
       no snapshot, no id | n/a             | create -> {qty, amount}, no id
       id set, no snapshot | n/a             | 409 refuse (no base to compare
                          |                  |   against -- see pxq_diff.py)
       mirror id absent from live entirely   | 409 refuse
     tiers absent from `desired` are simply omitted from the array (delete);
     an untracked live tier (no desired row references its id) is preserved
     as a keep, UNLESS `desired` is empty and `allow_clear=true`, which wipes
     every live tier including untracked ones via an explicit `[]`.
  7. POST full array; re-read live; CONFIRM each written/kept tier by
     matching (quantity, amount) in the re-read, and ONLY THEN write the
     snapshot (cantidad_sincronizada/precio_sincronizado) from those
     CONFIRMED values; estado='sincronizado'.
```

An earlier draft of this algorithm decided step 6 by reading the row's `estado` (`listo` vs
`sincronizado`) instead of a shared snapshot, and its own step 5/6 wording called any matched-id
difference a "divergence" while also calling it a "modify" -- literally impossible to satisfy
together, since a legitimate local price edit and an external ML-side change produced the identical
symptom (matched id, differing qty/amount) with no way to tell them apart. The snapshot is the shared
base that resolves the contradiction: local and live are each judged against what ML last confirmed,
not against each other, so "who moved this" becomes answerable instead of guessed. See
`pxq_diff.py`'s module docstring for the full case table and the implementation.

Invariant: step 6/7 may only emit ids observed in the step-4 live payload.

**Failure modes.** Timeout/5xx on the POST ⇒ `ambiguous_needs_reconcile`: mirror rows set to
`desconocido`, `ml_price_id` AND the snapshot left untouched (not advanced to the attempted value),
next sync necessarily hits the divergence gate (6). Live read fails ⇒ refuse. Empty desired set ⇒
refuse unless an explicit `allow_clear=true` flag (deleting all tiers must be intentional). Post-write
re-read fails ⇒ `submitted_unconfirmed`, mirror `desconocido`, snapshot left untouched -- the snapshot
is written ONLY on a write CONFIRMED by the post-write re-read, never on the POST response alone;
writing it early or on any non-confirmed path is what silently degrades the three-way merge back into
the blind overwrite this mirror exists to prevent.

## Live-Read Endpoint (pool-safe)

`GET /api/pxq/{item_id}/live -> PxqLiveStateResponse` (explicit `response_model`).
`Depends(get_current_user_transient)` — **no** `Depends(get_db)`. Sequence: open a short session in a
`with` block, load mirror rows into plain dataclasses, **close it**, then `await` the proxy read with
no session held, then compare in memory. This is the QueuePool-exhaustion rule from
`backend/CLAUDE.md`.

Staleness/errors: response carries `fetched_at` and `live_status` (`ok` | `unavailable`). Never
cached server-side. `unavailable` returns 200 with `live_tiers: null` and the UI renders an error
band with the sync button disabled (fail-closed). The write path always performs its own fresh read;
this endpoint's payload never authorizes a write. The UI shows live tier state above the tier input
**always**, not only on divergence.

## Frontend Collapse State

```js
// treeViewStore.js — persist partialize: only { showFamilia }
collapseEpoch: 0,
collapseMode: 'manual',              // 'manual' | 'all-open' | 'all-closed'
expandAll:  () => set(s => ({ collapseEpoch: s.collapseEpoch + 1, collapseMode: 'all-open'  })),
collapseAll:() => set(s => ({ collapseEpoch: s.collapseEpoch + 1, collapseMode: 'all-closed'})),
```
`TreeNode.jsx`: `useEffect(() => { if (epoch === 0) return; const open = mode === 'all-open';
setIsOpen(open); setPromosOpen(open); }, [epoch])`. Manual toggles mutate only local state.

## Testing Strategy (strict TDD — RED first)

| Layer | What | Assertion |
|---|---|---|
| Unit (money) | `pxq_markup` golden cases 1/5/10/30/70 units vs the verified shipping table | limpio subtracts the **whole-shipment** cost once; regression test proves one-unit shipping is never subtracted from an N-unit order |
| Unit (structural) | `resolve_tier_shipping` returns `None`; signature has no shipping default | `inspect.signature` has no default for the shipping param; float cannot substitute |
| Unit (boundary) | AST import scan of PxQ modules | `ProductoPricing` / `productos_pricing` absent; `markup_rebate`/`markup_oferta` unchanged after a full sync |
| Unit (diff) | keep / create / delete / modify matrix, empty-desired guard, ids-only-from-live invariant | exact emitted array |
| Unit (gates) | kill-switch OFF, missing `pxq.escribir` → 403, ineligible seller/item, incomplete tier, divergence → 409 | no downstream ML call made |
| Integration | `GET .../live` opens no long-lived session; `live_status=unavailable` → 200 + disabled write | session count / mocked proxy |
| Frontend (vitest) | global toggle drives every node; a manual toggle after a global toggle sticks | |

Backend: `pytest tests/ -v --tb=short` from `backend/`, `ENVIRONMENT=testing`,
`DATABASE_URL=sqlite:///./test.db`. `ruff format app/` before every push (CI-enforced).

## Threat Matrix

N/A — no shell, subprocess, VCS/PR automation, or executable-file classification boundary. The only
external process integration is the existing ml-webhook HTTP proxy, already covered by the
kill-switch / eligibility / fresh-live-read gates above.

## PR Slicing (validated)

| # | Slice | Est. | Depends on |
|---|---|---|---|
| 1 | Collapse epoch in store + `TreeNode` sync + vitest | ~150 | — |
| 2 | `ml_pxq_tier` model + migration + **permissions migration** + `pxq_markup` + tests | ~370 | — |
| 3 | Diff/reconcile + `ml_pxq_write_service` + `PXQ_WRITE_ENABLED` + live-read & sync endpoints + tests | ~390 | 2 |
| 4 | PxQ panel: live state display, tier form, divergence banner | ~330 | 1, 3 |

Adjustment vs the proposal: the permission catalog + backfill migration moves into **PR 2** (the
promos precedent — declaring both codes up front keeps PR 3 purely additive). No forward dependency:
PR 2 ships storage and correct math with no ML traffic; PR 3 is inert with `PXQ_WRITE_ENABLED=False`
(default in code); PR 4 renders only what PR 3 exposes. Contingency: if PR 3 exceeds 400 lines, split
the pure diff function + its tests into PR 3a.

## Open Questions

- [ ] `allow_clear` UX for deleting every tier — confirm the explicit-confirmation shape in PR 4.
- [ ] Whether `adopt-live` should require `pxq.escribir` (it writes only local rows) — proposed: yes.

# Design: Informational PPP cost and PPP markups in Productos

> **SOURCE CORRECTION (2026-07-29)**: everything below was written against `ItemTransaction.it_priceofcostpp`,
> which turned out to be the WRONG field — verified against the live GBP ERP "Costo PPP" screen, it does not
> match (see `exploration.md`'s "SOURCE CORRECTION" section for the full evidence and root cause). The actual
> source is `ItemCostListHistory.iclh_price_aw` (`coslis_id=1`, latest `iclh_cd`, tiebreak `iclh_id DESC`),
> carried in its OWN currency (`curr_id`) and NEVER converted for display (conversion is only applied
> internally, as an input to the markup formula, since `limpio` is always ARS). The `DISTINCT ON`/LATERAL
> query-plan discussion below no longer applies as designed either: `tb_item_cost_list_history` has no
> equivalent composite index and is much smaller, so the resolver now uses a single portable
> `ROW_NUMBER()` formulation with no dialect branching — see `costo_ppp_service.py`'s module docstring.
> The `PppPayload` contract below is also stale: `moneda` replaces the `fecha`-only assumption of ARS,
> and there is no `costo_display`/`costo_display_moneda` (that later addition was itself a second,
> now-removed bug — an invalid ARS→USD-via-today's-rate conversion of a historical weighted average).
> This document is left in place as the historical record of the (wrong) original design.

## Technical Approach

One batch resolver reads the latest qualifying `it_priceofcostpp` per `item_id` for the page,
one per-product accumulator turns already-computed `limpio` values into PPP markups, one nested
payload field carries everything, one frontend component renders every companion line.
No pricing behaviour, no stored column, no filter changes.

## Architecture Decisions

| Decision | Choice | Alternatives rejected | Rationale |
|---|---|---|---|
| Read strategy | New `app/services/costo_ppp_service.py` → `resolver_ppp_batch(db, item_ids) -> dict[int, PppSource]`, ONE `DISTINCT ON (item_id)` query per page | per-row LATERAL in the ORM loop; denormalize onto `productos_erp` | Mirrors the existing `resolver_costos_envio_batch` (`app/services/envio_real_service.py:133`) and `pubs_by_item` prefetch. N+1 is structurally impossible: the loop only does dict lookups, it has no `db` access to the table. Denormalizing adds a migration + refresh job for data already synced every 5 min. |
| Avoiding 3× copy-paste | `PppMarkups` accumulator in the same service. Each block builds one per product; each of the ~10 sites adds exactly ONE line `ppp.record("clasica", limpio)` | copy the `calcular_markup` + `*100` + rounding + null-guard into each of ~30 site/block combinations | `limpio` only exists at the call sites, so the call must be there — but the derivation, the ×100 scaling, rounding, and the no-data guard live once. The three blocks (~900-1210, ~2098-2280, ~2442-2560) share one definition. |
| Formula | `calcular_markup(limpio, costo_ppp)` with PPP passed untouched (already ARS) | `calcular_precio_producto()` / goalseek; frontend re-derivation | Goalseek returns a *price*; frontend cannot reproduce per-site FX gates from a rounded payload markup. |
| Index | Add composite `(item_id, it_cd DESC)` on `tb_item_transactions` via Alembic **only if** `EXPLAIN (ANALYZE, BUFFERS)` on the `DISTINCT ON` shows a Sort/heap scan | ship blind; skip measurement | Existing indexes are separate (`item_id`, `it_cd`), which does not serve per-item top-1. Evidence before DDL on a large ERP table. |
| Payload | ONE nullable nested object `ppp` on `ProductoResponse` / `ProductoTiendaResponse` | 12+ flat `markup_ppp_*` keys | Additive and non-breaking; the no-data contract becomes a single `ppp is None` check instead of 14 nullable keys that can individually drift into a fallback. |

## Data Flow

    page query ──→ item_ids ──→ resolver_ppp_batch (1 SQL) ──→ ppp_by_item
                                                                  │
    per product: PppMarkups(costo_ppp) ←───────────────────────────┘
        site: limpio ──→ ppp.record(key, limpio)
                                │
                        ProductoResponse.ppp ──→ <PppLine> under cost + 12 markups

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/app/services/costo_ppp_service.py` | Create | `PppSource`, `resolver_ppp_batch`, `PppMarkups` (single source of the row-selection rule and derivation) |
| `backend/app/api/endpoints/productos_shared.py` | Modify | `PppPayload` model; `ppp: Optional[PppPayload] = None` on `ProductoResponse` + `ProductoTiendaResponse` |
| `backend/app/api/endpoints/productos_listing.py` | Modify | one prefetch call per block; one `ppp.record(...)` line at 965, 996, 1049, 1092, 1127, 1390, 2138, 2164, 2252, 2493, 2530; `ppp=ppp.payload()` in the three response builders |
| `backend/alembic/versions/YYYYMMDD_*.py` | Create (conditional) | composite index; generate only after `alembic heads` returns exactly ONE head |
| `frontend/src/hooks/useProductosOffsets.js` | Modify | pure `formatPppMonto` / `formatPppFecha` (dd/mm/aa) next to `calcularMarkupConOffset`/`getMarkupColor` |
| `frontend/src/components/PppLine.jsx` | Create | `<PppLine ppp={p.ppp} markupKey="clasica" />`; JSX cannot live in a `.js` file under Vite's default loader, so the component is separate from the formatters |
| `frontend/src/pages/Productos.jsx` | Modify | 1 line under the cost cell (1715) + 12 markup spots |

## Interfaces / Contracts

```python
class PppPayload(BaseModel):
    costo: float           # ARS, never null when `ppp` is present
    fecha: date            # it_cd of the source row, always rendered
    markups: dict[str, float]   # percent; keys only for computed sites
```

`ppp = None` ⇒ UI renders "sin PPP". Fallback to `costo` is forbidden at every layer;
`PppMarkups` returns `None` for the whole payload when `costo_ppp` is absent, so no call site
can construct a partial one.

## Testing Strategy

| Layer | What to test | Approach |
|---|---|---|
| Unit | Row-selection rule: cancelled / `it_exchangetobranchcurrency IS NULL` / RMA / credit-note / `pp <= 0` rows excluded; latest `it_cd` wins | pytest against seeded `tb_item_transactions` fixtures |
| Unit | No-data contract: item with zero qualifying rows ⇒ `ppp is None`, and no key equals `costo` | assert identity, not just nullness |
| Unit | `PppMarkups.record` scaling/rounding parity with the site it replaces | direct helper test |
| Integration | Golden no-regression: snapshot every existing markup/price field of `/productos` before and after; diff must be empty except the new `ppp` key | endpoint test on a fixed fixture page |
| Integration | Query count: one PPP query per request regardless of page size | `sqlalchemy` event counter asserting `== 1` for page_size 1 and 100 |
| Manual | `EXPLAIN (ANALYZE, BUFFERS)` before/after the index, recorded in the PR | staging DB |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or
process-integration boundary. Display-only read path.

## Migration / Rollout

No data migration. At most one additive index migration, created only against a verified single
Alembic head (the repo has a multiple-heads history). Rollback = revert PRs; the index drops
independently. 3-PR slicing per the proposal. `Productos.jsx` renormalization noise, if any,
goes in its own commit before the feature commit.

## Open Questions

- [ ] Whether the composite index is needed — decided by EXPLAIN during PR1, not up front.

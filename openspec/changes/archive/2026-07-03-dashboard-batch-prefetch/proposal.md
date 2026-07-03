# Proposal: Batch-Prefetch the N+1 Query Sites in the Rentabilidad/Offset Dashboards

> Change: `dashboard-batch-prefetch`
> Eliminates the per-group N+1 query pattern paid on **every dashboard refresh**
> across the rentabilidad and offset-consumo endpoints (evaluacion-integral
> **P-4**). Replaces 6 in-loop `.first()` lookups with a shared batch-prefetch
> helper (`collect ids → one .in_() query → dict → in-loop lookup`), the exact
> pattern already proven in `productos_listing.py` (T-3..T-7).
> **No behavior change, no schema/migration, no response-shape change** — pure
> query-count reduction from **O(distinct-groups)** to **O(1)** per endpoint.
> Single PR, estimated ~150–250 lines.

## Why

The `evaluacion-integral-2026-07-02.md` review flagged **P-4**: the rentabilidad
and offset-consumo dashboard endpoints issue **one DB query per distinct group**
inside their response-building loops. These endpoints run on **every dashboard
load** — the exact hot path a pricing operator hits dozens of times a day — so
the N+1 cost is paid repeatedly and grows linearly with the number of offset
groups, adding avoidable latency and DB round-trips to an interactive screen.

The exploration (`sdd/dashboard-batch-prefetch/explore`) mapped **6 concrete
sites across 5 files**, line numbers verified against `main`:

| # | File (`backend/app/api/endpoints/`) | Line | In-loop query |
|---|-------------------------------------|------|---------------|
| 1 | `rentabilidad_dashboard.py` | 330 | `OffsetGrupoResumen.filter(grupo_id==offset.grupo_id).first()` |
| 2 | `rentabilidad_tienda_nube.py` | 332 | `OffsetGrupoResumen` per grupo |
| 3 | `rentabilidad_tienda_nube.py` | 416 | `OffsetIndividualResumen` per offset |
| 4 | `rentabilidad_fuera.py` | 385 | `OffsetGrupoResumen` per grupo |
| 5 | `offsets_ganancia/_consumo_grupos.py` | 73 & 385 | **TWO** queries per grupo: `OffsetGrupoResumen` **and** the `offset_con_limite` `OffsetGanancia` lookup |
| 6 | `offsets_ganancia/_consumo_individual.py` | 426 & 449 | `OffsetIndividualResumen` per offset |

Sites 1–4 and 6 are straightforward 1:1 lookups (`grupo_id`/`offset_id` is unique
per resumen row), so `.first()` is trivially equivalent to a batched
`.in_()`+dict. The `offsets_grupo_calculados` / `offsets_individuales_calculados`
dict-membership guard already deduplicates repeated hits for the SAME group within
one request, so the N+1 is bounded by **distinct group count** rather than total
offset count — still N queries instead of 1 batch, but that is the whole point:
one bounded batch query replaces the linear growth.

Site 5 has a **correctness nuance** (see the CRITICAL constraint below): its
second query (`offset_con_limite`) picks "any offset in the group that has a
limit" and today relies on a **non-deterministic tie-break**.

**Evidence of the proven fix**: `productos_listing.py` (L608–712, T-3..T-7)
already implements exactly this pattern inline: collect keys before the loop →
one `db.query(Model).filter(Model.key.in_(keys)).all()` → build `{key: row}` →
loop uses `dict.get(key)` with zero in-loop queries. This change replicates that,
extracted into a small shared helper because the same
`OffsetGrupoResumen`/`OffsetIndividualResumen` fetch-by-key shape repeats
identically across 5 of the 6 sites.

Success =

1. Each of the 6 endpoints issues a **bounded (O(1)) number of queries** for the
   resumen lookups, **independent of how many groups/offsets** are in the
   response — proven by query-count assertions.
2. Responses are **byte-identical** to today's for representative multi-group
   fixtures (this is a refactor, not a feature).
3. New tests are green and the **entire existing backend suite stays green**
   (`cd backend && pytest tests/ -v --tb=short`).

## What Changes

A mechanical query-shape refactor. **No endpoint changes its response schema, its
business logic, or its output values.** The only thing that changes is *how many
queries* each endpoint runs to gather the resumen data.

### Fixed decision (product owner — encode, do NOT reopen)

- **Scope is dashboards (P-4) ONLY.** Exports (`productos_export.py`, P-3) are
  **explicitly OUT** — a separate future change. **Caching (P-6) is also OUT.**

### Shared batch-prefetch helper (covers 5 sites)

New module `backend/app/services/offset_resumen_service.py` with two functions:

- `fetch_resumenes_grupo(db, grupo_ids) -> dict[int, OffsetGrupoResumen]` — one
  `OffsetGrupoResumen.filter(grupo_id.in_(grupo_ids)).all()`, keyed by `grupo_id`.
  Used by sites 1, 2, 4, and the first query of site 5.
- `fetch_resumenes_individuales(db, offset_ids) -> dict[int, OffsetIndividualResumen]`
  — one `.filter(offset_id.in_(offset_ids)).all()`, keyed by `offset_id`. Used by
  sites 3 and 6.

Each call site changes from `db.query(...).filter(key==x).first()` **inside** the
loop to: collect the ids **before** the loop, call the helper once, then
`resumenes.get(x)` **inside** the loop.

### Ordered helper for the `_consumo_grupos.py` tie-break site (site 5, 2nd query)

The `offset_con_limite` query (`OffsetGanancia.filter(grupo_id==grupo.id,
or_(max_unidades not null, max_monto_usd not null)).first()`) is **not** a 1:1
lookup — a group can have multiple offsets with limits, and today `.first()`
returns whichever row the DB happens to surface first (a **non-deterministic**
tie-break). Its batch replacement groups the offsets by `grupo_id` in Python after
**one** `.in_(grupo_ids)` fetch and takes the first per group, adding an explicit
**`ORDER BY id ASC`** to the batch query (see CRITICAL constraint).

### CRITICAL correctness constraint (deliberate, tested behavior-pinning)

The batch fix for site 5's `offset_con_limite` query **MUST** add
**`ORDER BY id ASC`** so that "first matching offset per group" becomes
**deterministic (lowest id wins)**.

- Today's `.first()` tie-break is **arbitrary** — there is no `ORDER BY`, so which
  row wins on a multi-limit group is undefined (implementation/plan-dependent).
- Pinning it to **lowest-id** is therefore **safe and an improvement**: it cannot
  regress a guaranteed behavior (there is none), and it makes the endpoint's
  output reproducible.
- This is a **deliberate behavior-pinning**, called out explicitly here so
  reviewers do not read it as an accidental behavior change. It requires an
  **explicit tie-case test** (a group with ≥2 limit-bearing offsets asserting the
  lowest-id row is chosen).

## Scope / Non-Goals

### In Scope

- **The 6 N+1 sites** across the 5 files listed above, converted to batch-prefetch.
- **The shared helper** `app/services/offset_resumen_service.py`
  (`fetch_resumenes_grupo` + `fetch_resumenes_individuales`) plus the small ordered
  batch helper for the `_consumo_grupos.py` `offset_con_limite` tie-break.
- **A query-count test harness**: query-count assertions per endpoint (proving
  O(1) resumen queries regardless of group count) plus the tie-case determinism
  test. Reuse the existing `before_cursor_execute` counter pattern from
  `tests/compras/test_varianza_tc_batch.py` (~L423–436); worth extracting to a
  reusable conftest fixture given 6 sites need it.

### Out of Scope (explicitly deferred)

- **Exports (P-3, `productos_export.py`)** — fixed decision: separate future change.
- **Caching (P-6)** — fixed decision: out. Cache invalidation (offset consumo
  changes on every sale sync) is a distinct concern from query count and would
  blur the "no behavior change" guarantee this change relies on.
- **Any behavior or response-shape change** — outputs stay identical (except the
  now-deterministic, previously-arbitrary tie-break, which is pinned, not changed).
- **No schema change, no migration** — pure read-path refactor.
- **No new indexes, no query-planner tuning** beyond the batch reshape.

## Impact

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/services/offset_resumen_service.py` (new) | Added | Shared `fetch_resumenes_grupo` + `fetch_resumenes_individuales` + ordered `offset_con_limite` batch helper |
| `backend/app/api/endpoints/rentabilidad_dashboard.py` (L330) | Modified | In-loop `.first()` → prefetch + `dict.get` |
| `backend/app/api/endpoints/rentabilidad_tienda_nube.py` (L332, L416) | Modified | Both grupo + individual loops batched |
| `backend/app/api/endpoints/rentabilidad_fuera.py` (L385) | Modified | Grupo loop batched |
| `backend/app/api/endpoints/offsets_ganancia/_consumo_grupos.py` (L73, L385) | Modified | Both queries batched; `offset_con_limite` gains `ORDER BY id ASC` |
| `backend/app/api/endpoints/offsets_ganancia/_consumo_individual.py` (L426, L449) | Modified | Individual loop batched |
| `backend/tests/...` (new) | Added | Query-count assertions per endpoint + tie-break determinism test; reusable `count_queries` conftest fixture |
| Dashboard responses | No change | Byte-identical output for representative fixtures |
| End users | No change | Same dashboards, fewer DB round-trips per refresh |

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| **No existing test coverage** on these 5 endpoints — fixtures (offsets/grupos/resumenes) must be built from scratch, and getting them wrong could mask a regression. | High | Build multi-group fixtures deliberately (N>1 distinct groups); assert byte-identical responses AND bounded query count. In-memory SQLite `engine`/`db`/`client` conftest fixtures already exist and are compatible. Strict TDD: write red query-count tests first. |
| **Tie-break pinning** silently changes which `offset_con_limite` row wins for multi-limit groups. | Med | This is the one real behavior nuance and is **intentional**: today's tie-break is non-deterministic, so pinning to lowest-id cannot regress a guaranteed behavior. Locked by an explicit tie-case test asserting lowest-id selection. |
| A 1:1 lookup is actually 1:N for some site (batch dict would drop rows). | Low | Exploration verified `grupo_id`/`offset_id` uniqueness per resumen row for sites 1–4 and 6; only site 5's second query is 1:N and is handled by the ordered group-in-Python helper. |
| Query-count assertion too loose/tight and passes without proving O(1). | Low | Assert the resumen-query count is a small constant across **two** fixtures with different group counts (e.g. 2 vs 5 groups) so linear growth would fail. |

## Success Criteria

1. Each of the 6 sites issues a **bounded number of resumen queries** independent
   of group/offset count — proven by query-count assertions across fixtures with
   differing group counts.
2. Endpoint responses are **byte-identical** to pre-change output for
   representative multi-group fixtures.
3. The `offset_con_limite` batch is **deterministic** (`ORDER BY id ASC`), locked
   by a tie-case test with ≥2 limit-bearing offsets in one group.
4. New tests are green **and** the entire existing backend suite stays green
   (`cd backend && pytest tests/ -v --tb=short`).
5. The change stays a **single PR** within the ~150–250 line estimate.

## Approach — Rejected Alternatives

- **Patch each of the 6 sites independently with its own inline batch — REJECTED.**
  The `OffsetGrupoResumen`/`OffsetIndividualResumen` fetch-by-key shape is
  identical across 5 sites; inlining it 5 times would duplicate the exact pattern
  and invite future divergence. One shared helper is DRY and gives a single place
  to test the batch semantics.
- **Add caching (P-6) alongside the N+1 fix — REJECTED (out of scope by decision).**
  Caching introduces invalidation complexity (offset consumo changes on every sale
  sync) and would blur the "no behavior change" guarantee that makes this refactor
  safely reviewable. Deferred to a follow-up once metrics confirm it is still
  needed after the N+1 fix.
- **Change the `offset_con_limite` tie-break via a semantic ORDER BY (e.g. largest
  limit) — REJECTED.** The goal is to preserve current behavior, not redefine it.
  `ORDER BY id ASC` is the minimal determinism-pinning that matches "first row"
  semantics without introducing a new product decision about which limit wins.

## Delivery

- **Single PR** to `main`, estimated ~150–250 lines (one new helper module, 5
  touched endpoint files, one new test file + conftest fixture).
- Strict TDD is active: `cd backend && pytest tests/ -v --tb=short`. Write the
  query-count and tie-case tests **red first**, then apply the batch-prefetch fix
  to green.

## Next Phase

`sdd-spec` and `sdd-design` (can run in parallel). Spec formalizes the acceptance
criteria per site (bounded query count, byte-identical response, deterministic
tie-break) and the query-count test contract. Design pins the exact helper
signatures (`fetch_resumenes_grupo`, `fetch_resumenes_individuales`, the ordered
`offset_con_limite` batch), the `ORDER BY id ASC` placement, the per-site
collect-before-loop refactor shape, and the reusable `count_queries` conftest
fixture.

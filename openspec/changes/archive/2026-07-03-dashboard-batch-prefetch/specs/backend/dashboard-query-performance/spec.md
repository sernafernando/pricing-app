# Spec: backend/dashboard-query-performance

**Capability**: `backend/dashboard-query-performance`
**Status**: Active (canonical source of truth)
**Origen**: Batch-prefetch N+1 query sites in rentabilidad and offset dashboards (evaluacion-integral P-4)
**Última actualización**: 2026-07-03

> Batch-prefetch refactor: eliminates the per-group N+1 query pattern paid on every dashboard refresh across rentabilidad and offset-consumo endpoints. Replaces 11 in-loop `.first()` lookups with a shared batch-prefetch helper (`collect ids → one .in_() query → dict → in-loop lookup`). **No behavior change, no schema/migration, no response-shape change** — pure query-count reduction from O(distinct-groups) to O(1) per endpoint.

---

## Requirement 1: Query-count bound (O(1) resumen lookups per endpoint)

Each of the affected endpoints MUST issue a constant, small number of resumen/offset lookup queries for a given request, independent of the number of distinct groups or offsets in the response.

### Scenario: N=1 group produces the baseline query count

- **Given** a dashboard response containing exactly 1 distinct grupo (or offset, per endpoint)
- **When** the endpoint runs
- **Then** the number of `OffsetGrupoResumen` / `OffsetIndividualResumen` / `OffsetGanancia` (`offset_con_limite`) lookup queries issued is captured as the baseline count `C`

### Scenario: N=many groups produces the same query count as N=1

- **Given** the same endpoint, now returning a response with ≥5 distinct grupos/offsets (a value that would multiply the pre-change query count if the N+1 pattern were still present)
- **When** the endpoint runs
- **Then** the number of resumen/offset lookup queries issued equals the baseline count `C` from the N=1 scenario (not `C * N`)
- **And** `C` is a small fixed constant per endpoint (1 for endpoints with a single resumen type; 2 for `_consumo_grupos.py`, which fetches both `OffsetGrupoResumen` and `offset_con_limite` in separate bounded batches)

This applies independently to each of the 5 files; `_consumo_grupos.py` is tested for both of its lookup sites.

## Requirement 2: Behavior preservation (byte-identical responses)

For representative multi-group fixtures, each endpoint's JSON response body MUST be byte-identical before and after the change — same key order, same values, same null handling, no added/removed/reordered fields.

### Scenario: Identical response for a representative multi-group fixture

- **Given** a fixture with multiple distinct grupos/offsets, at least one of which has a matching resumen row and at least one of which has no matching resumen row (missing/None case)
- **When** the endpoint is called before the change (baseline capture) and again after the change is applied
- **Then** the two JSON response bodies are byte-identical (serialized form compared exactly, not just semantically equal)

This scenario is verified for each of the affected endpoint files.

## Requirement 3: Deterministic tie-break for `offset_con_limite` (intentional behavior change)

The `_consumo_grupos.py` and `_consumo_individual.py` `offset_con_limite` lookups (`OffsetGanancia` filtered by `grupo_id` plus a limit-not-null condition) are the only lookups that are not strict 1:1 key mappings. Their batch replacement MUST select, per `grupo_id`, the matching `OffsetGanancia` row with the lowest `id` — deterministically replacing today's unordered `.first()`.

### Scenario: Tie-break selects the lowest-id row

- **Given** a single grupo with two or more `OffsetGanancia` rows that each match the `offset_con_limite` filter (same `grupo_id`, each with `max_unidades` or `max_monto_usd` set)
- **When** the endpoint builds the batch of `offset_con_limite` results
- **Then** the row selected for that `grupo_id` is the one with the lowest `id` among the matching rows, regardless of DB row-return order

### Scenario: Single matching row is unaffected

- **Given** a grupo with exactly one matching `OffsetGanancia` row for `offset_con_limite`
- **When** the batch is built
- **Then** that row is selected (identical to pre-change `.first()` behavior, since there was no tie to break)

## Requirement 4: Shared helper contract

`fetch_resumenes_grupo(db, grupo_ids) -> dict[int, OffsetGrupoResumen]` and `fetch_resumenes_individuales(db, offset_ids) -> dict[int, OffsetIndividualResumen]` in `backend/app/services/offset_resumen_service.py` MUST satisfy:

### Scenario: Dict contains exactly the rows the old per-iteration lookup would have returned

- **Given** a list of `grupo_ids` (or `offset_ids`) where some ids have a matching resumen row and some do not
- **When** the helper is called once with the full id list
- **Then** the returned dict contains one entry per id that HAS a matching row, keyed by that id, with the same row object/values that `.filter(grupo_id == x).first()` would have returned for that id in the old code

### Scenario: Missing ids are absent, not raising

- **Given** a `grupo_id` (or `offset_id`) with no matching resumen row
- **When** the helper is called with that id included in the input list
- **Then** the id is simply absent from the returned dict — the helper does not raise, and does not insert `None` as a value

### Scenario: Helper is called exactly once per endpoint invocation

- **Given** any of the affected endpoint files using the helper for a given resumen type
- **When** the endpoint handles a single request
- **Then** `fetch_resumenes_grupo` (or `fetch_resumenes_individuales`) is invoked exactly once per resumen type needed by that endpoint, with ids collected from the full result set before the loop — never called inside the per-group/per-offset loop

## Requirement 5: Non-goals guard

The change MUST NOT introduce any of the following, even incidentally:

### Scenario: No caching introduced

- **Given** the completed change
- **When** the same endpoint is called twice in a row with the same parameters
- **Then** both calls issue their own DB queries (no in-memory or persistent cache layer is added; each request re-fetches fresh data)

### Scenario: No export endpoints touched

- **Given** the completed change
- **When** the diff is reviewed
- **Then** `productos_export.py` is not modified

### Scenario: No response-shape change

- **Given** the completed change
- **When** any of the affected endpoints' Pydantic response models are inspected
- **Then** no fields are added, removed, renamed, or reordered relative to pre-change models

### Scenario: No schema or migration change

- **Given** the completed change
- **When** the `alembic/versions/` directory and DB models are reviewed
- **Then** no new migration exists and no SQLAlchemy model column/table definitions are modified

---

## Implementation Details

**Affected sites (11 total across 5 files):**

1. `rentabilidad_dashboard.py:330` — `OffsetGrupoResumen` per grupo
2. `rentabilidad_dashboard.py:473` — `OffsetIndividualResumen` per offset
3. `rentabilidad_tienda_nube.py:332` — `OffsetGrupoResumen` per grupo
4. `rentabilidad_tienda_nube.py:416` — `OffsetIndividualResumen` per offset
5. `rentabilidad_fuera.py:385` — `OffsetGrupoResumen` per grupo
6. `rentabilidad_fuera.py:472` — `OffsetIndividualResumen` per offset
7. `offsets_ganancia/_consumo_grupos.py:73` — `OffsetGrupoResumen` per grupo
8. `offsets_ganancia/_consumo_grupos.py:385` — `OffsetGanancia` (`offset_con_limite`) per grupo (tie-break)
9. `offsets_ganancia/_consumo_individual.py:385/387–394` — `OffsetGrupoResumen` and `offset_limite` per grupo (second tie-break)
10. `offsets_ganancia/_consumo_individual.py:426` — `OffsetIndividualResumen` per offset
11. `offsets_ganancia/_consumo_individual.py:64` — `OffsetIndividualResumen` per offset (11th site, `obtener_resumen_offsets_individuales`)

**Shared helpers in `backend/app/services/offset_resumen_service.py`:**

- `fetch_resumenes_grupo(db, grupo_ids)` — batch-load by `grupo_id`
- `fetch_resumenes_individuales(db, offset_ids)` — batch-load by `offset_id`
- `fetch_offsets_limite_por_grupo(db, grupo_ids)` — batch-load with `ORDER BY id ASC` tie-break

**Decision:** `fetch_offsets_limite_por_grupo` adds `ORDER BY grupo_id, id ASC` and takes the first (lowest id) offset per group, pinning the previously non-deterministic tie-break to "lowest id wins" — a safe improvement that cannot regress guaranteed behavior (none exists for unordered `.first()`).

**No partial-deployment risk:** pure read-path refactor with no schema change. Rollback = revert the commit.

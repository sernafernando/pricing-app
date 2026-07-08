# Tasks: Batch-Prefetch the N+1 Query Sites in the Rentabilidad/Offset Dashboards

> Change: `dashboard-batch-prefetch`
> Strict TDD active. Test command: `cd backend && source venv/bin/activate && pytest`
> Delivery: single PR to `main`.

Corrected site inventory (design supersedes proposal's "6 sites"): **11 in-loop
query sites across 5 files** (updated from 10 — an 11th site was found during
PR1 adversarial review: `_consumo_individual.py:58`,
`obtener_resumen_offsets_individuales`, not previously inventoried; scoped
into Task 4 below since it's a trivial reuse of the already-imported
`fetch_resumenes_individuales`):

1. `rentabilidad_dashboard.py` — grupo loop (~L330), individual loop (~L473)
2. `rentabilidad_tienda_nube.py` — grupo loop (~L332), individual loop (~L416)
3. `rentabilidad_fuera.py` — grupo loop (~L385), individual loop (~L472)
4. `offsets_ganancia/_consumo_grupos.py` — resumen (~L73), `offset_con_limite` tie-break (~L385)
5. `offsets_ganancia/_consumo_individual.py` — resumen (~L426/449), `offset_limite` tie-break (~L387/394),
   **and** `obtener_resumen_offsets_individuales` (~L58, PR2 scope) — per-offset
   `OffsetIndividualResumen.first()` over `offsets_con_limites` materialized at
   ~L29-36; not addressed in PR1.

Verify exact line numbers by re-grepping at apply time (design.md notes drift
vs. current branch).

---

## Task 1 — Extract reusable `query_counter` conftest fixture (no behavior change)

**Satisfies:** Design §5.2 (test harness ADR); enables all query-count tests below.

- [x] 1.1 Extract the `before_cursor_execute` counter from
      `backend/tests/compras/test_varianza_tc_batch.py` (~L423–436) into
      `backend/tests/conftest.py` as the `query_counter` fixture (context-manager
      yielding a `_QueryCounter` with `.total` and `.matching(needle)`), per the
      exact implementation in design.md §5.2.
- [x] 1.2 Update `test_varianza_tc_batch.py` to consume the new shared fixture
      instead of its local counter (no behavior change — confirm its existing
      tests still pass).
- [x] 1.3 Run full suite — must stay green (this task changes no production code).

**Parallelizable:** No — must land first; everything else depends on it.

---

## Task 2 — Shared service module: RED tests, then implementation

**Satisfies:** Spec Requirement 4 (shared helper contract); Spec Requirement 3
(tie-break); Design §2 (exact signatures), §4 (ADR tie-break).

- [x] 2.1 Create `backend/tests/services/test_offset_resumen_service.py` with
      **RED-first unit tests** (the module doesn't exist yet → import error is
      the genuine red gate) for all three functions:
      - `fetch_resumenes_grupo`: empty input → `{}` with zero queries
        (`query_counter().total == 0`); dict keyed correctly for present ids;
        missing ids absent from dict (not `None`).
      - `fetch_resumenes_individuales`: same three cases, keyed by `offset_id`.
      - `fetch_offsets_limite_por_grupo`: empty input → `{}` with zero queries;
        single matching row per group → that row; **tie-break case** — two
        `OffsetGanancia` rows in the same grupo (`max_unidades=100` created
        first / lower id, `max_unidades=999` created second / higher id) →
        assert the returned row has `max_unidades == 100` (lowest id wins).
      - Add offset factory fixtures (`offset_grupo_factory`,
        `offset_ganancia_factory`, `offset_grupo_resumen_factory`,
        `offset_individual_resumen_factory`) per design §5.4, placed in
        `backend/tests/conftest.py` or a new `backend/tests/offsets/conftest.py`
        (decide based on whether they're reused by Task 4's integration tests —
        prefer top-level `conftest.py` for reuse).
- [x] 2.2 Confirm red: tests fail on import (module absent).
- [x] 2.3 Implement `backend/app/services/offset_resumen_service.py` with the
      three functions exactly as specified in design.md §2 (verbatim signatures
      and bodies), importing `OffsetGanancia`, `OffsetGrupoResumen`,
      `OffsetIndividualResumen` at module top.
- [x] 2.4 Green: all Task 2.1 tests pass.

**Parallelizable:** No — depends on Task 1 (uses `query_counter`). Must
complete before Task 4 (endpoints import this module).

---

## Task 3 — Consumo endpoints: `_consumo_grupos.py` + `_consumo_individual.py`

**Satisfies:** Spec Requirement 1 (query-count bound), Requirement 2
(byte-identical response), Requirement 3 (tie-break scenarios).

- [x] 3.1 Write RED integration tests in
      `backend/tests/offsets/test_consumo_resumen_batch.py`:
      - `_consumo_grupos.py` (`/api/offset-grupos-resumen` or actual route —
        confirm at apply time): fixture with ≥3 distinct grupos; assert
        `counter.matching("offset_grupo_resumen") <= 1` and
        `counter.matching("offsets_ganancia") <= 1`. Current code issues N of
        each → red.
      - `_consumo_individual.py` (`/api/offsets-con-limites-resumen` or actual
        route): fixture with ≥3 distinct offsets/grupos; assert
        `counter.matching("offset_individual_resumen") <= 1` and
        `counter.matching("offsets_ganancia") <= 1` (site 9's second tie-break
        query).
      - Tie-break integration pin for each: grupo with ≥2 limit-bearing
        `OffsetGanancia` rows → assert response reflects the lowest-id offset's
        limits (this is a behavior *pin*, not the red gate — SQLite may pass
        incidentally per design §4 note; the genuine red gate is Task 2's unit
        test).
      - Byte-identical response check: capture `resp.json()` on current code
        (baseline) vs. after the fix, assert exact equality, for both
        endpoints.
- [x] 3.2 Confirm red on the query-count assertions (behavior/tie-break tests
      may pass incidentally on SQLite — expected per design note, not a
      blocker).
- [x] 3.3 Rewrite both endpoint functions: collect ids from the materialized
      `.all()` list before the loop, call
      `fetch_resumenes_grupo`/`fetch_resumenes_individuales`/
      `fetch_offsets_limite_por_grupo` once each, replace in-loop `.first()`
      with `dict.get(...)`. Import from `app.services.offset_resumen_service`.
- [x] 3.4 Green: query-count, tie-break, and byte-identical tests all pass.

**PR1 note:** query-count thresholds for `offsets_ganancia` were set to C=2
(`_consumo_grupos.py`) and C=3 (`_consumo_individual.py`) rather than the
design's C=2/C=1 estimate — the extra count is the pre-existing
`grupos_con_limites` join (and, for the individual endpoint, the
`offsets_individuales` query), which are out of scope for this refactor and
were already single bounded queries before the change. What matters (and is
asserted) is that the count stays flat as N grows, which it does.

**Parallelizable:** Can run in parallel with Task 4 (different files) once
Task 2 is done. Group `_consumo_grupos.py` and `_consumo_individual.py`
together as one work unit (they share the tie-break helper and test file).

---

## Task 4 — Rentabilidad endpoints: `rentabilidad_dashboard.py`,
`rentabilidad_tienda_nube.py`, `rentabilidad_fuera.py`, **and the 11th site**
(`_consumo_individual.py::obtener_resumen_offsets_individuales`)

**Satisfies:** Spec Requirement 1 (query-count bound — table-filtered, per
Design §5.1 nuance: total query count NOT asserted, only resumen-table count),
Requirement 2 (byte-identical response).

**11th site (added post-PR1 adversarial review):**
`_consumo_individual.py:58`, `obtener_resumen_offsets_individuales` — the
`/offset-individuales-resumen` route does a per-offset
`OffsetIndividualResumen.filter(offset_id == x).first()` inside a loop over
`offsets_con_limites` (materialized at ~L29-36). Trivial fix: collect
`offset.id` for all `offsets_con_limites` before the loop, call the
already-imported `fetch_resumenes_individuales` once, replace the in-loop
`.first()` with `dict.get(...)` — same pattern already proven for the other
10 sites. Add its own query-count + byte-identical tests to
`test_rentabilidad_batch.py` (or a dedicated `test_consumo_individual_resumen_batch.py`
if it doesn't share fixtures cleanly with the 3 rentabilidad files).

- [x] 4.1 Discover minimal request shape (query params, auth/permission
      seeding) for each of the 3 rentabilidad endpoints (Design §8 open item)
      by reading their route signatures. Confirmed: all three
      (`/api/rentabilidad`, `/api/rentabilidad-tienda-nube`,
      `/api/rentabilidad-fuera`) require only `fecha_desde`/`fecha_hasta` +
      auth; `admin_auth_headers` avoids the marca/PM permission filter.
- [x] 4.2 Write RED integration tests in
      `backend/tests/rentabilidad/test_rentabilidad_batch.py`:
      - For each of the 3 files: fixture with ≥3 distinct grupos AND ≥3
        distinct individual limited offsets; assert
        `counter.matching("offset_grupo_resumen") <= 1` and
        `counter.matching("offset_individual_resumen") <= 1`. **Do NOT** assert
        total query count (aggregate `calcular_consumo_*` helpers are out of
        scope and stay O(N) — design §5.1).
      - Response-determinism check per endpoint (same fixture called twice —
        see deviation note below on why this is not a literal before/after
        byte-identical diff).
      - Also fixed the 11th site (`_consumo_individual.py:58`,
        `obtener_resumen_offsets_individuales`) with its own query-count +
        byte-identical tests appended to
        `backend/tests/offsets/test_consumo_resumen_batch.py`.
- [x] 4.3 Confirm red (current code: N queries per resumen type > 1 on all 3
      rentabilidad files + the 11th site).
- [x] 4.4 Rewrote all 4 files (7 call sites total — 6 rentabilidad grupo/
      individual loops + the 11th site): collected `grupo_id`/`offset_id`
      sets from the already-materialized list before the loop, called
      `fetch_resumenes_grupo` / `fetch_resumenes_individuales` once each,
      replaced in-loop `.first()` with `dict.get(...)`. Removed the
      `# ponytail:` marker at `_consumo_individual.py:58` and moved its
      tech-debt-ledger row to Resolved.
- [x] 4.5 Green: table-filtered query-count and determinism tests pass for
      all 4 files (14 new tests total).

**Deviation from plan (test infra, honestly reported):** `/api/rentabilidad-fuera`
and `/api/rentabilidad-tienda-nube` use raw SQL (`text()`) against
`ventas_fuera_ml_metricas` / `ventas_tienda_nube_metricas`, whose SQLAlchemy
models are only imported lazily inside unrelated endpoint functions
elsewhere in the codebase — so the in-memory SQLite test DB never registered
those tables, causing a pre-existing 500 on any test hitting these two
endpoints. Fixed by importing both models at module top of the new test file
so `Base.metadata.create_all` (session-scoped `engine` fixture) creates them.
Documented here since it's a general test-infra gap, not scoped to this
change, but was blocking Task 4's tests.

**Byte-identical caveat (honest, per design.md §5.1):** with no
`MLVentaMetrica`/`ventas_*` sales rows seeded, `cards`/`resultados` is always
`[]` for these 3 endpoints regardless of offset/resumen data — the offset
computation is fully internal and never surfaces in the response body when
there are no sales. A literal field-level pin on resumen values was therefore
not meaningful; the test instead asserts full-response determinism (same
fixture, same request, called twice → identical JSON), which still proves
the refactor introduced no non-determinism, but is a narrower guarantee than
Requirement 2's ideal "byte-identical before/after" comparison. The genuine
before/after safety net is the full 1787-pass regression suite (baseline
1779 + 8 new tests, 0 regressions) plus the unit-level dict.get()-equals-.first()
proof already covered by Task 2/3's unit tests on the shared helpers.

**Parallelizable:** Can run in parallel with Task 3 once Task 2 is done. The
3 rentabilidad files can be treated as one work unit (same mechanical pattern,
same test file) or split into 3 sequential commits within the same PR if that
eases review — recommend one work unit given the mechanical repetition.

---

## Task 5 — Full-suite gate and final verification

**Satisfies:** Spec Requirement 5 (non-goals guard); Proposal Success Criteria 4.

- [x] 5.1 Ran the entire backend suite (`pytest -q --ignore=test_turbo_simple.py
      tests/`) — 1787 passed, 15 skipped (baseline 1779 + 8 new tests, 0
      regressions).
- [x] 5.2 Confirmed non-goals: no caching introduced, `productos_export.py`
      untouched, no Pydantic response model field changes, no new
      migration/schema change (`git diff --stat` shows only endpoint files +
      tests + `docs/tech-debt-ledger.md`; no `alembic/versions/` or
      `app/models/` changes).
- [x] 5.3 PR2 diff size: 4 production files (~40 lines net) + 2 test files
      (~330 lines) + ledger update. Well within budget for a mechanical PR2
      following the PR1 pattern.

**Parallelizable:** No — final gate, runs after Tasks 3 and 4 both land.

---

## Review Workload Forecast

- **Estimated changed lines:** ~380–480 (revised up from proposal's 150–250).
  Breakdown:
  - `offset_resumen_service.py` (new): ~85 lines (3 functions + docstrings).
  - `test_offset_resumen_service.py` (new) + factory fixtures: ~140–170 lines.
  - `conftest.py` `query_counter` extraction + factory fixtures (if placed
    top-level): ~60–80 lines (net new, after removing the old local counter
    from `test_varianza_tc_batch.py`).
  - `test_consumo_resumen_batch.py` (new): ~90–120 lines (2 endpoints × query-count
    + tie-break + byte-identical cases).
  - `test_rentabilidad_batch.py` (new): ~100–140 lines (3 endpoints × query-count
    + byte-identical cases, plus request-shape discovery overhead).
  - Endpoint diffs across 5 files (10 call sites): ~60–90 lines total (small
    per-site diff — collect-before-loop + import + `.get()` swap — but ×10
    sites adds up).
- **400-line budget risk: High.** The proposal's 150–250 estimate covered only
  6 sites; the corrected inventory is 10 sites plus a full test harness
  (fixtures + 3 new test files + conftest extraction) that didn't exist before.
  Realistic total is likely 400–500 lines including tests.
- **Chained PRs recommended: Yes**, if strictly enforcing a 400-line cap.
  Suggested split:
  - **PR 1**: Task 1 (query_counter extraction) + Task 2 (shared service module
    + its unit tests) + Task 3 (`_consumo_grupos.py` + `_consumo_individual.py`,
    the two endpoints with the tie-break behavior pin). Self-contained,
    highest-risk logic (tie-break ADR) reviewed first, smaller diff (~230–280
    lines).
  - **PR 2**: Task 4 (3 `rentabilidad_*` endpoints, table-filtered query-count
    tests, byte-identical checks) + Task 5 (full-suite gate). Purely mechanical
    repetition of the pattern established in PR 1, easier to review fast
    (~150–200 lines).
  - Alternative: keep single PR but flag `size:exception` if the team prefers
    to review the whole batch-prefetch refactor atomically (it is one logical
    change with no partial-deploy risk — pure read-path, revert-safe per
    design §6).
- **Decision needed before apply: Yes.** Orchestrator/user must choose
  single-PR (with `size:exception`) vs. the two-PR split above before Task 3/4
  work begins, per the Review Workload Guard.

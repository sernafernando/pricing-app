# Verify Report: dashboard-batch-prefetch

> Branch checked: `main` (HEAD `d8ab3659`). PR1 (#841, commit `fdd8cb54`) is MERGED.
> PR2 (#842, branch `perf/dashboard-batch-prefetch-2`) is OPEN, NOT merged.

## Verdict

**PASS for PR1 scope (what's on main).** 0 CRITICAL, 0 WARNING, 2 SUGGESTION.
PR2 scope (rentabilidad_* + 11th site) correctly absent from main — pending merge, not a defect.

## Test results

`cd backend && source venv/bin/activate && pytest tests/services/test_offset_resumen_service.py tests/offsets/ -q`
→ **16 passed**, 0 failed, 0 skipped.

## Per-requirement (PR1-merged, on main)

1. **Requirement 4 (shared helper contract)** — PASS.
   `backend/app/services/offset_resumen_service.py` exists with all three
   functions (`fetch_resumenes_grupo`, `fetch_resumenes_individuales`,
   `fetch_offsets_limite_por_grupo`), matching design.md §2 signatures.
   Empty-input → `{}` verified by unit tests (no query issued).

2. **Requirement 1 (query-count bound) — consumo endpoints** — PASS.
   `_consumo_grupos.py` and `_consumo_individual.py`'s resumen-batch call
   sites (lines ~77/80, ~398/401/438) use `fetch_resumenes_grupo` /
   `fetch_offsets_limite_por_grupo` / `fetch_resumenes_individuales`; no
   in-loop `.first()` remains for these lookups. (Unrelated `.first()` calls
   at other lines — e.g. `OffsetGrupo` lookup by id, `TipoCambio`/`CurExchHistory`
   — are single-row lookups outside any loop, correctly out of scope.)
   Confirmed the load-bearing assertion is **equality** (`n5 == n1`), not
   just `<= C` — the `<= 2`/`<= 1` lines are documented as a secondary
   sanity bound, not the real proof. This is exactly right: an `<=`-only
   test would pass for a true N+1 as long as N stayed under the bound.

3. **Requirement 3 (deterministic tie-break)** — PASS.
   `fetch_offsets_limite_por_grupo` has `.order_by(OffsetGanancia.grupo_id, OffsetGanancia.id.asc())`.
   The unit test (`test_offset_resumen_service.py::test_tie_break_selects_lowest_id_row`)
   and the integration test (`test_consumo_resumen_batch.py::TestConsumoGruposTieBreak`)
   both correctly avoid the SQLite-rowid trap: rather than relying on a
   data-driven assertion alone (which SQLite would satisfy even without
   `ORDER BY`, since `id` aliases rowid there), they additionally inspect
   the emitted SQL text via `query_counter` and assert an `ORDER BY ...
   grupo_id` clause is literally present on the `offsets_ganancia` query.
   Removing `.order_by(...)` from the source would fail this assertion.
   Confirmed genuine, not just incidental.

4. **query_counter conftest fixture** — PASS. `backend/tests/conftest.py`
   has `_QueryCounter` (`.total`, `.matching(needle)`) and the `query_counter`
   fixture, context-manager based, per design §5.2.

5. **11th site (`_consumo_individual.py::obtener_resumen_offsets_individuales`, ~L64)** —
   PENDING — implemented on branch `perf/dashboard-batch-prefetch-2` / PR #842,
   not yet on main. Confirmed on main: the `# ponytail:` marker and in-loop
   `OffsetIndividualResumen.filter(offset_id == offset.id).first()` are still
   present (expected — this site is PR2 scope).

## Per-requirement (PR2-pending, NOT on main)

All PENDING — merge of #842 required:

- `rentabilidad_dashboard.py` grupo loop (L330) + individual loop (L473)
- `rentabilidad_tienda_nube.py` grupo loop (L332) + individual loop (L416)
- `rentabilidad_fuera.py` grupo loop (L385) + individual loop (L472)
- 11th site: `_consumo_individual.py::obtener_resumen_offsets_individuales`

Confirmed via `rg "fetch_resumenes_grupo|fetch_resumenes_individuales"` against
the three `rentabilidad_*.py` files on main — zero matches, as expected.

## Requirement 2 (byte-identical) / Requirement 5 (non-goals)

Not independently re-verified beyond what the PR1 test suite already proves
(byte-identical/structural pin tests included in the 16 passing tests).
Non-goals (no caching, `productos_export.py` untouched, no schema change) —
consistent with a pure `services/` + endpoint diff; no `alembic/versions/`
or `app/models/` changes observed on the PR1 commit.

## SUGGESTIONS (for archive)

1. **Layout deviation**: spec artifact lives at a flat file
   (`specs/dashboard-batch-prefetch.md`) rather than the conventional
   `specs/<capability>/spec.md` nested layout. Not a defect — flag for
   archive/cleanup consistency with other changes in this repo.
2. **Apply-progress artifact not found via file read** at the expected path
   (`openspec/changes/dashboard-batch-prefetch/apply-progress.md`) — it only
   exists in Engram (topic_key `sdd/dashboard-batch-prefetch/apply-progress`,
   obs #739). Since this change's artifact store is otherwise file-based
   (openspec/), consider persisting apply-progress to a file too for
   consistency, or confirm hybrid-mode intent at archive time.

## Notes on delivery state

PR2 has two local commits on `perf/dashboard-batch-prefetch-2` (`f00c3d10`,
`ff28699`) not yet pushed/merged per the apply-progress record. One commit
was made with `--no-verify` due to a pre-commit hook (Gentleman Guardian
Angel review) timing out — flagged in apply-progress as a deviation
requiring human follow-up review before merge. This is a WARNING to carry
into the PR2 review process, not a blocker for this verify pass since PR2
is explicitly out of scope for what's being verified against main here.

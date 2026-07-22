# Proposal: MLQuestions Resizable Columns via TanStack Table (Preguntas first)

> Phase: propose · Store: hybrid (openspec + Engram `sdd/ml-bot-resizable-columns-tanstack/proposal`) · Date: 2026-07-22

## Intent

Operators need to widen/narrow MLQuestions table columns to read long ML question/answer text. A hand-rolled fixed-width-sum resizer was attempted 4× and reverted (#956): its fixed model clipped the variable-width **Acciones** column (up to 5 conditional buttons) and drag was buggy. Redo it RIGHT using `@tanstack/react-table` v8's battle-tested headless column-sizing engine — the exact narrow piece that kept breaking — while leaving every already-working custom body render (expandable detail, buyer-history spoiler, thread grouping, action buttons) untouched. Base is clean (plain auto-layout tables).

## Scope

### In Scope
- **Preguntas table ONLY** (PR1): user-resizable columns via TanStack's sizing engine.
- One `useReactTable` instance for `columnSizing` state + `header.getResizeHandler()` + `column.getSize()`/`table.getTotalSize()`; `columnResizeMode: 'onChange'`.
- Apply widths via `<colgroup><col width=getSize()>` + `<table>` width = `getTotalSize()`, under `table-layout: fixed`; long content truncates.
- **Acciones**: explicit generous `minSize` + default sized for up to 5 buttons (the #956 failure mode). Fixed columns get fixed sizes; text columns (Pregunta/Item/Respuesta) resizable min/max.
- Persist `columnSizing` per table in localStorage (per-table key), fail-safe (corrupt/absent → defaults, never throw). Reset-to-default affordance.
- Reconcile with the #925 notebook-fit clamp caps (coexist or supersede — spelled out in design).

### Out of Scope (explicit follow-ups / non-goals)
- Historial/detalle table and Mensajes table (each a separate later change, after Preguntas verified in a real browser).
- TanStack row model / `flexRender` / `getRowModel` for the body — body JSX stays hand-rendered.
- Column reordering, hiding, sorting, server/cross-device persistence.
- Any change to shared `table-tesla.css`; any backend change.

## Capabilities

### New Capabilities
- `mlquestions-resizable-columns`: user-resizable, persisted column widths for the MLQuestions Preguntas table using TanStack's column-sizing engine, with an Acciones min-width guard and fail-safe localStorage persistence.

### Modified Capabilities
- None (no existing OpenSpec capability specs for this page today).

## Approach

Adopt TanStack **minimally** — sizing engine only. For the Preguntas table define a `columns` array carrying `id`/`size`/`minSize`/`maxSize`, call `useReactTable({ columns, data: [], columnResizeMode: 'onChange', state: { columnSizing }, onColumnSizingChange })`. Consume only `getHeaderGroups()` (for `<th>` labels + resize grips) and `getTotalSize()`/`column.getSize()` (for `<colgroup>`/table width). Keep `data: []` — body is still the existing hand-rolled `.map()` with `Fragment` + conditional `renderDetailRow`, so the fragile-but-working expand/spoiler/action code is not re-touched.

**Rationale — three options weighed** (per exploration):
- *TanStack sizing engine only (chosen)*: TanStack owns exactly the math + drag lifecycle that broke 4×; zero risk to expand/thread/action JSX; small diff; per-table localStorage trivial. Slightly unusual usage (columns without row model) — documented inline.
- *Full TanStack row model / flexRender (rejected)*: idiomatic but rewrites every stable render branch (detail tabs, colSpan thread headers, nested Historial) — high regression risk, no proportional benefit; violates "boring tech, no over-engineering".
- *Rebuild the hand-rolled resizer (rejected)*: already failed 4×; that math/drag is precisely what a library should own.

## Business Rules & Edge Cases

- **Acciones min-width is a MUST, not nice-to-have** — verify against max simultaneous buttons (expand chevron + TakeOver/Editar/PublicarAhora/Retener); this is the literal #956 failure.
- **Long content truncates** under `table-layout: fixed` (title-attr tooltips already present stay intact).
- **Cold start / corrupt localStorage** → fall back to defaults, never throw; mirrors `LlmProviderRosterEditor` try/catch pattern in this same file.
- **Stale/unknown column ids** in persisted state → ignore (fail open), never crash if the column set later changes.
- **Reset affordance** restores defaults and clears the persisted key.
- **`<colgroup>` + `colSpan` coexistence** (relevant to future Mensajes work) must be confirmed visually, not assumed.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `frontend/src/pages/MLQuestions.jsx` | Modified | Preguntas table: `columns` def, `useReactTable`, `<colgroup>`, `<th>` resize grips, table inline width, localStorage persist/reset |
| `frontend/src/pages/MLQuestions.module.css` | Modified | Resize-grip styling, `table-layout: fixed` + truncation for the Preguntas table scope only |
| `frontend/src/styles/table-tesla.css` | Read-only check | Confirm residual specificity from reverted #956 (commits 48bb5839/51e9b971, still on branch) doesn't conflict with `<colgroup>` — no edit intended |
| Backend | None | Purely frontend/UI |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Acciones column clips again (the 4× failure) | Med | Hard `minSize` sized to max buttons; mandatory real-browser check with all-buttons status |
| jsdom hides the layout bug (as it did 4×) | High | jsdom explicitly insufficient — HARD gate: headless-Chromium with realistic LONG content before "done" |
| First real in-repo TanStack usage — no local pattern to copy | Med | Minimal surface (sizing only); documented inline; establishes the reusable pattern for follow-ups |
| Residual fixed-width CSS from reverted #956 conflicts with colgroup | Med | Read `table-tesla.css` current state before applying; no shared-CSS edit |
| Expand/tab/history state (`expandedId`/`expandedTab`/`historyLoading`) regresses | Med | Body JSX untouched; manual regression check: toggle expand + tab-switch + spoiler open post-change |

## Rollback Plan

Entirely additive to ONE table in ONE file (plus scoped CSS). Single revert of the PR restores the clean plain auto-layout Preguntas table; no shared CSS, no backend, no data migration, no cross-PR coupling. Corrupt persisted state is self-healing (fail-safe to defaults) even without a revert.

## Success Criteria

- [ ] Dragging a Preguntas column header visibly resizes it (real headless-Chromium, realistic long ML titles/answers).
- [ ] Acciones column keeps all applicable buttons usable at its min width across statuses — no clipping.
- [ ] Detail/Historial spoilers still open and tab-switch after resize.
- [ ] Widths persist across reload per table; corrupt/absent localStorage → defaults, never throws.
- [ ] Reset-to-default restores defaults and clears the key.
- [ ] Coexistence with #925 notebook-fit clamp is explicit and correct.
- [ ] No shared `table-tesla.css` edit; no backend change.

## Verification Gate (mandatory)

**jsdom is explicitly insufficient** — it hid this bug all 4 prior times. The change is NOT done until real headless-Chromium, loaded with realistic LONG content (long question text, long buyer nicknames, all-buttons-visible status), confirms: (1) dragging visibly resizes, (2) action buttons stay usable, (3) detail/history spoilers still open. This is a blocking gate, above and beyond vitest/jsdom unit coverage.

## Review Workload Forecast

- **PR1 (Preguntas only):** single-file JSX + scoped CSS, estimated well under the 400-line budget.
- **Chained PRs recommended: Yes** — Historial and Mensajes are separate later slices, not bundled (keeps reviewer diff small given the 4-failure history).
- **Decision needed before apply: No** (scope already sliced to Preguntas-first).

## Dependencies

- `@tanstack/react-table` v8.21.3 — ALREADY installed (package.json + lockfile). No new install; this is its first application-code usage.

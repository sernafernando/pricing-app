# Tasks: MLQuestions Resizable Columns via TanStack Table (Preguntas) — PR1

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~180-260 (1 JSX file + 1 CSS file + tests) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Preguntas table resizable/persisted columns (JSX+CSS+tests) | PR 1 | `npm run test -- MLQuestions` (frontend) | `chromium --headless=new` driven-page harness against dev build, long content + `taken_over` row | Revert `MLQuestions.jsx`/`.module.css` diff; no migration, no other files touched |

## Locked Sizing (overrides design's 1105px default — notebook-fit ~1024px)

`pregunta:141 (min120/max600) · item:100 (min100/max400) · estado:120 (fixed) · respuesta:118 (min100/max600) · confianza:90 (fixed) · cuentaRegresiva:175 (fixed) · acciones:280 (fixed min=max=280)` → sum **1024px**.

## Pre-flight

- [x] 0.1 Confirm PR #956 revert is merged to `main`; branch this change off updated `main` (clean base, no residual resizer code).

## Phase 1: Columns Definition + Sizing Hook (RED tests first)

- [x] 1.1 RED: vitest for `loadColumnSizing`/`saveColumnSizing` — absent key → `{}`; corrupt JSON → `{}` (no throw); valid JSON round-trips; unknown column id ignored on load; reset clears key.
- [x] 1.2 GREEN: implement `loadColumnSizing(key)`/`saveColumnSizing(state, key)` in `frontend/src/pages/MLQuestions.jsx` per design (try/catch, `KEY='mlq:colsizing:preguntas'`).
- [x] 1.3 Define `columns` array (7 ids) with locked sizes above; `enableResizing:false` for estado/confianza/cuentaRegresiva/acciones; acciones `minSize=maxSize=size=280`.
- [x] 1.4 Wire `useReactTable({ columns, data: [], columnResizeMode: 'onChange', getCoreRowModel(), state:{columnSizing}, onColumnSizingChange })`; `useState(() => loadColumnSizing())`; debounced (~200ms) save on change.
- [x] 1.5 Add reset control (button) calling `setColumnSizing({}); localStorage.removeItem(KEY)`.

## Phase 2: JSX Wiring (body untouched)

- [x] 2.1 Import `flexRender` from `@tanstack/react-table`.
- [x] 2.2 Render `<table style={{width: table.getTotalSize()}} className="table-tesla striped ${styles.resizableTable}">`.
- [x] 2.3 Render `<colgroup>` with one `<col style={{width: col.getSize()}}>` per `getVisibleLeafColumns()`.
- [x] 2.4 Render `<thead>` from `getFlatHeaders()`; add resize grip (`span role="separator" aria-orientation="vertical" aria-label`) on `getCanResize()` headers only, wired to `getResizeHandler()` on mouseDown/touchStart.
- [x] 2.5 Leave existing `<tbody>` `.map()`/`Fragment`/`renderDetailRow` and `<td colSpan={7}>` completely unchanged.
- [x] 2.6 RED→GREEN vitest (RTL): renders 3 `role="separator"` grips (pregunta/item/respuesta only), 4 fixed headers have none, one `<col>` per header, reset control present.

## Phase 3: CSS (scoped, `MLQuestions.module.css`)

- [x] 3.1 Add `.resizableTable { table-layout: fixed }` scoped class (not `table-tesla.css`).
- [x] 3.2 Add `.resizeGrip`/`.resizeGripActive` (design tokens, `cursor: col-resize`, `touch-action: none`, visible on hover/active/focus); `th { position: relative }`.
- [x] 3.3 Verify existing `.cellQuestion/.cellItem/.cellAnswer` truncation (overflow/ellipsis/nowrap, `title` attr) still applies under fixed layout; note #925 clamp caps become inert for this table only (leave untouched, other tables still use them).

## Phase 4: Mandatory Headless-Chromium Verification (BLOCKING GATE)

- [ ] 4.1 Build/serve a page rendering the Preguntas table with realistic LONG content (long pregunta/item/respuesta text, long nickname) and a `taken_over` row (all 4 buttons + chevron).
- [ ] 4.2 Using `chromium --headless=new` driven-page harness (this session's measurement pattern): drag the Pregunta header resize grip; assert rendered `<col>`/`<th>` width changes to match drag delta.
- [ ] 4.3 Assert `actionsCell.scrollWidth <= renderedAccionesColWidth` (no clipping) for `taken_over`, `waiting`, `received`, `pending_morning`, `failed` statuses.
- [ ] 4.4 Assert chevron expand opens detail row, "Historial del comprador" spoiler opens, and detail-tab switching still works after a resize.
- [ ] 4.5 Assert persistence: resize a column, reload the driven page, assert the column renders at the saved width.
- [ ] 4.6 Document pass/fail evidence for all of 4.2–4.5 in the PR description; this task is NOT satisfied by vitest alone.

## Phase 5: Cleanup

- [ ] 5.1 Re-confirm `frontend/src/styles/table-tesla.css` untouched (read-only per design).
- [ ] 5.2 Remove any temporary debug harness files used only for Phase 4 (keep the harness pattern documented, not committed, unless project convention keeps E2E scripts in-repo).

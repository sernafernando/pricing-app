# Tasks: ml-bot-resizable-columns

Locked decision overriding design's open question: in **Mensajes**, resizable columns are **BOTH "Mensaje" AND "Comprador·Pack"** (design's Mensaje-only default is superseded).

Strict TDD is ON: tests for the hook are written/updated before (or alongside, RED-first) the corresponding implementation. Test runner: `pnpm run test` (vitest + RTL) from `frontend/`.

Scope fence: only `frontend/src/hooks/useResizableColumns.js` (+ its test file), `frontend/src/pages/MLQuestions.jsx`, `frontend/src/pages/MLQuestions.module.css`. No edits to `frontend/src/styles/table-tesla.css`, no backend, no new npm dependency.

## 1. Hook tests (RED) — sequential, must land first
**Satisfies**: Spec req 1 (drag), 2 (keyboard), 3 (persistence), 5 (reset), 8 (fallback); Design "Hook Interface" + "Testing" sections.
- [x] 1.1 Create `frontend/src/hooks/useResizableColumns.test.js` with failing specs (renderHook/act) for:
  - init with no storage → `colWidth(id)` undefined for all cols, `isResized(id)` false
  - keyboard Arrow Right/Left steps ±16px (Shift ×4 = ±64px) from `defaultWidth` baseline, clamped to `[min,max]`
  - Home/End jump to `min`/`max`
  - persistence round-trip: resize via keyboard → unmount → remount same `storageKey` → width restored
  - `resetWidths()` clears in-memory overrides AND removes the localStorage key; subsequent remount starts clean
  - corrupt localStorage value (invalid JSON) → hook falls back to defaults, does not throw
  - out-of-range persisted value (below min / above max) → re-clamped on load
  - localStorage disabled/throwing (e.g. private mode `setItem` throws) → live in-memory resize still works, no throw
  - `getHandleProps(id)` returns `role="separator"`, `aria-orientation="vertical"`, `aria-label` containing the column label, `tabIndex=0`
  - Done when: `pnpm run test -- useResizableColumns` fails only on missing implementation (RED confirmed, not on test syntax/setup errors).

## 2. Hook implementation (GREEN) — sequential, depends on 1.1
**Satisfies**: Spec reqs 1, 2, 3, 5, 8; Design "Hook Interface" + "Persistence" sections.
- [x] 2.1 Create `frontend/src/hooks/useResizableColumns.js` implementing `useResizableColumns({ storageKey, columns })`:
  - lazy init: read `localStorage[storageKey]`, `JSON.parse` in try/catch, keep only finite numeric values re-clamped to each column's `[min,max]`; any failure → `{}`
  - returns `colWidth(id)`, `isResized(id)`, `getHandleProps(id)`, `resetWidths()`
  - drag: `onMouseDown` records `startX` + baseline (`closest('th').offsetWidth || defaultWidth`), attaches `document` `mousemove`/`mouseup` listeners (refs, cleaned up in `useEffect` return + on unmount), live clamped width update, single localStorage write on `mouseup`
  - keyboard: ArrowLeft/ArrowRight ±16px (Shift ×4), Home/End → min/max, debounced (300ms) localStorage write
  - all `localStorage.setItem` calls wrapped in try/catch, swallow errors silently (spec req 8)
  - `resetWidths()` clears state map + `localStorage.removeItem(storageKey)`
  - Done when: all tests from 1.1 pass (`pnpm run test -- useResizableColumns` green), no lint errors, no new dependency added.

## 3. MLQuestions.module.css scoped layout changes
**Satisfies**: Spec reqs 4 (clamp coexistence), 6 (ellipsis), 7 (guaranteed horizontal scroll); Design "Key Decisions" 1–3.
- [ ] 3.1 Add `.container :global(.table-tesla) { table-layout: fixed; width: max-content; min-width: 100%; }` (page-scoped override, no edits to shared `table-tesla.css`).
- [ ] 3.2 Add `.container :global(.table-container-tesla) { overflow-x: auto; }` — confirm existing scrollbar styling is reused, not duplicated; verify sticky thead still works with horizontal scroll (visual/manual, see section 6).
- [ ] 3.3 Move current `max-width: clamp(...)` rules for resizable columns off cell classes (`.cellQuestion`, `.cellItem`, `.cellAnswer`, etc.) onto new `<col>`-targeting classes (e.g. `.colQuestion`, `.colItem`, `.colAnswer`, `.colMensaje`, `.colComprador`) using `width: clamp(...)` instead of `max-width`.
- [ ] 3.4 Keep `overflow: hidden; text-overflow: ellipsis; white-space: nowrap;` on the existing cell classes (still needed for ellipsis under fixed layout even though `max-width` there is now inert).
- [ ] 3.5 Add handle styles: absolutely positioned `right:0; top:0; bottom:0; width:6px; cursor:col-resize;` inside a scoped `th { position: relative; }` rule for resizable headers.
- [ ] 3.6 Add focus-ring style for the handle: `box-shadow: 0 0 0 2px var(--brand-primary-light);` (design token, no hardcoded color) on `:focus-visible`.
- [ ] 3.7 Add static `<col>` width classes for fixed/non-resizable columns (Estado, Confianza, Cuenta regresiva, Acciones, Recibido, Leído, Moderación, Fecha, thin indent col in Mensajes) so table-layout:fixed has explicit widths for every column.
- Done when: `pnpm run build` (or dev server) shows no CSS errors, and visually the three tables render with fixed layout, working ellipsis, and no changes made to `frontend/src/styles/table-tesla.css`.

## 4. Wire Preguntas table in MLQuestions.jsx
**Satisfies**: Spec reqs 1–8 for the Preguntas table; Design "File Changes" + "Resizable cols" mapping.
- [ ] 4.1 Instantiate `useResizableColumns({ storageKey: 'mlbot:colwidths:preguntas', columns: [...] })` with resizable Pregunta/Item/Respuesta(borrador) and fixed Estado/Confianza/Cuenta regresiva/Acciones.
- [ ] 4.2 Add `<colgroup>` with one `<col>` per column; resizable cols get inline `style={{ width: colWidth(id) }}` when `isResized(id)` (falls through to `.colX` CSS class default otherwise); fixed cols use static width classes from 3.7.
- [ ] 4.3 Add a resize handle element inside each resizable `<th>`, spread `getHandleProps(id)` onto it.
- [ ] 4.4 Add a "Restablecer columnas" ghost button (btn-tesla sm) near the Preguntas table header, visible only when `isResized` is true for at least one column of this table; `onClick` calls `resetWidths()`.
- Done when: Preguntas tab renders with drag+keyboard resizing on Pregunta/Item/Respuesta, reset button appears only after a resize, and existing Preguntas behavior (sorting/filtering/pagination) is unaffected.

## 5. Wire Mensajes table in MLQuestions.jsx (LOCKED: Mensaje + Comprador·Pack both resizable)
**Satisfies**: Spec reqs 1–8 for the Mensajes table; overrides design's Mensaje-only default per explicit product decision.
- [ ] 5.1 Instantiate `useResizableColumns({ storageKey: 'mlbot:colwidths:mensajes', columns: [...] })` with resizable **Mensaje** and **Comprador·Pack**; fixed Recibido/Leído/Moderación (and the thin indent column, if present, stays fixed).
- [ ] 5.2 Add `<colgroup>` per 4.2 pattern, now with two resizable `<col>`s (Mensaje, Comprador·Pack).
- [ ] 5.3 Add resize handles + `getHandleProps(id)` to both the "Mensaje" and "Comprador·Pack" `<th>`s.
- [ ] 5.4 Add reset button for the Mensajes table (independent from Preguntas/Detalle, own storage key).
- Done when: both Mensaje and Comprador·Pack columns are independently draggable/keyboard-resizable, persist independently, reset together via the Mensajes reset button, and Preguntas/Detalle widths are unaffected (independent storage keys, spec req 3).

## 6. Wire Detalle/historial table in MLQuestions.jsx
**Satisfies**: Spec reqs 1–8 for the Detalle table.
- [ ] 6.1 Instantiate `useResizableColumns({ storageKey: 'mlbot:colwidths:detalle', columns: [...] })` with resizable Pregunta/Item/Respuesta; fixed Fecha/Estado.
- [ ] 6.2 Add `<colgroup>`, handles, `getHandleProps` per the same pattern as 4.2–4.3.
- [ ] 6.3 Add reset button scoped to the Detalle table.
- Done when: Detalle/historial view (modal or expanded row, whichever the current implementation uses) resizes/persists/resets independently of the other two tables.

## 7. Manual/browser verification (cannot be exercised in jsdom)
**Satisfies**: Spec reqs 4 (clamp/1440px breakpoint), 7 (guaranteed horizontal scroll with sticky thead), drag pixel math.
- [ ] 7.1 In a real browser (dev server), for each of the 3 tables: drag a resizable column narrower/wider, confirm live width update and min/max clamping at drag boundaries.
- [ ] 7.2 Resize a column past total container width; confirm `.table-container-tesla` shows a horizontal scrollbar, scrolling reaches the widened column, and the sticky thead scrolls horizontally in lockstep with tbody (no visual desync).
- [ ] 7.3 Resize the browser to below and above the 1440px breakpoint; confirm untouched columns still follow `clamp()` responsive defaults while a resized column keeps its explicit override width.
- [ ] 7.4 Reload the page after resizing; confirm widths persist per table, and confirm resizing one table (e.g. Mensajes) does not affect the other two's stored widths.
- [ ] 7.5 Click "Restablecer columnas" on each table; confirm it reverts only that table to clamp() defaults and clears only its own localStorage key.
- [ ] 7.6 With devtools localStorage disabled or manually corrupted (set the key to `"not json"`), reload and confirm the page still renders with default widths (no console throw), and live resize (in-memory) still works during that session.
- Done when: all 6 checks above pass manually and are noted as verified in the PR description (this task list does not gate merge on automated coverage for pixel/visual behavior, per design's stated jsdom limitation).

---

## Parallelization notes
- Section 1 (tests) → Section 2 (hook impl): strictly sequential (TDD RED→GREEN).
- Section 3 (CSS) can proceed in parallel with sections 1–2 (independent files), but sections 4–6 depend on both 2 (hook) and 3 (CSS classes) being done.
- Sections 4, 5, 6 (wiring the three tables) touch the same two files (`MLQuestions.jsx`, `MLQuestions.module.css`) — treat as sequential within one PR/commit sequence to avoid merge conflicts, even though they are logically independent per-table.
- Section 7 (manual verification) is sequential, last, after 4–6 land.

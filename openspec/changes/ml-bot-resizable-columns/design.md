# Design: ML-Bot Resizable Table Columns

## Technical Approach

A page-scoped custom hook `useResizableColumns` manages a per-table `{colId: px}`
override map, persisted to localStorage. Each table renders a `<colgroup>`; a
drag/keyboard handle sits on the right edge of resizable `<th>`s. All layout CSS
(`table-layout: fixed`, `<col>` defaults, handle, focus ring, guaranteed scroll)
lives in `MLQuestions.module.css`, scoped via `.container :global(...)`. Shared
`table-tesla.css` is NOT touched. React 18 hooks only, no new deps. Three hook
instances (Preguntas / Mensajes / Detalle), three independent storage keys.

## Architecture Decisions

### Decision: Column width source under `table-layout: fixed`
**Choice**: Move the responsive clamp() off cell `max-width` onto the `<col>`
`width`. Un-resized columns get a CSS class (`col.colText { width: clamp(...) }`);
resized columns get inline `style={{ width: Npx }}` on the `<col>` which
out-specifies the class. Fixed (badge/action) columns get a static `<col>` width.
**Alternatives considered**: Keep clamp on cell `max-width` (ignored under fixed
layout — breaks responsiveness); write width to first-row `<td>` (fragile with
multi-tbody Mensajes / colSpan rows).
**Rationale**: Under `table-layout: fixed` only `<col>`/first-row `width` sets
column size — cell `max-width` is ignored. Putting clamp() on `col.width` keeps
the exact responsive default while inline `<col>` width cleanly overrides ONLY
dragged columns. Inline style is the sanctioned dynamic-value exception.

### Decision: Guaranteed horizontal scrollbar
**Choice**: Page-scoped `.container :global(.table-tesla){ table-layout: fixed;
width: max-content; min-width: 100% }` + `.container :global(.table-container-tesla){
overflow-x: auto }`. `width:max-content` sizes the table to the sum of `<col>`
widths; `min-width:100%` still fills the container when columns are narrow. When
the sum exceeds the container the table overflows and the container's existing
8px webkit scrollbar shows.
**Alternatives considered**: `overflow-x: scroll` (always-visible track, noisy);
editing shared `table-tesla.css` `width:100%` (blast radius — forbidden).
**Rationale**: `auto` keeps the clean look when it fits and a usable scrollbar
when it doesn't. Sticky thead is unaffected (sticky is vertical; horizontal
scroll moves head+body together).

### Decision: Ellipsis under fixed layout
**Choice**: Keep `overflow:hidden; text-overflow:ellipsis; white-space:nowrap` on
`.cellQuestion/.cellAnswer/.cellItem`; `max-width` becomes inert but harmless.
Column width now comes from `<col>`, cells clip to it → ellipsis still truncates.
**Rationale**: Fixed layout enforces the col width on the td; the existing three
overflow properties are exactly what ellipsis needs. No new CSS required beyond
verification.

## Hook Interface

`useResizableColumns({ storageKey, columns })`
- `columns`: `[{ id, label, resizable, min, max, defaultWidth }]`. `defaultWidth`
  is the drag/keyboard baseline used only when live `th.offsetWidth` is 0
  (also makes tests deterministic).
- Returns: `colWidth(id)→px|undefined`, `isResized(id)→bool`,
  `getHandleProps(id)`, `resetWidths()`.
- `getHandleProps` yields `{ role:'separator', 'aria-orientation':'vertical',
  'aria-label':`Redimensionar columna ${label}`, tabIndex:0, onMouseDown,
  onKeyDown, className }`.

Drag: `onMouseDown` records `startX` + baseline (`closest('th').offsetWidth ||
defaultWidth`), attaches `document` `mousemove`/`mouseup`; `mousemove` sets
`clamp(base+dx, min, max)` live; `mouseup` removes listeners + one localStorage
write. Listeners stored in refs; `useEffect` cleanup removes them on unmount.
Keyboard: Arrow Left/Right = ±step (16px; Shift ×4); Home/End = min/max; write
debounced 300ms.

## Persistence

Keys: `mlbot:colwidths:preguntas|mensajes|detalle`. Value: JSON `{colId: px}`
(only resized cols). Lazy init reads once, wrapped in try/catch: parse, keep only
finite numbers re-clamped to `[min,max]`; corrupt/absent/disabled → `{}`, never
throw. Writes wrapped in try/catch (quota/private-mode safe). Write on `mouseup`
and debounced key-commit. `resetWidths` clears state + `removeItem`.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/hooks/useResizableColumns.js` | Create | Drag+keyboard resize, clamp, per-key persistence, reset |
| `frontend/src/hooks/useResizableColumns.test.js` | Create | Vitest+RTL units |
| `frontend/src/pages/MLQuestions.jsx` | Modify | `<colgroup>`, handles, reset button ×3 tables |
| `frontend/src/pages/MLQuestions.module.css` | Modify | Scoped fixed layout, col defaults, handle, focus, scroll |

Resizable cols — Preguntas: Pregunta, Item, Respuesta. Mensajes: Mensaje (col 2;
col 1 is the thin indent, stays fixed). Detalle: Pregunta, Item, Respuesta.
Badge/date/action columns stay fixed-width `<col>`.

## Handle UI + a11y + Reset

Handle: `<button>`/separator absolutely positioned `right:0; top:0; bottom:0;
width:6px; cursor:col-resize` inside a scoped `th{position:relative}` rule; focus
ring via `box-shadow: 0 0 0 2px var(--brand-primary-light)` (design token).
Keyboard-operable, `aria-label` per column. Reset: `btn-tesla ghost sm`
"Restablecer columnas" in each tab's filters/detail header, shown when any column
is resized.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | init empty; clamp min/max; keyboard step ±/Home/End; persistence round-trip (remount same key); reset clears state+storage; corrupt-storage fallback; out-of-range persisted value re-clamped | `renderHook`/`act`, keyboard path for determinism (jsdom `offsetWidth`=0 → `defaultWidth` baseline) |

Strict TDD: tests written RED first. Vitest is not CI-gated but required.

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file
classification, or process-integration boundary. Pure client-side UI + localStorage.

## Migration / Rollout

No migration. Fully additive, page-scoped. Rollback = delete hook, remove
colgroup/handles/reset from jsx, drop added css rules; stale localStorage keys
become inert.

## Open Questions

- [ ] Make Mensajes "Comprador·Pack" resizable too, or Mensaje only? (default: Mensaje only)

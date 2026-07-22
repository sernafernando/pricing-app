# Design: MLQuestions Resizable Columns via TanStack Table (Preguntas)

> Phase: design · Store: hybrid (openspec + Engram `sdd/ml-bot-resizable-columns-tanstack/design`) · Date: 2026-07-22

## Technical Approach

Adopt `@tanstack/react-table` v8.21.3 **as a headless column-sizing engine only** for the Preguntas
table in `MLQuestions.jsx`. One `useReactTable` instance owns `columnSizing` state + the drag lifecycle
that a hand-rolled resizer failed at 4× (#956). We consume ONLY header metadata + sizes; the body stays
the existing hand-rendered `.map()` + `Fragment` + `renderDetailRow`. Widths are applied through a
`<colgroup>` under `table-layout: fixed`, so one column grid governs BOTH the TanStack header row and the
untouched body rows. Persist per-table in localStorage, fail-safe. Scope: `MLQuestions.jsx` +
`MLQuestions.module.css` only; `table-tesla.css` read-only.

## Architecture Decisions

| Decision | Choice | Alternatives rejected | Rationale |
|---|---|---|---|
| Library usage | Sizing engine only (`columns`+`data:[]`, no row model) | Full `getRowModel`/`flexRender`; rebuild hand resizer | Library owns exactly the broken math/drag; zero risk to expand/thread/action JSX; tiny diff |
| Width application | `<colgroup><col width=getSize()>` + `<table style={{width:getTotalSize()}}>` under `table-layout: fixed` | Per-`<th>`/`<td>` inline widths | colgroup is one source of truth for header + body; fixed layout makes col widths authoritative |
| `table-layout:fixed` location | Scoped module class `styles.resizableTable` on the Preguntas `<table>` | Edit shared `table-tesla.css` | No blast radius to other Tesla tables (Historial/Mensajes/Config stay auto-layout) |
| #925 clamp coexistence | Leave `.cellQuestion/.cellItem/.cellAnswer` clamps as-is | Delete clamps | Under fixed layout cell `max-width` is inert (col width wins); clamps still serve the auto-layout tables that reuse these classes |
| Acciones column | `enableResizing:false`, `size=minSize=maxSize=280` | Resizable / smaller fixed | 280 > measured 267px worst case; the literal #956 failure — never clip |
| Persistence | localStorage `mlq:colsizing:preguntas`, try/catch → `{}` | Server / cross-device | Mirrors `LlmProviderRosterEditor` fail-safe parse already in this file |

## Columns Definition (the 7 Preguntas columns)

| id | header | size | minSize | maxSize | enableResizing |
|---|---|---|---|---|---|
| `pregunta` | Pregunta | 180 | 120 | 600 | true |
| `item` | Item | 110 | 100 | 400 | true |
| `estado` | Estado | 120 | — | — | **false** |
| `respuesta` | Respuesta (borrador) | 150 | 100 | 600 | true |
| `confianza` | Confianza | 90 | — | — | **false** |
| `cuentaRegresiva` | Cuenta regresiva | 175 | — | — | **false** |
| `acciones` | Acciones | **280** | **280** | 280 | **false** |

Default `getTotalSize()` ≈ **1105px**: fits a 1440px monitor minus the 240px sidebar (~1200px content) with
no scroll. On a true ~1024px notebook the `table-container-tesla` (already `overflow-x:auto`) scrolls
horizontally until the operator narrows columns — which then persists. This supersedes #925's clamp
scroll-avoidance goal because resizing gives explicit, sticky user control. Fixed sizes chosen to fit each
column's worst-case content: Estado longest badge ("Para la mañana" + injection flag), Cuenta regresiva
`"esperando aprobación"` (~176px incl. icon+padding), Acciones 4-button `taken_over` row.

### Acciones min-width proof (the #956 guarantee)
Buttons are `btn-tesla … sm` **without** `icon-only` → each carries `.sm` padding `0 16px` + `2px` border →
icon button ≈ **50px**, `"Editar"` text button ≈ **73px**. Worst case is `status==='taken_over'`:
chevron(50) + Editar(73) + PublicarAhora(50) + Retener(50) + 3×gap(4) + `td` padding(32) = **≈267px**.
`waiting` (4 icon buttons) ≈ 244px. Floor set to **280px** (>267 + margin). The headless gate MUST assert
`actionsCell.scrollWidth <= colWidth(acciones)` for a rendered `taken_over` row.

## Data Flow

    columns[] ─┐
               ├─► useReactTable({columns, data:[], columnResizeMode:'onChange',
    columnSizing (state, from localStorage init)   getCoreRowModel(), state:{columnSizing},
               │                                    onColumnSizingChange})
               │        ┌─ getHeaderGroups() ──► <thead> labels + resize grips (getResizeHandler)
               ├────────┤─ getVisibleLeafColumns().getSize() ──► <colgroup><col width>
               │        └─ getTotalSize() ──► <table style width>
    onColumnSizingChange(updater) ─► setColumnSizing(next) ─► debounced save → localStorage
                                                            (unchanged body .map + Fragment + renderDetailRow)

`data:[]` is fine: we never call `getRowModel()`. The body is still hand-rendered; the shared `<colgroup>`
sizes every `<tr>` (header + body), and the `<td colSpan={7}>` detail row spans the full grid unchanged.

## DOM Wiring (illustrative)

```jsx
<table className={`table-tesla striped ${styles.resizableTable}`} style={{ width: table.getTotalSize() }}>
  <colgroup>
    {table.getVisibleLeafColumns().map(col => <col key={col.id} style={{ width: col.getSize() }} />)}
  </colgroup>
  <thead className="table-tesla-head">
    <tr>{table.getFlatHeaders().map(h => (
      <th key={h.id} style={{ position:'relative' }}>
        {flexRender(h.column.columnDef.header, h.getContext())}
        {h.column.getCanResize() && (
          <span className={`${styles.resizeGrip} ${h.column.getIsResizing() ? styles.resizeGripActive : ''}`}
                onMouseDown={h.getResizeHandler()} onTouchStart={h.getResizeHandler()}
                role="separator" aria-orientation="vertical" aria-label={`Redimensionar ${h.column.id}`} />
        )}
      </th>))}
    </tr>
  </thead>
  <tbody className="table-tesla-body">{/* EXISTING hand-rendered .map() + Fragment + renderDetailRow — UNCHANGED */}</tbody>
</table>
```

Header labels stay plain strings (`header: 'Pregunta'`), so `flexRender` just returns text.

## Persistence & Reset (extractable, unit-testable)

```js
const KEY = 'mlq:colsizing:preguntas';
export function loadColumnSizing(key = KEY) {          // corrupt/absent → {} (never throws)
  try { const v = JSON.parse(localStorage.getItem(key) || '{}'); return v && typeof v === 'object' ? v : {}; }
  catch { return {}; }
}
export function saveColumnSizing(state, key = KEY) { try { localStorage.setItem(key, JSON.stringify(state)); } catch {} }
```

`useState(() => loadColumnSizing())`. `onColumnSizingChange = updater => setColumnSizing(prev => {
const next = typeof updater==='function'?updater(prev):updater; debouncedSave(next); return next; })`
(debounce ~200ms via a ref timer — `onChange` fires per mouse-move during drag). Unknown/stale column ids
in the stored object are inert: TanStack only reads sizes for columns that exist. Reset affordance:
`setColumnSizing({}); localStorage.removeItem(KEY)` → engine falls back to `columnDef.size`.

## Resize Grip UX + a11y (`MLQuestions.module.css`)

`.resizeGrip`: `position:absolute; top:0; right:0; height:100%; width:5px; cursor:col-resize;
touch-action:none; user-select:none;` transparent, becoming visible on `th:hover .resizeGrip` and
`.resizeGripActive` using design tokens (`var(--cf-accent-blue)` / `var(--cf-border-default)`). `th` gets
`position:relative`. `role="separator"` + `aria-orientation="vertical"` + `aria-label`. TanStack's drag is
mouse/touch only — **keyboard resize is a documented follow-up** (not shipped here).

## File Changes

| File | Action | Description |
|---|---|---|
| `frontend/src/pages/MLQuestions.jsx` | Modify | `columns` def, `useReactTable`, `flexRender` import, `<colgroup>`, `<th>` grips, table inline width, load/save/reset persistence; body JSX untouched |
| `frontend/src/pages/MLQuestions.module.css` | Modify | `.resizableTable{table-layout:fixed}`, `.resizeGrip`/`.resizeGripActive`, `th` position; scoped to Preguntas |
| `frontend/src/styles/table-tesla.css` | Read-only | Confirmed: no `table-layout`/`colgroup` rules; residual #956 specificity absent. No edit |

## Interfaces / Contracts

`columnSizing: Record<string, number>` (`{ [colId]: pxWidth }`). `columns: ColumnDef[]` with
`{ id, header, size, minSize, maxSize, enableResizing }`. Public helpers `loadColumnSizing(key)` /
`saveColumnSizing(state, key)`.

## Testing Strategy

| Layer | What | Approach |
|---|---|---|
| Unit (vitest/jsdom) | `loadColumnSizing`: valid / corrupt JSON / absent → `{}`; `saveColumnSizing` round-trip; reset removes key; unknown ids ignored | Mock `localStorage`; pure functions |
| Unit (vitest/RTL) | 3 resize grips render (`role="separator"`), fixed columns have none; header labels present | Render Preguntas table, query separators |
| **E2E — headless Chromium (BLOCKING GATE)** | jsdom does NOT lay out (hid this bug 4×). Load realistic LONG content (long question/answer, long nickname, `taken_over` all-buttons row). Measure `<col>`/`<th>` px width before/after a size change; assert Acciones `actionsCell.scrollWidth <= col width` (no clip); assert dragging visibly resizes; click chevron → detail spoiler opens, tab-switch works | Reuse this session's headless-Chromium harness (driven page + `getBoundingClientRect`) |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary. Purely client-side UI.

## Migration / Rollout

No migration. Additive to one table/one file + scoped CSS. Single-PR revert restores the plain auto-layout
table. Corrupt persisted state self-heals to defaults without a revert.

## Open Questions

- [ ] None blocking. Keyboard-driven resize deferred as an explicit follow-up (TanStack drag is pointer/touch only).

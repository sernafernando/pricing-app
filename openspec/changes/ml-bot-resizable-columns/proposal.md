# Proposal: ML-Bot Resizable Table Columns

> Change: `ml-bot-resizable-columns`
> Add user-resizable table columns (drag the column border) to the tables in
> `frontend/src/pages/MLQuestions.jsx`, persisting each column's width per browser
> in localStorage. Complementary to the responsive clamp() width fix already
> shipped in `MLQuestions.module.css`.

## Intent

Operators live in the ML-bot Preguntas/Mensajes screens reading long free-text
columns (Pregunta, Mensaje, Respuesta) and shorter fixed columns (Estado,
Confianza, Acciones). Today column widths are decided by the browser
(`table-layout: auto`) plus CSS clamp() caps; users cannot widen the column they
are reading or shrink noise, and the layout resets on every visit. The recent
responsive fix keeps tables inside a notebook screen but gives the user no
control. This change lets each user set the widths that fit their workflow and
have them stick across sessions on that browser.

Success = a user drags a column border, the column resizes live, and the width is
still there after a reload — per table, with a way to reset to defaults, and
reachable by keyboard.

## Scope

### In Scope
- Drag-to-resize handle on the right border of resizable columns in the
  MLQuestions tables: **Preguntas** tab, **Mensajes** tab, and the **detail/draft
  history** table that shares the same cell classes.
- A page-scoped `useResizableColumns` hook: `onMouseDown` on the handle →
  `onMouseMove` updates px width → `onMouseUp` persists to localStorage. Renders a
  `<colgroup><col>` per table with `table-layout: fixed` scoped to these tables.
- Per-table persistence in localStorage, keyed independently
  (e.g. `mlbot:colwidths:preguntas`, `:mensajes`, `:detalle`).
- A "user-resized" flag per column: manual px width overrides the clamp() default
  ONLY for columns the user actually dragged; untouched columns keep the existing
  responsive behavior.
- "Reset to default widths" affordance per table (clears that table's key).
- Keyboard-accessible resize (arrow keys while the handle is focused) and an
  `aria-label` per handle (e.g. "Redimensionar columna Pregunta").

### Out of Scope (non-goals)
- No backend, no new table/migration/endpoint; `ml_bot_config` is not touched.
- **Per-user cross-device sync** — explicitly a non-goal (localStorage is
  per-browser only).
- Drag-to-reorder or hide/show columns.
- Any change to the shared `frontend/src/styles/table-tesla.css` or to the ~50
  other pages that consume `.table-tesla` / `.table-container-tesla`.
- Adding a table library (react-table / TanStack) or any new npm dependency.

## Capabilities

### New Capabilities
- `ml-bot-resizable-columns`: user-resizable, per-browser-persisted column widths
  for the MLQuestions tables — drag + keyboard resize, per-table storage keys,
  reset affordance, coexisting with responsive clamp() defaults.

### Modified Capabilities
- None. Additive UI behavior scoped to MLQuestions; no existing spec-level
  behavior changes.

## Approach

**Chosen — small page-scoped custom hook + `<colgroup>` + scoped
`table-layout: fixed`.** Native `<table>` markup already used everywhere stays;
the hook manages a `widths` map (px) per table, writes a `<col>` per column, and
persists on mouse-up / key-commit. Manual widths are applied via inline dynamic
width on `<col>` (the one sanctioned inline-style exception — dynamic values),
which out-specifies the clamp() cap for resized columns only. All new CSS
(`table-layout: fixed`, `<colgroup>`, handle styling, focus ring) lives in
`MLQuestions.module.css`, design tokens only.

**Rejected — table library (react-table / TanStack).** Over-engineering for
"drag a border, remember the width"; forces a new dependency and a markup pattern
inconsistent with every other table-tesla page. Against the project's
boring-tech / no-over-engineering rule.

**Rejected — backend persistence in `ml_bot_config`.** That table is global
key/value (single row per key), not per-user; per-browser layout preference does
not justify a new per-user table + migration + endpoint. localStorage meets the
"persist across sessions" need with zero backend work.

## Business Rules & Edge Cases

- **Min/max width** per column (e.g. clamp px bounds) so a column can't collapse to
  0 or be dragged off-screen; enforced in the hook.
- **Ellipsis under `table-layout: fixed`**: fixed layout changes overflow;
  existing `text-overflow: ellipsis` truncation on `.cellQuestion/.cellAnswer/
  .cellItem` must be re-verified per column.
- **Three independent tables** → three independent storage keys; resizing one
  never affects another.
- **Only free-text/id columns are resizable** (Pregunta, Item, Respuesta, Mensaje);
  badge/action columns (Estado, Confianza, Acciones) stay auto/fixed.
- **Reset** clears that table's localStorage key and returns every column to its
  responsive clamp() default.
- **Corrupt/absent localStorage value** → fall back to defaults, never throw.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `frontend/src/pages/MLQuestions.jsx` | Modified | Render `<colgroup>`, resize handles, reset control; wire the hook |
| `frontend/src/pages/MLQuestions.module.css` | Modified | Scoped `table-layout: fixed`, `<col>`/handle/focus styles, resized-column override of clamp() |
| `frontend/src/hooks/useResizableColumns.js` (new) | New | Drag + keyboard resize, min/max clamp, per-key localStorage persistence, reset |
| `frontend/src/styles/table-tesla.css` | Untouched (read-only ref) | Must NOT change — shared by ~50 pages |
| `backend/app/models/ml_bot_config.py` | Untouched | Confirmed wrong fit; not touched |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `table-layout: fixed` breaks existing ellipsis/overflow in these tables | Med | Keep scoped to MLQuestions; re-verify truncation per column at design/verify |
| Manual px width and clamp() default conflict (specificity) | Med | Apply width only to user-resized columns via dynamic inline `<col>` width; leave untouched columns on clamp() |
| Blast radius onto other table-tesla pages | Low | All changes scoped to MLQuestions jsx + module.css; zero edits to shared table-tesla.css |
| Keyboard/a11y path missed (drag-only) | Med | In scope: arrow-key resize on focused handle + `aria-label`; part of QA checklist |
| localStorage disabled/full or stale keys | Low | Guard reads/writes; fall back to defaults; reset clears keys |

## Rollback Plan

Fully additive and page-scoped. To revert: delete
`useResizableColumns.js`, remove the `<colgroup>`/handles/reset from
`MLQuestions.jsx`, and drop the added rules from `MLQuestions.module.css`. No
shared CSS, backend, or other page is touched, so rollback cannot regress anything
outside MLQuestions. Users' localStorage keys become inert and can be ignored.

## Dependencies

- None new. React 18 + Vite + CSS Modules + design tokens already in place.
  No npm dependency, no backend, no migration.

## Success Criteria

- [ ] User can drag a column border in Preguntas, Mensajes, and the detail table
      and see the column resize live.
- [ ] Widths persist per table across reloads in the same browser.
- [ ] Resized columns override the clamp() default; untouched columns stay
      responsive.
- [ ] Min/max bounds prevent 0-width / runaway columns; ellipsis still truncates.
- [ ] "Reset to default widths" restores responsive defaults per table.
- [ ] Handles are keyboard-resizable and carry an `aria-label`.
- [ ] No edits to `table-tesla.css` and no regression on other table-tesla pages.

## Next Phase

`sdd-spec` and `sdd-design` (can run in parallel). Spec formalizes the resize/
persistence/reset/a11y requirements and the resizable-vs-fixed column list per
table. Design decides the exact hook API, the `<col>` width application vs clamp()
override mechanism, min/max bounds, storage-key naming, and the ellipsis
re-verification under `table-layout: fixed`.

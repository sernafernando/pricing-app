# ml-bot-resizable-columns Specification

> Phase: spec · Store: hybrid · New capability (no prior spec).
> Also persisted in Engram topic `sdd/ml-bot-resizable-columns/spec`.
> Formalizes `sdd/ml-bot-resizable-columns/proposal`.

## Purpose

User-resizable, per-browser-persisted column widths for the three MLQuestions
tables (Preguntas, Mensajes, detail/history), coexisting with the existing
responsive `clamp()` defaults, with keyboard access and a guaranteed
horizontal scrollbar when resized columns overflow the container.

## Column Classification

| Table | Resizable | Fixed/auto |
|---|---|---|
| Preguntas | Pregunta, Item, Respuesta (borrador) | Estado, Confianza, Cuenta regresiva, Acciones |
| Mensajes | Mensaje, Comprador · Pack | Recibido, Leído, Moderación |
| Detalle/historial | Pregunta, Item, Respuesta | Fecha, Estado |

## Requirements

### Requirement: Drag-to-resize
The system MUST let a user drag the right border of a resizable column's
header to change that column's pixel width live, bounded by a min and max
width enforced during drag.

#### Scenario: Live width update while dragging
- GIVEN the Preguntas table is rendered with `<colgroup>`/`table-layout: fixed`
- WHEN the user mouse-downs on the Pregunta column's handle and drags right
- THEN the column's rendered width updates continuously during the drag, without waiting for mouse-up

#### Scenario: Min/max bounds enforced
- GIVEN the user drags a handle toward 0px or far past the viewport edge
- WHEN the drag would exceed the column's configured min or max width
- THEN the width clamps at the bound and does not collapse to 0 or exceed the max

### Requirement: Keyboard resize
Each resize handle MUST be a focusable, keyboard-operable control with an
`aria-label` identifying the column.

#### Scenario: Arrow-key resize
- GIVEN a resize handle has keyboard focus
- WHEN the user presses ArrowLeft/ArrowRight
- THEN the column width decreases/increases by a fixed step, respecting the same min/max bounds as drag

#### Scenario: Handle is labeled
- GIVEN a screen reader user tabs to a resize handle
- WHEN the handle receives focus
- THEN an `aria-label` (e.g. "Redimensionar columna Pregunta") is announced

### Requirement: Per-table persistence
Each table's resized widths MUST persist to localStorage under its own key,
independent of the other two tables.

#### Scenario: Width survives reload
- GIVEN the user resizes the Item column in Preguntas and reloads the page
- WHEN the Preguntas table re-renders
- THEN the Item column restores the previously dragged width

#### Scenario: Tables are independent
- GIVEN the user resizes a column in Mensajes
- WHEN the Preguntas or detail table renders
- THEN neither is affected by the Mensajes resize

### Requirement: Coexistence with clamp() defaults
Only columns the user has actually resized MUST override the existing
`clamp()`-based responsive width; untouched columns MUST keep current
responsive behavior, including at the `1440px` breakpoint.

#### Scenario: Untouched column stays responsive
- GIVEN the user has never resized the Respuesta column
- WHEN the viewport crosses the `1440px` breakpoint
- THEN Respuesta continues to follow its `clamp()` width, unaffected by any other column's manual resize

#### Scenario: Resized column overrides clamp()
- GIVEN the user has dragged Pregunta to a manual width
- WHEN the table renders at any viewport size
- THEN Pregunta uses the manual width instead of its `clamp()` default

### Requirement: Reset to default
Each table MUST offer a control that clears that table's stored widths and
returns all columns to their responsive defaults.

#### Scenario: Reset restores defaults
- GIVEN Preguntas has one or more manually resized columns
- WHEN the user activates "Reset to default widths" for Preguntas
- THEN that table's localStorage key is cleared and every column returns to its `clamp()` default on next render

### Requirement: Ellipsis truncation under fixed layout
Existing ellipsis truncation on free-text cells MUST continue to work once
`table-layout: fixed` is applied.

#### Scenario: Long text still truncates
- GIVEN a Pregunta cell contains text wider than the column's current width
- WHEN the row renders under `table-layout: fixed`
- THEN the cell truncates with an ellipsis and the full text remains available via the existing `title` tooltip

### Requirement: Guaranteed horizontal scroll on overflow
`.table-container-tesla` (scoped via `.container :global(...)` in
`MLQuestions.module.css` only — `table-tesla.css` MUST NOT change) MUST
provide a visible, operable horizontal scrollbar whenever total resized
column width exceeds the container width, while sticky headers keep working.

#### Scenario: No overflow, no scrollbar
- GIVEN total column width is less than or equal to the container width
- WHEN the table renders
- THEN no horizontal scrollbar appears

#### Scenario: Overflow produces a usable scrollbar
- GIVEN the user drags a column wider than the remaining container width
- WHEN total column width exceeds the container width
- THEN `.table-container-tesla` scrolls horizontally, the scrollbar is visible and operable by mouse/trackpad, and the widened column is reachable by scrolling

#### Scenario: Sticky header persists under horizontal scroll
- GIVEN the table has overflowed and shows a horizontal scrollbar
- WHEN the user scrolls horizontally or vertically
- THEN the `thead` row remains sticky per existing behavior

### Requirement: Graceful localStorage fallback
The system MUST NOT throw or block rendering when localStorage is absent,
disabled, full, or holds a corrupt value for a table's key.

#### Scenario: Corrupt stored value
- GIVEN a table's localStorage key holds invalid/non-JSON data
- WHEN the table initializes
- THEN it falls back to responsive defaults for all columns, with no thrown error

#### Scenario: localStorage disabled or write fails
- GIVEN the browser blocks localStorage reads/writes
- WHEN the user resizes a column
- THEN the live resize still works for the session, and the failed persistence attempt does not surface an error to the user

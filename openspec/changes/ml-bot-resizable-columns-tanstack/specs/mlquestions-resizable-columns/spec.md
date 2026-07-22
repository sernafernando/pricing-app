# mlquestions-resizable-columns Specification

## Purpose

Define user-resizable, persisted column widths for the MLQuestions **Preguntas** table, powered by TanStack Table v8's column-sizing engine, without touching the existing hand-rolled body JSX (expand rows, buyer-history spoiler, tab switching, action buttons).

## Column Inventory (Preguntas table)

| Column | Resizable | Notes |
|---|---|---|
| Pregunta | Yes | long text, min/max bounded |
| Item | Yes | long text, min/max bounded |
| Respuesta (borrador) | Yes | long text, min/max bounded |
| Estado | No (fixed) | short badge content |
| Confianza | No (fixed) | short numeric/badge content |
| Cuenta regresiva | No (fixed) | short countdown text |
| Acciones | No (fixed, generous `minSize`) | up to 5 buttons: expand chevron + TakeOver/Editar/PublicarAhora/Retener |

## Requirements

### Requirement: Column Drag-to-Resize
The system MUST let an operator drag the resize handle on a resizable Preguntas column header (Pregunta, Item, Respuesta) to change that column's width, via TanStack's `column.getSize()` / `header.getResizeHandler()`. Fixed columns (Estado, Confianza, Cuenta regresiva, Acciones) MUST NOT expose a resize handle.

#### Scenario: Drag resizes a text column
- GIVEN the Preguntas table is rendered with default widths
- WHEN the operator drags the Pregunta column's resize handle wider
- THEN the Pregunta column's rendered width increases to match the drag position
- AND the table's total width (`getTotalSize()`) reflects the new sum

#### Scenario: Fixed columns have no resize handle
- GIVEN the Preguntas table is rendered
- WHEN the operator inspects the Estado, Confianza, Cuenta regresiva, or Acciones header
- THEN no resize handle is present for that header

### Requirement: Acciones Column Never Clips Buttons
The system MUST guarantee the Acciones column has a `minSize` sufficient to render the maximum simultaneous action set (expand chevron + TakeOver + Editar + PublicarAhora + Retener) fully visible and clickable, at all times, for every question status (`received`, `waiting`, `taken_over`, `pending_morning`, `failed`).

#### Scenario: All-buttons status at minimum width
- GIVEN a question row whose status shows the maximum button set (expand chevron + TakeOver + Editar + PublicarAhora + Retener)
- WHEN the Acciones column is at its `minSize`
- THEN every button remains fully visible and clickable, with no clipping or overflow-hidden truncation

#### Scenario: Regression guard for the #956 failure mode
- GIVEN the Acciones column width is derived from the fixed-width-sum model used before this change
- WHEN real headless-Chromium renders a row in any of the five statuses (received/waiting/taken_over/pending_morning/failed)
- THEN no button is clipped, overlapped, or pushed outside the visible column area

### Requirement: Long Content Truncation
Resizable text columns MUST truncate overflowing content under `table-layout: fixed` while preserving the existing `title` attribute tooltip so the full text remains discoverable on hover.

#### Scenario: Long question text truncates
- GIVEN a question with a very long `pregunta` text
- WHEN the Pregunta column is narrower than the text's natural width
- THEN the displayed text is truncated (e.g., ellipsis)
- AND the cell's `title` attribute still contains the full original text

### Requirement: Persisted Column Widths (Fail-Safe)
The system MUST persist the Preguntas table's `columnSizing` state to localStorage under a table-specific key, and MUST restore it on reload. Absent, corrupt, or disabled localStorage MUST fall back to default widths without throwing. Persisted state referencing stale/unknown column ids MUST be ignored for those ids (fail-open), never crashing.

#### Scenario: Widths persist across reload
- GIVEN the operator resized the Pregunta column and reloaded the page
- WHEN the Preguntas table mounts
- THEN the Pregunta column renders at the previously saved width

#### Scenario: Corrupt localStorage falls back to defaults
- GIVEN the persisted key contains malformed JSON
- WHEN the Preguntas table mounts
- THEN the table renders with default column widths
- AND no exception is thrown

#### Scenario: localStorage unavailable
- GIVEN localStorage access throws (e.g., disabled/private mode)
- WHEN the Preguntas table mounts or the operator resizes a column
- THEN the table still renders and resizes in-memory
- AND no exception propagates to the user

#### Scenario: Stale column ids in persisted state
- GIVEN the persisted `columnSizing` object contains an id for a column that no longer exists
- WHEN the Preguntas table mounts
- THEN the unknown id is ignored
- AND all current columns render with valid widths (persisted or default)

### Requirement: Reset to Default Widths
The system MUST provide a reset affordance that restores all Preguntas columns to their default sizes and clears the persisted localStorage key for this table.

#### Scenario: Reset restores defaults
- GIVEN the operator previously resized one or more columns
- WHEN the operator activates the reset-to-default control
- THEN all Preguntas columns return to their default widths
- AND the table's localStorage key no longer contains the prior custom sizing

### Requirement: Body Behavior Regression Guard
Adopting TanStack's sizing engine MUST NOT alter the existing expand/collapse detail row behavior, the "Historial del comprador" spoiler, or detail-tab switching, since the body remains hand-rendered (`data: []`, custom `.map()`).

#### Scenario: Expand and tab-switch still work after resize
- GIVEN the operator resized one or more Preguntas columns
- WHEN the operator expands a question row, opens the "Historial del comprador" spoiler, and switches detail tabs
- THEN all these interactions behave exactly as before the resizing change

### Requirement: Coexistence with Notebook-Fit Clamp
The Preguntas table's resizable column widths MUST coexist with the existing #925 notebook-fit clamp caps (max-width constraints for small viewports) without either mechanism silently overriding the other in an unintended way.

#### Scenario: Resize within clamp bounds
- GIVEN the notebook-fit clamp caps the table's maximum rendered width on a small viewport
- WHEN the operator resizes a column within that viewport
- THEN the column resizes as expected
- AND the overall table width still respects the clamp cap

### Requirement: Mandatory Real-Browser Verification Gate
The change MUST NOT be considered done based on jsdom/vitest unit coverage alone. A real headless-Chromium check with realistic LONG content (long question/answer text, long buyer nicknames, an all-buttons-visible status) MUST confirm: (1) dragging visibly resizes a column, (2) Acciones buttons remain usable and unclipped, (3) detail/history spoilers still open post-resize.

#### Scenario: Headless-Chromium gate passes before merge
- GIVEN the implementation is complete and jsdom-based unit tests pass
- WHEN a real headless-Chromium session loads the Preguntas table with realistic long content and an all-buttons status
- THEN dragging a resizable header visibly changes its width
- AND the Acciones buttons remain fully visible and clickable
- AND detail/history spoilers open correctly

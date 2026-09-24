# Delta for compras-oc-match-ui

## ADDED Requirements

### Requirement: Manual refresh restore-deleted warning

When the dedicated **Actualizar Factura/s y Pedido/s** control is shown, the UI MUST warn that the action re-reads the PDF and MAY restore numbers the operator deleted by hand. The warning MUST be the button `title` and/or helper text next to that control. The system MUST NOT add a tombstone. Accordion expand, button visibility, enqueue banner, and Retry + `refrescar_doc_refs` MUST stay unchanged.

#### Scenario: Warning on dedicated refresh

- GIVEN a `done` or `error` job and a user who can gestionar
- WHEN they expand the job
- THEN **Actualizar Factura/s y Pedido/s** is shown
- AND its `title` and/or nearby helper states it re-reads the PDF and may restore manually deleted numbers

#### Scenario: View-only still hides the control

- GIVEN a view-only user
- WHEN they expand a `done` or `error` job
- THEN the dedicated refresh control and its warning are not shown

#### Scenario: Expand UX unchanged

- GIVEN the operator selects a job
- WHEN detail is shown
- THEN detail still expands under that row
- AND it is not a side pane or modal

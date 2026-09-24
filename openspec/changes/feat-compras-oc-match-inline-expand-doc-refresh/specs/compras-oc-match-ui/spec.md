# Delta for compras-oc-match-ui

## ADDED Requirements

### Requirement: Dedicated Factura/s and Pedido/s refresh action

Detail MUST show `Actualizar Factura/s y Pedido/s` only for `done`|`error` plus `administracion.gestionar_ordenes_compra`. It MUST hide for view-only and for `queued`|`running`|`skipped`. Click MUST POST `…/refresh-doc-refs` empty-body and MUST NOT call retry/`queue_retry`. After accept, the UI MUST show a non-blocking banner (`Actualización encolada` or API `detail`) and MUST NOT block on extract or poll as `queued`|`running`. Error jobs MUST keep Reintentar plus checkbox `También actualizar Factura/s y Pedido/s` (`refrescar_doc_refs`). Detail MUST NOT expose `doc_refs_aplicado_at`.

#### Scenario: Button shown for done plus gestionar

- GIVEN a `done` job and a user who can gestionar
- WHEN they expand the job
- THEN the button `Actualizar Factura/s y Pedido/s` is shown

#### Scenario: Error keeps Retry plus checkbox

- GIVEN a retryable `error` job and a user who can gestionar
- WHEN they expand the job
- THEN the dedicated refresh button is shown
- AND Reintentar and the `refrescar_doc_refs` checkbox remain

#### Scenario: View-only hides refresh button

- GIVEN a `done` or `error` job and a view-only user
- WHEN they expand the job
- THEN the dedicated refresh button is not shown

#### Scenario: Hidden on queued running skipped

- GIVEN a job whose `status` is `queued`, `running`, or `skipped` and a user who can gestionar
- WHEN they expand the job
- THEN the dedicated refresh button is not shown

#### Scenario: Click enqueues without rematch spinner

- GIVEN the dedicated button is shown
- WHEN the operator clicks it and the POST is accepted
- THEN a non-blocking `Actualización encolada` banner appears
- AND no blocking spinner and no `queued`|`running` poll

## MODIFIED Requirements

### Requirement: Accordion expand under selected job row

Selecting a job MUST expand existing detail immediately under that row at full width. Detail MUST NOT render below the entire list. Pagination MUST stay after the table, not between the row and its detail. Same-row click MUST toggle collapse; another row MUST move the expand. Detail MUST NOT be a side pane or modal. Renglones MUST stay full width. Shared tables MUST offer optional `expandedRowId` + `renderExpandedRow` (off unless both set); omitted props MUST leave other tables unchanged.
(Previously: Selecting a job expanded detail below the entire list at full width.)

#### Scenario: Selected job expands under its row

- GIVEN the OC Match list is visible
- WHEN the operator selects job N
- THEN detail expands immediately under row N at full width
- AND renglones use that full width; other rows stay visible

#### Scenario: Same-row click toggles collapse

- GIVEN job N is selected and its detail is expanded
- WHEN the operator clicks row N again
- THEN the expand collapses

#### Scenario: Other row moves the expand

- GIVEN job N is expanded
- WHEN the operator selects job M
- THEN detail is under row M
- AND row N has no expand slot

#### Scenario: Detail is not below the whole list

- GIVEN the operator selects a job
- WHEN detail is shown
- THEN it is not a sibling below the entire list
- AND pagination is not between the selected row and its detail

#### Scenario: Side pane and modal are not used

- GIVEN the operator selects a job
- WHEN detail is shown
- THEN no side pane is used
- AND no modal is used

#### Scenario: Other tables unchanged when expand omitted

- GIVEN another Compras `DataTable` that omits `expandedRowId` and `renderExpandedRow`
- WHEN that table renders
- THEN its markup and row behavior are unchanged

## RENAMED Requirements

### Requirement: Expand-below full-width job detail → Accordion expand under selected job row

(Reason: Ops-ux `expand_below_full_width` is replaced by accordion under the selected row.)
(Migration: Update TabOcMatch tests/docs that cite “below the list”; keep not-aside/not-modal.)

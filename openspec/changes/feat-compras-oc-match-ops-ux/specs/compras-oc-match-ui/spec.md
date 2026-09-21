# Delta for compras-oc-match-ui

## ADDED Requirements

### Requirement: Pedido numero and phase on list and detail

List and detail MUST show `pedido_numero` from the job payload as the operator-facing pedido identity. The payload MUST still include `pedido_id`. While `status` is `running`, the status badge MUST remain “Procesando” and the phase MUST appear only as a secondary label. The UI MUST NOT treat `extracting`, `matching`, or `excel` as job statuses.

#### Scenario: List shows pedido numero

- GIVEN a job with `pedido_numero` `OC-100` and `pedido_id` `202`
- WHEN the operator views the list or expanded detail
- THEN `OC-100` is shown as the pedido identity
- AND `pedido_id` remains in the payload

#### Scenario: Running shows Procesando plus phase subtitle

- GIVEN a `running` job with `progress_phase` `matching`
- WHEN the operator views the row
- THEN the badge is still “Procesando”
- AND a secondary label shows the matching phase

### Requirement: Error column wrap and clamp

TabOcMatch error cells MUST wrap and clamp to approximately three lines. Full error text MUST be available via `title` and the expanded detail. Shared DataTable styles MUST NOT change.

#### Scenario: Long error clamps to three lines

- GIVEN a job whose error text exceeds three lines
- WHEN the operator views the list
- THEN the error cell wraps
- AND visible text is clamped to about three lines

#### Scenario: Full error remains in title and detail

- GIVEN a clamped error cell
- WHEN the operator inspects `title` or expands detail
- THEN the full error text is available

### Requirement: Expand-below full-width job detail

Selecting a job MUST expand its detail below the list at full interface width. The detail MUST NOT be a side pane or a modal. Renglones MUST use the full interface width.

#### Scenario: Selected job expands below the list

- GIVEN the OC Match list is visible
- WHEN the operator selects a job
- THEN detail expands below the list at full width
- AND renglones use that full width

#### Scenario: Side pane and modal are not used

- GIVEN the operator selects a job
- WHEN detail is shown
- THEN no side pane is used
- AND no modal is used

## MODIFIED Requirements

### Requirement: Tab visibility and poll

The Compras module MUST add an OC Match tab visible only with `administracion.ver_ordenes_compra`. The tab MUST poll job status while `queued` or `running` and MUST stop when status is `done`, `error`, or `skipped`. Polling MUST remain on `queued|running` when `progress_phase` is set. `progress_phase` values MUST NOT be poll statuses.
(Previously: Poll set was already `queued|running`; no contract that phase must not change it.)

#### Scenario: Tab hidden without view permiso

- GIVEN a user lacks `administracion.ver_ordenes_compra`
- WHEN they open Compras
- THEN the OC Match tab is not rendered

#### Scenario: Poll until terminal status

- GIVEN a `queued` or `running` job and the tab is open
- WHEN status remains non-terminal
- THEN the UI keeps polling
- WHEN status becomes `done`, `error`, or `skipped`
- THEN polling stops

#### Scenario: Phase does not change the poll set

- GIVEN a `running` job with `progress_phase` `matching` and the tab is open
- WHEN status remains `running`
- THEN the UI keeps polling
- AND MUST NOT treat `extracting`, `matching`, or `excel` as poll statuses

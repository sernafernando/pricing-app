# Compras OC Match UI Specification

## Purpose

Compras tab (Cheques list pattern) that polls job status and shows renglones, acta, and Excel download. Mail is not a UI channel.

## Requirements

### Requirement: Tab visibility and poll

The Compras module MUST add an OC Match tab visible only with `administracion.ver_ordenes_compra`. The tab MUST poll job status while `queued` or `running` and MUST stop when status is `done`, `error`, or `skipped`.

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

### Requirement: Renglones, acta, download, retry, filters

The tab MUST show renglones and acta from Pricing DB. Download MUST request the job Excel. Retry MUST be offered for reclaim or `error` jobs only when the user has `administracion.gestionar_ordenes_compra`. List MUST support status filter `queued|running|done|error` and MAY include `skipped`.

#### Scenario: Done job shows artifacts

- GIVEN a `done` job with renglones, acta, and Excel
- WHEN the operator opens the job
- THEN renglones and acta are shown and Excel download succeeds

#### Scenario: Retry hidden for view-only

- GIVEN a retryable `error` job and a view-only user
- WHEN they open the tab
- THEN retry is not available
- AND they can still view status, renglones, and acta

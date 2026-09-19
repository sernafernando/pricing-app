# Compras OC Match Jobs Specification

## Purpose

Enqueue, persist, list, reclaim, retry, and download OC-match jobs after pedido adjunto upload. Pricing DB is the source of truth. Sync is `BackgroundTasks` plus a job table. Mail is OFF.

## Requirements

### Requirement: Pedido-adjunto trigger and MIME gate

The system MUST enqueue an OC-match job only after `subir_adjunto_pedido` commits. Pedido create, OP adjuntos, and NC adjuntos MUST NOT enqueue. Gemini work MUST enqueue only for PDF, JPG, JPEG, PNG, or WEBP. Office and unknown types MUST remain valid adjuntos and MUST yield `skipped` or `error` without Gemini.

#### Scenario: Create pedido does not enqueue

- GIVEN an operator creates a pedido with no adjunto
- WHEN create succeeds
- THEN no OC-match job exists for that pedido

#### Scenario: PDF enqueues; Office skips Gemini

- GIVEN a pedido exists
- WHEN a PDF adjunto is uploaded
- THEN a `queued` job is persisted and a background task is scheduled
- WHEN an XLSX adjunto is uploaded
- THEN the adjunto is stored, the job is `skipped` or `error`, and Gemini is not called

#### Scenario: OP or NC adjunto does not enqueue

- GIVEN an OP or NC adjunto upload
- WHEN the upload commits
- THEN no OC-match job is created

### Requirement: Idempotency and 15-minute reclaim

Jobs MUST be unique on `(pedido_id, attachment_id)`. A new adjunto MUST create a new job. The same adjunto with an existing `done` or `running` job MUST reuse or skip that job. List and detail MUST present a job `running` longer than 15 minutes as retryable `error`.

#### Scenario: Same adjunto reuses; new file is a new job

- GIVEN a `done` job for `(pedido_id, attachment_id)`
- WHEN the same adjunto is processed again
- THEN no second job is created and the existing job is returned
- WHEN a different adjunto is uploaded on the same pedido
- THEN a distinct job is created

#### Scenario: Stale running becomes retryable error

- GIVEN a job has been `running` for more than 15 minutes
- WHEN list or detail is requested
- THEN the job is presented as retryable `error`

### Requirement: List, retry, download, permisos, mail OFF

List MUST return jobs for pedidos the caller can access, filterable by `queued|running|done|error`, and MAY include `skipped`. View and download MUST require `administracion.ver_ordenes_compra`. Retry MUST require `administracion.gestionar_ordenes_compra`. Download MUST serve the persisted Excel file. The system MUST NOT send mail on enqueue, skip, retry, or complete.

#### Scenario: View and retry permisos

- GIVEN a user lacks `administracion.ver_ordenes_compra`
- WHEN they request the job list
- THEN the API returns 403
- GIVEN a view-only user and a retryable `error` job
- WHEN they request retry
- THEN the API returns 403

#### Scenario: No mail on job lifecycle

- GIVEN a job is enqueued, skipped, retried, or completed
- WHEN that transition persists
- THEN Pricing sends no mail
